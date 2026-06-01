// Minimal line-based diff for the AI plan preview. LCS dynamic programming —
// fine for the file sizes the editor allows (<= 500 KB). Returns a flat list of
// rows tagged add / del / ctx so the panel can render a unified diff.

export type DiffRow = { type: "add" | "del" | "ctx"; text: string };

const MAX_LINES = 4000; // guard against pathological O(n*m) blow-ups

export function diffLines(oldStr: string, newStr: string): DiffRow[] {
  const a = oldStr.length ? oldStr.split("\n") : [];
  const b = newStr.length ? newStr.split("\n") : [];

  // Too big to diff cheaply — fall back to a coarse replace block.
  if (a.length > MAX_LINES || b.length > MAX_LINES) {
    return [
      ...a.map((t): DiffRow => ({ type: "del", text: t })),
      ...b.map((t): DiffRow => ({ type: "add", text: t })),
    ];
  }

  const n = a.length;
  const m = b.length;
  // lcs[i][j] = length of LCS of a[i:] and b[j:]
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: "ctx", text: a[i] });
      i++; j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ type: "del", text: a[i] });
      i++;
    } else {
      rows.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < n) rows.push({ type: "del", text: a[i++] });
  while (j < m) rows.push({ type: "add", text: b[j++] });
  return rows;
}

export function diffStats(rows: DiffRow[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const r of rows) {
    if (r.type === "add") added++;
    else if (r.type === "del") removed++;
  }
  return { added, removed };
}
