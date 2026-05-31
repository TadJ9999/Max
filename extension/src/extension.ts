import * as vscode from "vscode";
import { detectCommand, type DslMatch } from "./dsl";
import { fimComplete, getConfig, getHealth, streamCommand } from "./engine";

let status: vscode.StatusBarItem;
let applying = false; // true while we're editing the doc, so auto-trigger ignores our own edits
let runToken: vscode.CancellationTokenSource | null = null;

export function activate(context: vscode.ExtensionContext) {
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "max.runCommand";
  context.subscriptions.push(status);
  void refreshStatus();
  const poll = setInterval(() => void refreshStatus(), 5000);
  context.subscriptions.push({ dispose: () => clearInterval(poll) });

  context.subscriptions.push(
    vscode.commands.registerCommand("max.runCommand", () => void runAtCursor()),
    vscode.commands.registerCommand("max.toggleAutocomplete", toggleAutocomplete),
    vscode.workspace.onDidChangeTextDocument(onDocChange),
    vscode.languages.registerInlineCompletionItemProvider(
      { pattern: "**" },
      { provideInlineCompletionItems },
    ),
  );
}

export function deactivate() {
  runToken?.cancel();
}

// ---- status bar --------------------------------------------------------

async function refreshStatus() {
  if (applying) return; // don't clobber the live "running" state
  const h = await getHealth();
  if (h) {
    status.text = "$(zap) Max";
    status.tooltip = `Max engine ${h.version} — online`;
    status.backgroundColor = undefined;
  } else {
    status.text = "$(zap) Max $(circle-slash)";
    status.tooltip = "Max engine offline — start the Max app or run the engine";
    status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }
  status.show();
}

// ---- DSL command: detect, stream, inline-replace -----------------------

async function runAtCursor() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return;
  const sel = editor.selection;
  const useSelection = !sel.isEmpty;
  const range = useSelection
    ? new vscode.Range(sel.start, sel.end)
    : trimmedLineRange(editor.document, sel.active.line);
  const raw = editor.document.getText(range);
  const match = detectCommand(raw);
  if (!match) {
    vscode.window.showInformationMessage(
      "Max: no command here. Use  . generate .   .. document ..   ~ fix ~  (optionally @ # ! before).",
    );
    return;
  }
  await runMatch(editor, range, match);
}

async function runMatch(editor: vscode.TextEditor, range: vscode.Range, match: DslMatch) {
  runToken?.cancel(); // supersede any in-flight run
  const cts = new vscode.CancellationTokenSource();
  runToken = cts;

  const start = range.start;
  const meta: { model?: string } = {};
  applying = true;
  status.text = match.cloud ? "$(cloud) Max ☁ cloud…" : "$(sync~spin) Max…";
  status.tooltip = match.cloud ? "Running on a cloud model — this leaves your machine" : "Max is generating…";

  try {
    // Clear the command text, then stream the result into its place.
    await editor.edit((b) => b.replace(range, ""), { undoStopBefore: true, undoStopAfter: false });
    let acc = "";
    let end = start;
    for await (const delta of streamCommand(match.text, cts.token, meta)) {
      if (cts.token.isCancellationRequested) break;
      acc += delta;
      const prev = new vscode.Range(start, end);
      await editor.edit((b) => b.replace(prev, acc), {
        undoStopBefore: false,
        undoStopAfter: false,
      });
      end = endPosition(start, acc);
    }
    if (!acc.trim()) {
      vscode.window.showWarningMessage("Max: the model returned nothing.");
    }
  } catch (e) {
    vscode.window.showErrorMessage(`Max: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    applying = false;
    if (runToken === cts) runToken = null;
    cts.dispose();
    status.text = meta.model ? `$(zap) Max · ${meta.model}` : "$(zap) Max";
    status.tooltip = meta.model ? `Last run: ${meta.model}` : "Max";
  }
}

// ---- auto-trigger on the closing delimiter -----------------------------

let autoTimer: ReturnType<typeof setTimeout> | undefined;

function onDocChange(e: vscode.TextDocumentChangeEvent) {
  if (applying) return;
  if (getConfig("trigger", "auto") !== "auto") return;
  const editor = vscode.window.activeTextEditor;
  if (!editor || e.document !== editor.document) return;
  const change = e.contentChanges[e.contentChanges.length - 1];
  if (!change) return;
  const last = change.text.slice(-1);
  if (last !== "." && last !== "~") return; // only react to a closing delimiter

  const line = editor.selection.active.line;
  if (!detectCommand(editor.document.lineAt(line).text)) return;

  if (autoTimer) clearTimeout(autoTimer);
  autoTimer = setTimeout(() => {
    const ed = vscode.window.activeTextEditor;
    if (!ed || ed.document !== e.document) return;
    const range = trimmedLineRange(ed.document, line);
    const match = detectCommand(ed.document.getText(range));
    if (match) void runMatch(ed, range, match);
  }, 250);
}

// ---- ghost-text FIM autocomplete ---------------------------------------

const MAX_CTX = 2000;

async function provideInlineCompletionItems(
  document: vscode.TextDocument,
  position: vscode.Position,
  _context: vscode.InlineCompletionContext,
  token: vscode.CancellationToken,
): Promise<vscode.InlineCompletionItem[] | undefined> {
  if (!getConfig("autocomplete", true) || applying) return;
  // Debounce: wait out rapid typing, bail if superseded/cancelled.
  await new Promise((r) => setTimeout(r, getConfig("completionDelayMs", 300)));
  if (token.isCancellationRequested) return;

  const offset = document.offsetAt(position);
  const text = document.getText();
  const prefix = text.slice(Math.max(0, offset - MAX_CTX), offset);
  const suffix = text.slice(offset, offset + MAX_CTX);
  if (!prefix.trim()) return;

  const completion = await fimComplete(prefix, suffix, token);
  if (!completion || token.isCancellationRequested) return;
  return [new vscode.InlineCompletionItem(completion, new vscode.Range(position, position))];
}

// ---- helpers -----------------------------------------------------------

function toggleAutocomplete() {
  const cfg = vscode.workspace.getConfiguration("max");
  const next = !cfg.get<boolean>("autocomplete", true);
  void cfg.update("autocomplete", next, vscode.ConfigurationTarget.Global);
  vscode.window.showInformationMessage(`Max autocomplete ${next ? "on" : "off"}`);
}

// The command text on a line, ignoring leading indentation and trailing space.
function trimmedLineRange(document: vscode.TextDocument, lineNo: number): vscode.Range {
  const line = document.lineAt(lineNo);
  const startChar = line.firstNonWhitespaceCharacterIndex;
  const endChar = line.text.trimEnd().length;
  return new vscode.Range(lineNo, startChar, lineNo, Math.max(startChar, endChar));
}

// Position after inserting `text` starting at `start`.
function endPosition(start: vscode.Position, text: string): vscode.Position {
  const lines = text.split("\n");
  if (lines.length === 1) {
    return new vscode.Position(start.line, start.character + text.length);
  }
  return new vscode.Position(start.line + lines.length - 1, lines[lines.length - 1].length);
}
