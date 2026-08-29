# SQLSEED-UI PLUGIN

**Last updated:** 2026-08-30

## OVERVIEW

Web UI for sqlseed: a FastAPI backend wrapping `DataOrchestrator` + the sqlseed-ai self-healing subsystem, plus a dependency-free static frontend (vanilla ES modules, NO build toolchain, NO node_modules). Navicat-style information architecture (redesigned 2026-08-30 from 5 Navicat Data Generator reference screenshots): a three-step generation wizard (target → object tree + per-column property panel → topo-ordered preview/fill) and a three-pane data browser, plus the heal lab and acceptance cockpit as standalone entries. Serves two purposes:

1. **Visual workbench** — connection management, wizard-driven column configuration (generator dropdown + params + single-column live preview + NULL%/unique), topo-ordered generation, three-pane data browsing, YAML save/load.
2. **Acceptance cockpit** — every core feature (9-level mapping, constraint solving, contract validation, repair strategies, auto-heal) is exposed as an observable endpoint. The meta page counts (35 generators, 12 hooks) must match the code — it is the UI-side equivalent of `tests/test_doc_sync.py`.

sqlseed-ai is an **optional** dependency: heal endpoints degrade to `{"ok": false, "reason": ...}` / HTTP 503 without it. Auto-heal additionally requires an LLM API key.

## STRUCTURE

```
sqlseed-web/
├── pyproject.toml               # sqlseed + fastapi + uvicorn + pyyaml; [ai] extra = sqlseed-ai
├── src/sqlseed_web/
│   ├── app.py                   # create_app() factory + `sqlseed-web` console script (uvicorn, port 8630)
│   ├── state.py                 # UIState singleton: connection registry + job tracker (threading)
│   ├── api.py                   # ALL routers under /api (see endpoint map below)
│   ├── __main__.py              # python -m sqlseed_web
│   └── static/                  # frontend served at /
│       ├── index.html           # shell: topbar nav + #main mount
│       ├── style.css            # dark theme, GitHub-ish palette
│       └── js/
│           ├── api.js           # fetch helpers + h()/table()/msg() DOM utils + shared store
│           ├── app.js           # hash router: connect / wizard / browse / heal / meta
│           ├── dropdown.js      # custom dropdown (page-DOM panel; native <select> popups misposition in WebViews)
│           ├── filepicker.js    # server-side directory-browse modal (the real "choose file" button)
│           ├── labels.js        # generator Chinese labels + tree column annotations (外键/序列/语义)
│           ├── tree.js          # checkable table/column tree (wizard step2 left pane)
│           ├── genform.js       # column property panel: generator dropdown + dynamic params + single-column preview + NULL%/unique
│           └── pages/           # connect / wizard (3-step) / browse (3-pane) / heal / meta
└── tests/test_api.py            # TestClient + real SQLite (never mock the DB layer — Pitfall #13)
```

## ENDPOINT MAP (`api.py`)

| Prefix | Endpoints | Backing core API |
|--------|-----------|------------------|
| `/api/meta` | `generators`, `hooks`, `providers`, `ai`, `info`, `locales`, `dialects` | `GeneratorDispatchMixin.GENERATOR_MAP`, `BaseProvider._gen_*` signatures, `SqlseedHookSpec.sqlseed_spec` markers, `AIConfig.from_env()`, curated locale list (sync with `mimesis_provider.set_locale` map) |
| `/api/fs` | `browse?path=&all_files=` | server-side directory listing for the file-picker modal (browsers never expose absolute paths) |
| `/api/connections` | POST/GET/DELETE | `DataOrchestrator(target, provider_name, locale)` — target accepts SQLite path or URL. GET returns same-target grouping metadata (`group_key` normalized via `_normalize_target`: paths resolve absolute, `sqlite:///` URLs collapse to bare paths, other URLs keep scheme with password stripped; `group_index`/`group_size` drive the 主连接/并行 N badges) |
| `/api/connections/{id}/tables/{t}` | `schema`, `mapping`, `yaml-template`, `rows` | `get_column_info` / `get_column_mapping` (9-level chain output) / `get_foreign_keys` / `query()` |
| `/api/connections/{id}/topo-order` | GET `?tables=a,b` | `get_topological_table_order()` — wizard step3 "表生成顺序" (Navicat parity) |
| `/api/connections/{id}` | `preview`, `fill`, `query` | `preview_table()` / `fill_table()` (background thread + job polling) / read-only SELECT guard |
| `/api/config` | `parse`, `serialize` | `load_config` via temp file (validation parity with CLI) |
| `/api/connections/{id}/heal` | `validate`, `repair`, `auto` | L2 `FastValidator`, L3 `RepairPipeline`, L5 `AutoHealOrchestrator` (wired like `ai_commands._run_auto_heal_v4`); `auto` honors the session AI override (`backend` param added) |
| `/api/ai/config` | GET/POST | session-level AI override (backend/model/api_key/base_url) merged over env defaults — in-UI online/local LLM switching without env edits or restarts |
| `/api/jobs` | list + `{job_id}` status | job registry; live fill progress via `get_row_count` delta |

Connection kinds (UI): `sqlite` (local db file + file-picker modal), `postgresql` (field form → `postgresql://user:pass@host:port/db`), `url` (raw SQLAlchemy URL, reserved for future databases).

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add an API endpoint | `api.py` | single-file router; follow the `_conn_or_404` + try/except pattern |
| Add a page | `static/js/pages/*.js` + `app.js` router table | export `render()` (+ optional `mount()`); hash `#/name` |
| Change connection lifecycle | `state.py` | one DataOrchestrator per conn; per-connection lock serializes fills |
| Add heal-lab capability | `api.py` heal section | lazy-import sqlseed_ai; degrade gracefully when missing |
| Styling | `static/style.css` | CSS vars in `:root`; pill/table/panel primitives |

## CONVENTIONS

- **from __future__ import annotations** at every file top (ruff)
- **Never mock the DB layer** in tests — real SQLite via `tmp_path` fixtures
- **Job result race**: assign `job.result` BEFORE `job.status = "done"` (polling endpoint reads both; status-first creates an empty-result race — fixed once, keep it that way)
- **pluggy markers**: hook firstresult lives on `fn.sqlseed_spec` (project_name + "_spec"), not `_hookspec`
- **GenerationResult.count** is the inserted-row count (there is no `rows_inserted` attribute)
- **Frontend**: ES modules only, no bundler, no external CDN; all state in `api.js` `store` (connId survives page switches)
- **SQL console** accepts single SELECT statements only (guard in `run_query`)

## ANTI-PATTERNS

- **NEVER** use native `<select>` in pages — its option popup is rendered by the browser UI layer and mispositions (detached from the control) in embedded WebViews / IDE preview browsers; page CSS cannot fix it. Use `createDropdown()` from `dropdown.js` (page-DOM panel absolutely positioned 4px below the button; module-level instances survive page switches and are re-mounted by `render()`).
- **NEVER** rely on `input { min-width }` applying to checkboxes — the global rule is scoped to `input:not([type=checkbox]):not([type=radio])`; a 160px-wide checkbox once pushed its label text 147px away from the box.
- **NEVER** register this package under `[project.entry-points."sqlseed"]` — it is a standalone app, not a generation plugin
- **NEVER** import `sqlseed_ai` at module top in `api.py` — lazy import inside endpoints; the package must work without the AI plugin
- **NEVER** let the HTTP handler block on `fill_table` — always dispatch to a background thread job
- **NEVER** run two fills on the same connection concurrently — take `state.connection_lock(conn_id)` first
- **ALWAYS** validate table names via `validate_table_name()` + `quote_identifier()` before SQL interpolation

## COMMANDS

```bash
pip install -e "./plugins/sqlseed-web"          # + [ai] extra for the heal lab
sqlseed-web                                     # serve at http://127.0.0.1:8630
pytest plugins/sqlseed-web/tests/ -q            # 32 tests
ruff check plugins/sqlseed-web/ && mypy plugins/sqlseed-web/src/
```

## GOTCHAS

- **Same-target connections are legal but grouped**: multiple connections to one SQLite file work (read concurrency + serialized writes, verified by concurrent fill tests), and `list_connections()` tags them 主连接/并行 N so users don't lose track. Do not "deduplicate" connections silently — the isolation (per-connection provider/locale) is a feature.
- **Port 8630** is the default (uvicorn factory mode `sqlseed_web.app:create_app`).
- **Page-render timing**: `render()` runs BEFORE the page is mounted into the DOM — never use `document.getElementById` inside `render()` for elements the page itself creates. Pass the element reference instead (see `renderKind(body)` in connect.js; the getElementById variant once caused a blank file-input row on first load). Use the `mount()` hook for post-mount DOM lookups.
- **`out.append(arr)` renders `[object HTMLDivElement]`** — native `Element.append` does NOT spread arrays. When a render helper returns an array of nodes, always `out.append(...nodes)`. Found live in heal.js L2 violations rendering.
- **Boolean attrs in `h()`**: `setAttribute('disabled', false)` still disables the element (attribute presence wins). `h()` handles boolean values by add/remove attribute — pass real booleans (`disabled: atFirst`), never strings.
- **`ForeignKeyInfo` field names are singular** (`column` / `ref_table` / `ref_column`), not plural — the schema page FK table once rendered empty cells reading `fk.columns`.
- **File picker is server-side** (`/api/fs/browse`): browsers never expose absolute paths from `<input type="file">`; the local server lists directories instead. Default view hides non-DB files (toggle via `all_files=true`); hidden dotfiles always skipped.
- **Locale codes are faker-style** (`zh_CN`, `en_US`); `MimesisProvider.set_locale` maps them to mimesis short codes. Keep `SUPPORTED_LOCALES` in api.py in sync with that map — a test enforces the overlap.
- **Fill progress** is approximated by row-count delta polling (batches commit progressively); there is no in-fill callback hook.
- **`load_config` does NOT validate generator names** — unknown generators pass `/api/config/parse` and only fail at fill time (`UnknownGeneratorError`) or as heal violations. This is the core contract; tests document it.
- **YAML template endpoint** maps URL-prefixed targets to `url:` key, paths to `db_path:`.
- **vite/client 404** in browser console is from the browser environment, not this app (no Vite anywhere in the repo).
