# SQLSEED-UI PLUGIN

**Last updated:** 2026-08-30

## OVERVIEW

Web UI for sqlseed: a FastAPI backend wrapping `DataOrchestrator` + the sqlseed-ai self-healing subsystem, plus a dependency-free static frontend (vanilla ES modules, NO build toolchain, NO node\_modules). 参考工具-style information architecture (redesigned 2026-08-30 from 5 参考工具 Data Generator reference screenshots): a three-step generation wizard (target → object tree + per-column property panel → topo-ordered preview/fill) and a three-pane data browser, plus AI 分析与修复 (formerly 自愈实验室) and the acceptance cockpit (系统面板) as standalone entries. Serves two purposes:

1. **Visual workbench** — connection management, wizard-driven column configuration (generator dropdown + params + single-column live preview + NULL%/unique), topo-ordered generation, three-pane data browsing, YAML save/load. Step 2 carries an **AI 一键生成配置** button with readiness gating (installed + local backend, or online backend with key) and a click-time connectivity probe: L5 auto-heal produces a full YAML which is parsed back into the tree selection + per-column configs for the user to fine-tune (replaces current column configs, never writes the DB). After backfill the tree annotations and the right-hand property panel refresh immediately, and the tree selection persists across step navigation.
2. **Acceptance cockpit** — every core feature (9-level mapping, constraint solving, contract validation, repair strategies, auto-heal) is exposed as an observable endpoint. The meta page counts (36 generators, 12 hooks) must match the code — it is the UI-side equivalent of `tests/test_doc_sync.py`.

sqlseed-ai is an **optional** dependency: heal endpoints degrade to `{"ok": false, "reason": ...}` / HTTP 503 without it, and the AI page shows an onboarding card (install command + what still works without AI). Auto-heal additionally requires an LLM backend — local backends (Ollama / LM Studio) need NO API key, only a running server (`/api/ai/test-connection` probes and reports this in friendly Chinese).

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
│           ├── dropdown.js      # custom dropdown (page-DOM panel; native <select> popups misposition in WebViews); options support `group` headers and `disabled` placeholders
│           ├── filepicker.js    # server-side directory-browse modal; mode: `file` (DB files) / `dir` (pick a folder — bytes.folder)
│           ├── labels.js        # generator + param Chinese labels (PARAM_LABELS) + 参考工具 7-class grouping (GEN_CATEGORIES) + tree column annotations (外键/序列/语义)
│           ├── tree.js          # checkable table/column tree (wizard step2 left pane)
│           ├── genform.js       # column property panel (7-segment 参考工具 layout): grouped generator dropdown + dynamic params + debounced auto preview + clipped common area (NULL%/unique)
│           └── pages/           # connect / wizard (3-step) / browse (3-pane) / heal / meta
└── tests/test_api.py            # TestClient + real SQLite (never mock the DB layer — Pitfall #13)
```

## ENDPOINT MAP (`api.py`)

| Prefix                             | Endpoints                                                               | Backing core API                                                                                                                                                                                                                                                                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/meta`                        | `generators`, `hooks`, `providers`, `ai`, `info`, `locales`, `dialects` | `GeneratorDispatchMixin.GENERATOR_MAP`, `BaseProvider._gen_*` signatures, `SqlseedHookSpec.sqlseed_spec` markers, `AIConfig.from_env()` **merged with the session AI override** (effective backend/model/key), curated locale list (sync with `mimesis_provider.set_locale` map)                                                                         |
| `/api/fs`                          | `browse?path=&all_files=`                                               | server-side directory listing for the file-picker modal (browsers never expose absolute paths)                                                                                                                                                                                                                                                           |
| `/api/connections`                 | POST/GET/DELETE                                                         | `DataOrchestrator(target, provider_name, locale)` — target accepts SQLite path or URL. GET returns same-target grouping metadata (`group_key` normalized via `_normalize_target`: paths resolve absolute, `sqlite:///` URLs collapse to bare paths, other URLs keep scheme with password stripped; `group_index`/`group_size` drive the 主连接/并行 N badges) |
| `/api/connections/{id}/tables/{t}` | `schema`, `mapping`, `yaml-template`, `rows`                            | `get_column_info` / `get_column_mapping` (9-level chain output) / `get_foreign_keys` / `query()`                                                                                                                                                                                                                                                         |
| `/api/connections/{id}/topo-order` | GET `?tables=a,b`                                                       | `get_topological_table_order()` — wizard step3 "表生成顺序" (参考工具 parity)                                                                                                                                                                                                                                                                                  |
| `/api/connections/{id}`            | `preview`, `fill`, `query`                                              | `preview_table()` / `fill_table()` (background thread + job polling) / read-only SELECT guard                                                                                                                                                                                                                                                            |
| `/api/config`                      | `parse`, `serialize`                                                    | `load_config` via temp file (validation parity with CLI)                                                                                                                                                                                                                                                                                                 |
| `/api/connections/{id}/heal`       | `validate`, `repair`, `auto`                                            | L2 `FastValidator`, L3 `RepairPipeline`, L5 `AutoHealOrchestrator` (wired like `ai_commands._run_auto_heal_v4`); `auto` honors the session AI override (`backend` param added)                                                                                                                                                                           |
| `/api/ai/config`                   | GET/POST                                                                | session-level AI override (backend/model/api\_key/base\_url) merged over env defaults — in-UI online/local LLM switching without env edits or restarts                                                                                                                                                                                                   |
| `/api/ai/test-connection`          | POST                                                                    | friendly connectivity probe of the effective backend: local (Ollama/LM Studio) → reachability + model list, **no API key needed**; online → key check. Probe URL is `{base_url}/models` (probing bare Ollama `/models` returns 404 — bug fixed 2026-08-30)                                                                                               |
| `/api/jobs`                        | list + `{job_id}` status                                                | job registry; live fill progress via `get_row_count` delta                                                                                                                                                                                                                                                                                               |

Connection kinds (UI): `sqlite` (local db file + file-picker modal), `postgresql` (field form → `postgresql://user:pass@host:port/db`), `url` (raw SQLAlchemy URL, reserved for future databases).

## WHERE TO LOOK

| Task                        | Location                                       | Notes                                                                                                                                                            |
| --------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Add an API endpoint         | `api.py`                                       | single-file router; follow the `_conn_or_404` + try/except pattern                                                                                               |
| Add a page                  | `static/js/pages/*.js` + `app.js` router table | export `render()` (+ optional `mount()`); hash `#/name`                                                                                                          |
| Change connection lifecycle | `state.py`                                     | one DataOrchestrator per conn; per-connection lock serializes fills                                                                                              |
| Add heal-lab capability     | `api.py` heal section                          | lazy-import sqlseed\_ai; degrade gracefully when missing                                                                                                         |
| Styling                     | `static/style.css`                             | Material 3 tokens in `:root` (`--md-*`: color roles, 8dp `--md-space-*`, `--md-shape-*`); semi-transparent layers via `color-mix()`; pill/table/panel primitives |

## CONVENTIONS

* **from** __future__ import annotations at every file top (ruff)

* **Never mock the DB layer** in tests — real SQLite via `tmp_path` fixtures

* **Job result race**: assign `job.result` BEFORE `job.status = "done"` (polling endpoint reads both; status-first creates an empty-result race — fixed once, keep it that way)

* **pluggy markers**: hook firstresult lives on `fn.sqlseed_spec` (project\_name + "\_spec"), not `_hookspec`

* **GenerationResult.count** is the inserted-row count (there is no `rows_inserted` attribute)

* **Frontend**: ES modules only, no bundler, no external CDN; all state in `api.js` `store` (connId survives page switches)

* **SQL console** accepts single SELECT statements only (guard in `run_query`)

## ANTI-PATTERNS

* **NEVER** use native `<select>` in pages — its option popup is rendered by the browser UI layer and mispositions (detached from the control) in embedded WebViews / IDE preview browsers; page CSS cannot fix it. Use `createDropdown()` from `dropdown.js` (page-DOM panel absolutely positioned 4px below the button; module-level instances survive page switches and are re-mounted by `render()`).

* **NEVER** rely on `input { min-width }` applying to checkboxes — the global rule is scoped to `input:not([type=checkbox]):not([type=radio])`; a 160px-wide checkbox once pushed its label text 147px away from the box.

* **NEVER** register this package under `[project.entry-points."sqlseed"]` — it is a standalone app, not a generation plugin

* **NEVER** import `sqlseed_ai` at module top in `api.py` — lazy import inside endpoints; the package must work without the AI plugin

* **NEVER** let the HTTP handler block on `fill_table` — always dispatch to a background thread job

* **NEVER** run two fills on the same connection concurrently — take `state.connection_lock(conn_id)` first

* **ALWAYS** validate table names via `validate_table_name()` + `quote_identifier()` before SQL interpolation

## COMMANDS

```bash
pip install -e "./plugins/sqlseed-web"          # + [ai] extra for the heal lab
sqlseed-web                                     # serve at http://127.0.0.1:8630
pytest plugins/sqlseed-web/tests/ -q            # 42 tests
ruff check plugins/sqlseed-web/ && mypy plugins/sqlseed-web/src/
```

## GOTCHAS

* **genform preview is debounced-auto**: any generator/param/NULL/unique change schedules `doPreview` after 400ms (`schedulePreview`) — previously the preview only refreshed on column select or the manual 刷新 button, so it kept showing stale values after edits (found live 2026-08-30). `previewBox` must be updated in `render()`; the scheduled callback checks `isConnected` before firing.

* **genform is a 7-segment 参考工具 panel**: 字段名+类型副标题 → 生成器下拉 → 参数区 → 预览+刷新 → 通用区(NULL%/唯一) → 重置属性. Segment order matters — 参考工具 puts 预览 **above** 通用区 and 重置属性 at the panel bottom, not next to 刷新. The panel is rebuilt by `render()`; only `paramsHolder` is re-cleared in place when the generator changes, so never relocate the params block by `querySelector('.genform-section')` (the old code did, and it broke as soon as a second section existed).

* **Common area is clipped per generator** (`NO_COMMON_GENS` / `NO_UNIQUE_GENS` / `NO_PREVIEW_GENS` in genform.js, per `generator_ui_reference.md` §1.3): 词表类(枚举/文本/图像或二进制) hides 设置唯一, 图像或二进制(`bytes`) also hides 预览. `NO_COMMON_GENS` is currently **empty** — 参考工具's 序列 maps to sqlseed's `skip` (autoincrement, generated by the DB, not offered in the dropdown), NOT to `template`; `template` can contain random fragments (`SKU-{random_string:4}-{sequence:03d}`), so NULL%/unique are meaningful for it. Clipping `template` once made those two invisible and unfixable. `buildCfg()` (shared by `emit()` and `doPreview()`) re-applies the same clipping when building the ColumnConfig — otherwise switching to a clipped generator silently keeps sending an invisible NULL%/unique.

* **NULL 百分比默认 5 且未勾选时禁用**: the checkbox writes `DEFAULT_PERCENT` (5) and `renderNull()` toggles `nullPctInput.disabled`. Pass real booleans to `h()` — `setAttribute('disabled', false)` still disables.

* **数据库硬约束在通用区锁定**（2026-08-31）: `/tables/{t}/schema` 额外返回 `unique_columns`（来自核心 `detect_unique_columns`，AUTOINCREMENT 主键被核心排除——由 `skip` 处理，不在其中）。genform 通过 `uniqueColumnsOf` 回调拿到它，配合 `colInfo.nullable`：NOT NULL 列的「包含 NULL 值」禁用（`buildCfg` 兜底不发送 `null_ratio`），数据库唯一列的「设置唯一」强制开且禁用（优先于 `NO_UNIQUE_GENS` 裁剪，`buildCfg` 兜底发送 `constraints.unique`）。控件旁显示「数据库约束:…」灰字提示。

* **自增主键列整面板锁定**（2026-08-31）: `isDbGenerated()`（显式 AUTOINCREMENT 主键）的列在 `render()` 早期返回——只显示「序列（自增）· 由数据库生成」与提示，不渲染生成器下拉、参数区、通用区。原因：核心 mapper L1a 对该类列优先级最高（强制 `skip`），任何用户配置都会被静默覆盖，可编辑控件纯属误导。命名注意：项目为 AGPL 开源，用户可见文案与代码注释**不得提及商业工具品牌**（含文档），统一用「参考工具/参考设计」指代 `docs/superpowers/plans/generator_*.md` 的出处截图。



* **Param control shape is an explicit set, not a name regex**: `NUMERIC_PARAMS` / `TEXTAREA_PARAMS` in genform.js. A `/min|max|length/` regex previously rendered `precision` and `start_year` as text boxes. Add new params to these sets (not to a regex) and to `PARAM_LABELS` in labels.js.

* **Alias params are collapsed to one control via `HIDDEN_PARAMS` + `normalizeAliasParams()`**: the core takes several spellings for the same thing — `pattern`/`regex` are pure aliases (`effective = pattern or regex`), and `weighted_choice` accepts both `choices` (`[{value, weight}]` object lists) and `weighted_choices` (`{value: weight}` dicts). Rendering both left two same-meaning boxes on the panel (the two-正则表达式 case), and the UI's "one per line" textarea submits `choices` as a **string** list, which used to crash the core with `TypeError: string indices must be integers`. The panel now hides the alias keys and moves any existing value to the primary key on load; the core additionally tolerates plain string lists as equal-weight `choices`. Old YAML keeps working.

* **Empty-params previews are intercepted, not fired**: `choice` and `weighted_choice` are the only generators that raise on empty params, so switching to them (params still blank, 400ms debounce fires) used to flash a "预览失败" error. `REQUIRED_PARAMS` + `missingRequired()` in genform.js short-circuits `doPreview` with a「待填写」hint instead.

* **Date/time trio panels** (`date` / `datetime` / `time`): controls are driven by `PARAM_ORDER` (start/end date first, year params demoted to the bottom), plus three linked behaviours — 一整天 checkbox gates the time inputs via `syncTimeInputs()`; 星期 is a three-way radio (全部/工作日/自定义) that reveals a 7-checkbox 周几 group only in 自定义 mode (`weekdayControl()`); and `weekdays` serialises as `"all"` / `"workdays"` / `[0…6]` (Mon=0), matching core `normalize_weekdays`. Core side lives in `generators/_datetime_utils.py` — all three providers share it, which is also why their datetime output no longer diverges (faker/mimesis used to leak microseconds).

* **AI backend dropdown ordering is two-layered** (heal page): `AI_BACKENDS` in api.py is the static baseline — **OpenAI 兼容 first** (most universal: vLLM / OpenRouter / self-hosted gateways all speak it, and it is `AIConfig`'s default backend), Google AI Studio next, local backends (Ollama / LM Studio) last. On top of that, `renderAiBody` promotes the **currently effective** backend (`ov.backend || eff.backend`) to slot one, since that is what the dropdown opens on. Changing `AI_BACKENDS` order alone is therefore not enough when an override is active — and vice versa.

* **A page reload wipes the wizard state — the connection does not**: `store` is module-level, but the server-side connection object survives, so `wizard.mount()` calls `api.js restoreConnection()` when `store.connId` is empty. It picks the `localStorage`-remembered connId (`sqlseed.connId`, written by `connect.doConnect`) and falls back to the primary connection (`group_index === 1`); `GET /api/connections/{id}/tables` (new endpoint, mirrors the POST response shape) supplies the table list that `loadTablesMeta` needs. On failure (server restarted, connections gone) the stale key is removed and the old "go connect first" message shows. `mount()` became async for this — fine, app.js fire-and-forgets it. The conn badge briefly reads 未连接 until the two fetches land.

* **Derived columns must survive the round-trip**: `derive_from` + `expression` is a `ColumnConfig` **mode mutually exclusive with `generator`**. Three places silently downgraded it to `string` — `applyAiYaml` (`cc.generator || 'string'`), `showColumnInPanel` (spec rebuilt from `generator`/`params` only), and `genform.fromInferred` — so an AI-authored derived column was rewritten as a random string, and if it participated in a cross-column CHECK the preview died on `str` vs `datetime`. genform now renders derived columns read-only (source + expression + live preview) and `buildCfg()` emits derived mode; `saveConfig` writes `derive_from:`/`expression:` instead of `generator:`.

* **Date bounds are backfilled when absent**: LLMs routinely emit `datetime` with **no params at all** (verified with gemma4:31b-cloud — every date column came back `{}` while float/choice/template got params). The panel would then look empty even though the core was silently using `start_year=2000`. `applyDateDefaults()` fills `2000-01-01` / `<current-year>-12-31` **only when no bound of any kind is set**, so a partial AI config is never overwritten. 参考工具's 日期 panel pre-fills its bounds too.

* **Dropdowns must be destroyed on re-render**: `createDropdown` attaches `scroll`/`mousedown`/`keydown` listeners to `document` and removes them only in `close()`. Since genform's `render()` rebuilds the whole panel, an open dropdown that gets discarded leaks those listeners — the stale `reposition()` then threw `Cannot read properties of null (reading 'getBoundingClientRect')` in the IDE WebView on every subsequent scroll. genform tracks its dropdowns via `track()` and calls `destroy()` at the top of `render()`; `reposition()` additionally self-unregisters when `el.isConnected` is false. Any new `createDropdown` call site in genform must go through `track()`.

* **Generator dropdown uses 参考工具's 7 classes** (通用/个人/支付/商业/位置/产品/电脑, `GEN_CATEGORIES` in labels.js). 支付 and 产品 have no sqlseed generators yet — `groupGenerators()` marks them `pending:true` and the dropdown renders them as disabled placeholders; they become selectable automatically once the P2 generators land, with no change here.

* **参考工具 parity spec**: `docs/superpowers/plans/generator_parity.md` records the per-generator config granularity from the reference screenshots (示例UI/生成数据类型/) and the P0/P1/P2 backlog — consult it before extending generator params. Per-screenshot UI baseline (layout, controls, defaults, options for all 44 generators) lives in `docs/superpowers/plans/generator_ui_reference.md` — check against it when verifying the property panel.

* **Same-target connections are legal but grouped**: multiple connections to one SQLite file work (read concurrency + serialized writes, verified by concurrent fill tests), and `list_connections()` tags them 主连接/并行 N so users don't lose track. Do not "deduplicate" connections silently — the isolation (per-connection provider/locale) is a feature.

* **Port 8630** is the default (uvicorn factory mode `sqlseed_web.app:create_app`).

* **Page-render timing**: `render()` runs BEFORE the page is mounted into the DOM — never use `document.getElementById` inside `render()` for elements the page itself creates. Pass the element reference instead (see `renderKind(body)` in connect.js; the getElementById variant once caused a blank file-input row on first load). Use the `mount()` hook for post-mount DOM lookups.

* **`out.append(arr)`** **renders** **`[object HTMLDivElement]`** — native `Element.append` does NOT spread arrays. When a render helper returns an array of nodes, always `out.append(...nodes)`. Found live in heal.js L2 violations rendering.

* **Boolean attrs in** **`h()`**: `setAttribute('disabled', false)` still disables the element (attribute presence wins). `h()` handles boolean values by add/remove attribute — pass real booleans (`disabled: atFirst`), never strings.

* **`ForeignKeyInfo`** **field names are singular** (`column` / `ref_table` / `ref_column`), not plural — the schema page FK table once rendered empty cells reading `fk.columns`.

* **File picker is server-side** (`/api/fs/browse`): browsers never expose absolute paths from `<input type="file">`; the local server lists directories instead. Default view hides non-DB files (toggle via `all_files=true`); hidden dotfiles always skipped.

* **Locale codes are faker-style** (`zh_CN`, `en_US`); `MimesisProvider.set_locale` maps them to mimesis short codes. Keep `SUPPORTED_LOCALES` in api.py in sync with that map — a test enforces the overlap.

* **Fill progress** is approximated by row-count delta polling (batches commit progressively); there is no in-fill callback hook.

* **`load_config`** **does NOT validate generator names** — unknown generators pass `/api/config/parse` and only fail at fill time (`UnknownGeneratorError`) or as heal violations. This is the core contract; tests document it.

* **YAML template endpoint** maps URL-prefixed targets to `url:` key, paths to `db_path:`.

* **vite/client 404** in browser console is from the browser environment, not this app (no Vite anywhere in the repo).

* **null\_ratio unit mismatch**: the genform UI collects 0–100 percent but core `ColumnConfig.null_ratio` is a 0–1 fraction (`le=1.0`). `emit()` divides by 100 before sending; `fromInferred()` multiplies by 100 when hydrating from core specs. Wizard `cfg` stores the backend shape (0–1). Sending the raw percent once made every preview/fill with NULL% fail with 422 (fixed 2026-08-30).

* **AI probe URL**: `/api/ai/test-connection` must probe `{base_url}/models` — Ollama's bare-host `/models` returns 404 (only `/api/tags` and `/v1/models` exist), which once made a healthy local server look dead.

* **AI readiness formula** (wizard `aiReadiness`): installed AND (local backend OR `effective.api_key_present`). Local backends always report `api_key_present: true` (placeholder key) — never gate them on the key. The wizard fetches `/api/ai/config` (session-override-aware), NOT `/api/meta/ai`, so in-UI backend switches take effect without reload.

* **AI backfill is replace + never write**: `applyAiYaml` replaces the whole `cfg` map (AI 生成了完整一版配置)，只回填当前连接真实存在的表/列；生成/预览仍走 Step 3 的 fill/preview（写库永远要用户点「开始生成」）。

* **Wizard tree state persists across step renders**: `treeSelection` (module-level Map) is passed as `initialSelection` to `createTree` — without it, re-entering Step 2 reset checkboxes to all-checked and silently discarded the AI/manual selection. `tree.setSelection` also feeds back into `treeSelection` via the `onChange` handler.

* **`pollJob`** **maxTries**: default 120×400ms=48s is enough for fill; the AI full-pipeline job can run minutes — pass a larger maxTries (wizard uses 900) or long LLM runs falsely report 超时 while the job still completes server-side.

