<a id="_1"></a>

# Scope and maintenance commitments

This page describes the five-package workbench and support boundaries in 0.2.6. See the [migration guide](migration.md) for installing published releases, source checkouts and artifacts from the same build. The [release guide](releasing.md) and the corresponding release contain the publication and acceptance records.

This version prepares database test data for Python projects and CI: generate data from an existing schema and explicit rules, save those rules, and repeat experiments under the same conditions. The delivery target is a verifiable order workflow; support for every database feature and every AI backend is not a prerequisite.

<a id="_2"></a>

## Understanding the support scope

| Capability | Commitment in this version | Verification |
| --- | --- | --- |
| SQLite order workflow | Real generation, FK, UNIQUE, row-level CHECK and replay under fixed conditions for users, products, orders and order_items | `examples/order_workflow/README.md` and `tests/test_order_workflow.py` in the repository |
| SQLite single-column foreign keys | Sample actual parent records and account for dependencies in generation order | Core regressions against real SQLite and the order example |
| SQLite two-column composite foreign keys | Coordinate complete parent-key tuples; this does not imply support for arbitrary overlapping composite relationships or cross-table business rules | `tests/test_core/test_composite_fk_pair_pool.py` |
| Composite foreign keys with three or more columns | No automatic generation in this version; preflight explicitly rejects them | Boundary regressions verify rejection before clearing or writing data |
| PostgreSQL | Real PostgreSQL 16 verification of the adapter, URL API, FK, triggers and actual write counts; constraints remain enabled for large batches | `tests/integration/test_pg_*.py` and `test_url_e2e.py`; skips caused by an unavailable environment do not count as passes |
| PostgreSQL composite or cross-schema foreign keys | The current generator does not provide a complete guarantee and rejects unsupported relationships when detected | Reflection metadata contract tests do not replace acceptance against real PostgreSQL |
| PostgreSQL columns in one table that differ only in ASCII letter case | Current CHECK inference cannot distinguish them; generation and preview reject them before side effects | Sentinel records in real PostgreSQL verify this boundary; fields are not merged by guessing |
| AI suggestions | An optional plugin; suggestions, validation and execution after user confirmation remain separate | Fixed-response regressions verify local logic; real model availability and quality require separate testing |
| Cross-table SUM and complete order state machines | Not promised as general automatic generation capabilities | The order demonstration queries line-item totals rather than claiming automatic generation of order-header aggregates |

Being able to read a database structure does not mean the generator supports it. The 24-table `examples/scenario_lab/README.md` fixture exercises complex structures and boundaries. The four-table order example demonstrates complete generation. They serve different verification purposes.

<a id="write-semantics"></a>

<a id="_3"></a>

## Write and failure semantics

After calling Core, check both `GenerationResult.errors` and `count`, rather than only whether the function returned. `count` is the actual number of writes reported by execution; under normal per-batch commits, it counts committed batches. `batch_count` counts completed batches, not planned batches.

- **Preflight rejection:** unsupported structures produce an error before clearing or generating data. A configuration containing multiple tables checks every target first, so an earlier table is not changed before discovering that a later table is unsupported.
- **Failure during execution:** the failing batch rolls back; earlier committed batches can remain. The error result still reports the committed count.
- **Cooperative cancellation:** execution stops at engine checkpoints and preserves committed batches. This does not forcibly terminate an arbitrary Python function or remote request already running.
- **Process termination:** the caller may never receive the final result. Planned counts cannot establish the actual committed count; inspect the database again.
- **Multi-table Core configurations:** these are not one atomic transaction across the database. Passing support preflight does not guarantee that every subsequent business constraint, trigger or resource condition will succeed.

When the caller owns an outer transaction, a single-table Core result is not proof that the final transaction has committed. SQLite replacement runs in the supported Web workbench have their own transaction and rollback strategy; use the final status in the run record. This is not a default guarantee for every Core entry point.

<a id="_4"></a>

## Stable boundaries

| Source of change | Preferred place to change | Contract to preserve |
| --- | --- | --- |
| Models, SDKs and response protocols | Clients and protocol adapters in `sqlseed-ai` | Provider-specific model types stay outside Core; accepted configurations can run offline |
| Prompts, inference and repair strategies | Inside `sqlseed-ai` | Database constraints, explicit user rules and candidate validation results are not silently rewritten |
| Terminal, HTTP and MCP presentation | The corresponding entry-point plugin | Entry points translate errors and progress and call shared Python services |
| Database dialects | Database adapters; extend Core metadata when necessary | Preserve behavior for supported structures and compatibility with existing configurations |
| New business semantics | First check whether existing rules can express them | Do not hide cross-table execution logic in prompts or the UI |

The shared AI construction entry point is `sqlseed_ai.runtime`: `build_ai_config()`, `build_llm_client()` and `build_heal_orchestrator()`. It uses ordinary Python exceptions; terminal output and exit codes belong in the CLI. Web does not import private CLI factories. The entry point that creates a client releases it; ownership of injected clients must be explicit.

`ai-analyze` retains its existing default AutoHeal analysis flow. Workbench rule suggestions awaiting review and complete command-line analysis have different inputs and outputs. This version neither forces them into one large function nor introduces another replacement algorithm. New entry points should reuse the corresponding existing service. Run CLI and Web compatibility regressions when changing shared construction flows.

`tests/test_package_boundaries.py` checks static import direction: Core does not directly depend on entry-point plugins or model SDKs, Web/MCP do not depend on the AI CLI, and AI runtime does not depend on terminal entry points. This supplements import-linter; it does not claim to check every dynamic import at runtime.

<a id="_5"></a>

## Keeping maintenance manageable

1. Express new features through existing YAML and models first. Extend configuration and Core capabilities only when a real use case cannot be expressed. This version does not introduce a new business DSL.
2. Continue using Faker/Mimesis, SQLAlchemy and Pydantic for established foundational capabilities rather than duplicating their implementations.
3. Extract pure rule processing from AI orchestration as changes require it; do not launch a full rewrite merely to shorten files.
4. For every newly supported database structure, add both a successful real case and a boundary case that must be explicitly rejected.
5. Public Python parameters, configuration documentation and result semantics are compatibility contracts. Changelogs must explain breaking changes and migration. Internal algorithms can be corrected and evolved.
6. Evaluate new models against existing scenarios and result checks before enabling them. This version does not promise identical natural-language output or rule suggestions after switching models.

Deferred in this version: microservices, a general multi-agent platform, a complete orchestrator replacement, a general business DSL, large model leaderboards and statistical simulation of production data. Actual usage feedback will determine future investment.

<a id="reproduction-conditions"></a>

<a id="_6"></a>

## Reproduction conditions

Save the rules, schema, provider and dependency versions, seed, fixed time ranges and initial reference data. Replay into a new database. An identical seed does not prevent UNIQUE conflicts when appending repeatedly to an already populated database. Accepted AI output is a rule file; offline replay does not need another model request.

<a id="_7"></a>

## Completion criteria

- Run the order example from a new directory and obtain generated data, bad-rule diagnostics, a corrected configuration and a logical replay comparison.
- Unsupported relationships do not trigger clearing or partial writes first; committed counts match the real database.
- Shared AI construction does not depend on private CLI functions; existing analysis, error and progress regressions pass after changes.
- Installation and demonstration commands run successfully, with source checks and regression results recorded. Unverified external environments are explicitly listed.
- The [project walkthrough](project-showcase.md) describes actual functionality and evidence, without presenting future ideas as existing capabilities.

Once these criteria are met, freeze the new-feature scope for this version and move to actual use, demonstrations and feedback. Choose one improvement from that feedback for the next iteration.
