<a id="web"></a>

# Maintaining the bilingual Web UI

This page defines the Simplified Chinese and English interface scope, message boundaries and verification approach for the 0.2.6 workbench. For user instructions, see the [workbench guide](../web-workbench.md). This is a maintenance checklist, not a claim that all browser, CI or installed-distribution acceptance checks have passed.

<a id="_1"></a>

## Scope and terminology

| Chinese | English | Scope |
| --- | --- | --- |
| 工作台 | Workbench | Table selection, rules, dependency checks, preview, AI review and write confirmation |
| 配置管理 | Configurations | Save, open, search, duplicate, rename, import, export and delete |
| 运行记录 | Runs | Per-table results, committed counts, fixed configuration snapshots and recovery guidance |
| 设置 | Settings | AI services, configuration defaults, component management and appearance |
| 数据生成引擎 | Data generation engine | Configuration selection for Base, Faker and Mimesis |
| 数据语言与地区 | Data language and region | Generation locale, independent of UI language |

Coverage includes these supported pages and the connection, directory selection, dropdown, calendar, rule editor, relationship graph, preview and current-data windows they open. Headings, help, buttons, loading/empty/error states, placeholders, titles and ARIA names are all interface copy. Historical `connect/wizard/browse/heal/meta` pages are outside the supported router; do not expand the scope by reactivating them.

Keep table and column names, user configuration names, model IDs, product names, URLs/paths, SQL/YAML/JSON, generator identifiers and original database values unchanged. Number and date formatting is only for displaying metadata. Do not reparse database timestamps in ways that change precision or time zones. When third-party diagnostics or historical records lack message descriptors, preserve the safe original text and explain its meaning in the current language. Do not guess translations or recursively translate user data.

<a id="_2"></a>

## Preferences and lifecycle

The top bar is the shared language entry point. `js/i18n.js` supports `zh-CN/en` and stores an explicit choice in `sqlseed.ui.language`. Without a valid saved choice, it uses the first supported language in browser preferences, defaulting to English when none match. Same-origin tabs synchronize through the `storage` event; unavailable storage limits the change to the current page. The page `lang` and browser title update with the language.

Switching language updates only explicitly bound presentation slots. It must not call the router, remount forms, submit inputs, resample data or trigger database, AI or component-management requests. Preserve original DOM controls, input values and selections, focus, scroll position, expanded disclosure sections, unapplied rules and request state. Do not store UI language in generation documents or change the data locale with it.

<a id="_3"></a>

## Frontend messages

- Dictionaries live in `static/js/i18n/messages/*.json`, each with the structure `{namespace: {key: entry}}`. The matching JS modules only load and register them through the shared `loadMessages(url)`. Keep explicit side-effect imports for those modules, and use a dictionary only after its module has loaded. Keys have stable semantic names; entries are `[Chinese, English]`, interpolation uses `{namedParameter}`, and counts can use `one/other` forms.
- Maintain translation data separately from executable logic. The loader validates the full resource before calling `registerMessages(namespace, entries)` and reuses loaded results by URL. Language switching does not reload resources. Keep native ES modules, existing top-level await and local static fetches; do not introduce a bundler or online translation service.
- `tr()` returns a lazily formatted presentation value. `h()`, shared buttons and dropdowns accept that value; direct DOM updates use `setText()` / `setAttr()`. Use `appendContent()` / `replaceContent()` when passing translation values to native append or replaceChildren operations.
- Compose copy with `joinText()` or formatting-only `liveText()`. Template strings, ordinary array `.join()`, `String()` and `valueText()` resolve values immediately, so they cannot store copy that needs to update when the language changes.
- `t()` returns the current string. Use it only when a fixed value is intended, such as a default name offered when the user begins copying a configuration. Later language changes must not overwrite user names or submitted values.
- `formatNumber()` / `formatDate()` format displayed metadata. Keep the original numeric `count` for plural selection and pass a formatted display value as a separate parameter; grouping commas must not affect plural selection. Machine-readable input values, sort keys, counts and timestamps sent to APIs must not become locale-formatted strings.
- Recoverable UI errors use `UserFacingError(tr(...))` to retain `localizedMessage`; catch handlers display them with `errorText()`. For native or third-party errors, wrap safe original text in a diagnostic explanation in the current language. Do not handle an error as if it were a user-provided name.

For example, page state should retain bindings instead of issuing new requests when the language changes:

```javascript
setText(status, tr('runs.identity', {revision: run.revision, id: run.id}));
setAttr(action, 'aria-label', tr('configurations.recordActions', {name: record.name}));
```

<a id="_4"></a>

## Backend contracts and packaging

`sqlseed_web.messages` marks only explicitly created messages; it does not match existing strings to translations. Preserve original API text and add `<field>_key` / `<field>_params`. Arrays retain their original values and add index-aligned `<field>_i18n` entries containing a descriptor object or `null`. Preserve these descriptors across HTTP, event streams, managed-process communication and run-record boundaries without changing status codes, business identifiers, error codes or configuration structures. Parameters must still be sanitized and must not contain secrets.

On the frontend, call `serverText(record, field)` or `serverMessages(record, field)` only for known presentation fields. Do not walk an entire response to translate arbitrary strings. Nested messages also need explicit descriptors; missing or unrecognized diagnostics fall back to safe original text.

The shared backend dictionary is `static/i18n/backend-messages.json`. The app reads this static resource once on initial load, without requesting it again when the language changes. Frontend and backend JSON dictionaries and JS registration modules ship in the Python wheel; they do not depend on a CDN, runtime translation service or npm build. Resource-loading failures must not change business-operation results. Installed-package acceptance must check resource presence, readability through static routes and successful module dependency loading.

<a id="_5"></a>

## Change-verification checklist

| Area | Required behavior to check |
| --- | --- |
| Dictionaries | Matching Chinese/English keys, named parameters and plural forms; no missing or frozen copy in supported views |
| Preferences | Browser-language fallback, rejected/corrupt storage, same-origin storage synchronization and independent generation locale |
| Pages and overlays | Language switching updates body text, title, placeholder and ARIA content while preserving controls, unsaved values and focus |
| Task safety | Language changes do not alter request counts, cancellation/late-result guards, selected configuration items, execution plans or actual database data |
| Diagnostics | Known descriptors are bilingual; unknown original text is preserved with an explanation; sensitive parameters are not echoed |
| Readability | Both languages, light/dark themes, long labels on narrow screens, keyboard interaction, and relationship-graph/table overflow |
| Package resources | JS/JSON in the wheel, native ES-module links and static resources read from the installed package |

Node tests use real `loadFrontend/loadI18n` and real message dictionaries. Existing behavior tests explicitly set Chinese; new bilingual tests actively switch language. An identity `t()` stub cannot prove bindings work. Page-specific tests and `test_i18n.cjs` verify state and requests. `test_i18n_catalog.cjs` enumerates actual registered resources and checks languages, parameters, plural forms, backend descriptors and dynamic navigation/weekday/theme keys. Python message/API regressions verify the additive contract and isolation of raw data. Node's minimal DOM does not prove real browser layout. Record browser, wheel and CI results separately, and accurately list checks that were not run.

Run the existing gates from the repository root; internationalization does not require new build tools:

```bash
node --test plugins/sqlseed-web/tests/test_*.cjs
pytest plugins/sqlseed-web/tests/
python scripts/sync_docs.py --check
python -m mkdocs build --strict
```

<a id="_6"></a>

## Where acceptance results are recorded

Implementation, browser and installed-package evidence, and remote checks for this feature are recorded in [PR #20](https://github.com/sunbos/sqlseed/pull/20). Verification must match the commit SHA. Earlier candidate packages and test counts do not establish the status of later changes, and automation or API tests cannot substitute for browser acceptance that has not been completed.

Acceptance records should list automated tests, real-browser checks, installed-package checks, code review and remote gates separately, retaining failure and rerun history. For example, a real LLM check that fails and is later skipped because the service is unavailable must not be recorded as passed. An expected skip of PR documentation deployment also does not mean the documentation build was unchecked: verify both the strict build in lint and the separate documentation synchronization check.
