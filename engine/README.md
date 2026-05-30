# Max Engine

The brain of Max: provider routing, the command DSL, and the delegate system.
Python + FastAPI.

## Layout

```
max_engine/
├── main.py            # FastAPI app (/health, /parse; chat + sessions are TODO)
├── config.py          # sigils, per-task models, providers, allowlist, delegate cfg
├── dsl/parser.py      # the . / .. + sigil grammar  (implemented + tested)
├── router.py          # parsed command -> (provider, model)
├── providers/         # adapter interface + Ollama (local) & Claude (cloud) stubs
└── delegate/          # session manager + VRAM-aware scheduler
```

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # runs the DSL parser tests
uvicorn max_engine.main:app --reload
```

Try the parser over HTTP:

```bash
curl -s localhost:8000/parse -H 'content-type: application/json' \
  -d '{"text": "!. add a retry decorator ."}' | python -m json.tool
```
