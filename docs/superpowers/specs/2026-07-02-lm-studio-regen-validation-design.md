# LM Studio Data Regeneration & Validation Design

**Date:** 2026-07-02
**Status:** Approved (pending user review)
**Topic:** Clear `complex_biz.db` and `hr_biz.db`, regenerate data via LM Studio (local LLM only), validate integrity/business logic, output generalizable optimization plan.

## 1. Goal

Clear all table data in `complex_biz.db` (8 tables, e-commerce domain) and
`hr_biz.db` (4 tables, HR domain), then regenerate 100 rows/table using LM
Studio (`google/gemma-4-e2b`, 2B params) via the `sqlseed ai-analyze` +
`sqlseed fill --config` pipeline. The assistant does NOT intervene in the
LLM generation process — only validates the result and produces a
**generalizable** optimization plan (no domain-specific business logic in
core code).

## 2. Constraints

### 2.1 Non-intervention (assistant does not)
- Modify the YAML config produced by the LLM
- Adjust the LLM's prompts
- Manually INSERT data or hand-edit generated rows
- Selectively retry only "interesting" tables (run is end-to-end, untouched)

### 2.2 Core code purity (architectural)
- Optimizations targeting `src/sqlseed/` must be **type-correctness bug
  fixes** or **generic utilities** only — never business logic
- Domain-specific heuristics (e.g., "salary columns need a CHECK-aware
  generator") belong in the AI plugin layer (`plugins/sqlseed-ai/`) or in
  prompt/refiner rules — never in core

### 2.3 Optimization plan generality (key user requirement)
The optimization plan must be **pattern-based and schema-agnostic**. Every
recommendation must apply to *any* database with the same constraint shape,
not just these two specific schemas.

**Anti-pattern (forbidden):**
> "products.sale_price should derive_from cost_price"

**Acceptable pattern (required):**
> "Any column `X` in a same-table CHECK constraint `X >= Y` (where `Y` is a
> sibling column, not a literal) should be configured with
> `derive_from=[Y]` and an expression `value + random_int(0, K)` so the
> constraint is structurally guaranteed."

### 2.4 Local LLM only
- Backend: `LM_STUDIO` (`http://127.0.0.1:1234/v1`)
- Model: `google/gemma-4-e2b` (already running, confirmed via `/v1/models`)
- No cloud API calls (no Google AI Studio / OpenAI / OpenRouter)

## 3. Database Schema Context

### 3.1 `complex_biz.db` (8 tables, currently 1000 rows each)
- `categories`, `items`, `merchants`, `order_items`, `orders`, `products`,
  `sales`, `users`
- Constraint shapes present:
  - Cross-column CHECK: `sale_price >= cost_price`, `discount <= price_per_unit`, `end_date >= start_date` (n/a here)
  - Enum CHECK: `status IN (...)`, `role IN (...)`, `order_status IN (...)`
  - Range CHECK: `price > 0`, `stock_count >= 0`, `quantity > 0 AND quantity <= 5`
  - GENERATED column: `item_total = ROUND(quantity * (price_per_unit - discount), 2)`
  - UNIQUE: `merchant_code`, `sku`, `order_no`, `username`, `email`, etc.
  - FK with CASCADE: multi-level (merchants → products → order_items, etc.)

### 3.2 `hr_biz.db` (4 tables, departments=1000 rows, others=0)
- `departments`, `employees`, `projects`, `tasks`
- Constraint shapes present:
  - Cross-column CHECK: `end_date >= start_date`, `actual_hours <= est_hours`
  - Range CHECK: `age >= 18 AND age <= 80`, `salary >= 30000 AND salary <= 200000`, `budget >= 1000`
  - GENERATED column: `total_cost = ROUND(actual_hours * 50, 2)`
  - UNIQUE: `dept_code`, `employee_id`, `email`, `project_code`, `task_no`
  - DATE NOT NULL: `projects.start_date`, `projects.end_date`
  - FK: `employees.dept_id → departments.id`, `tasks.project_id → projects.id`, `tasks.assignee_id → employees.id`

## 4. Pipeline Design

### Stage 1: Clear table data (preserve schema)
- DELETE FROM each table in **FK-reverse-topological order** (children first)
- Reset `sqlite_sequence` so AUTOINCREMENT restarts from 1
- Preserve all schema objects (tables, indexes, triggers, CHECK constraints)

**Clear order:**
- `complex_biz.db`: `order_items` → `orders` → `sales` → `products` → `items` → `users` → `merchants` → `categories`
- `hr_biz.db`: `tasks` → `projects` → `employees` → `departments`

### Stage 2: Generate YAML config via LM Studio (non-intervention)
```bash
$env:SQLSEED_AI_BACKEND="lm_studio"
$env:SQLSEED_AI_API_KEY="lm-studio"   # placeholder, LM Studio doesn't validate
$env:SQLSEED_AI_ENABLED="1"
sqlseed ai-analyze --db complex_biz.db -o complex_biz_config.yaml
sqlseed ai-analyze --db hr_biz.db -o hr_biz_config.yaml
```
- `ai-analyze` internally invokes the `SchemaAnalyzer` + `AiConfigRefiner`
  self-correction loop (built-in, NOT assistant intervention)
- Output YAML is **not modified** by the assistant — used as-is for fill
- LLM call logs (prompts, responses, refine iterations) captured for
  root-cause analysis in Stage 5

### Stage 3: Generate data
```bash
sqlseed fill --config complex_biz_config.yaml
sqlseed fill --config hr_biz_config.yaml
```
- Per-table failures are logged, not fatal (continue with remaining tables)
- The YAML config controls row count per table; if missing, default 100

### Stage 4: Validation (assistant's only active role)
Run three validation passes:

**4.1 Row-count verification**
- Each table should have 100 rows (or the count specified in YAML)
- Record actual count per table

**4.2 Schema-driven business logic verification**
Reuse `_verify_business_logic.py` (already exists, accepts db_path arg):
```bash
python _verify_business_logic.py complex_biz.db
python _verify_business_logic.py hr_biz.db
```
Checks 5 categories:
1. **CHECK** constraints (parse DDL, test negation)
2. **FK integrity** (PRAGMA foreign_key_list + LEFT JOIN anti-pattern)
3. **UNIQUE** constraints (PRAGMA index_list + GROUP BY HAVING)
4. **GENERATED** columns (parse DDL formula, verify ABS(col - expr) ≈ 0)
5. **REALISM** heuristics (`*_name` readability, integer range, `*_email` format)

**4.3 Cross-column CHECK pattern detection (new, pattern-based)**
Specifically verify the cross-column CHECK shapes that are most likely to
fail when the LLM doesn't infer `derive_from`:
- Pattern A: `CHECK(col_x >= col_y)` — does `col_x` use `derive_from=[col_y]`?
- Pattern B: `CHECK(col_x <= col_y)` — does `col_x` use `derive_from=[col_y]`?
- Pattern C: `CHECK(col_x IN (literal_list))` — does `col_x` use `choice` or `weighted_choice`?
- Pattern D: `CHECK(col_x >= literal AND col_x <= literal)` — does `col_x` have `min_value`/`max_value` in params?

### Stage 5: Optimization plan (generalizable, pattern-based)
For each failure mode observed in Stage 4, produce a recommendation
classified by layer:

| Layer | What goes here | Example pattern |
|-------|----------------|-----------------|
| **Core (`src/sqlseed/`)** | Type-correctness bugs, generic utilities only. **NEVER** business logic. | `_gen_date` returning `datetime.date` instead of string (already done 2026-07-02) |
| **AI plugin (`plugins/sqlseed-ai/`)** | Prompt rules, refiner Fix rules, mediator heuristics | "Cross-column CHECK `X >= Y` triggers `derive_from=[Y]` for `X`" |
| **Config/template layer** | YAML param defaults, generator selection hints | "Range CHECK on integer → set `max_value` to upper bound" |

**Every recommendation must be phrased as a schema-agnostic pattern**, e.g.:
> "Pattern: any same-table CHECK constraint `col_x >= col_y` (sibling
> column reference, not literal) should cause the LLM/refiner to emit
> `derive_from=[col_y]` with expression `value + random_int(0, K)` for
> `col_x`. This structurally guarantees the constraint. Failure mode:
> without this, the LLM generates independent random values for `col_x`
> and `col_y`, violating the CHECK ~50% of the time."

## 5. Deliverables

| Artifact | Purpose | Layer |
|----------|---------|-------|
| `complex_biz_config.yaml` | LLM-generated config (unmodified) | Generated |
| `hr_biz_config.yaml` | LLM-generated config (unmodified) | Generated |
| `_e2e_generation_report.md` | Row counts + verify_business_logic output per DB | Report |
| `_optimization_plan.md` | Pattern-based recommendations, classified by layer | Plan |
| (Optional) LLM call logs | Captured prompts/responses for root-cause analysis | Diagnostic |

## 6. Acceptance Criteria

1. Both DBs cleared (0 rows in all tables) before regeneration
2. Both YAML configs generated by LM Studio without assistant modification
3. `sqlseed fill --config` runs to completion (per-table failures logged)
4. Validation report covers: row counts, 5 verify categories, 4 cross-column CHECK patterns
5. Optimization plan contains **only** schema-agnostic pattern recommendations
6. No recommendation puts business logic in `src/sqlseed/`

## 7. Out of Scope

- Modifying the LLM (no fine-tuning, no prompt editing during this run)
- Modifying core code during this run (optimization plan only proposes)
- Testing on PostgreSQL (SQLite only for this validation)
- Performance benchmarking (correctness only, not throughput)
- Fixing the 1 known flaky LLM integration test
  (`test_generate_and_refine_streaming_invokes_no_state_mutation`)

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LM Studio gemma-4-e2b (2B) may produce incomplete YAML | Refiner self-correction loop runs automatically; if still fails, record in report |
| Cross-column CHECK failures (expected ~50% without derive_from) | Document as failure mode → optimization pattern, do NOT patch during run |
| Long generation time (100 rows × 12 tables × 2B model) | Run sequentially, log progress, allow up to 30 min total |
| DB file locks from prior sessions | Use fresh DELETE (not file unlink) to clear data |

## 9. Next Steps After Design Approval

1. Write implementation plan via `writing-plans` skill
2. Execute plan: clear → generate → validate → report
3. Review optimization plan with user before any code changes
