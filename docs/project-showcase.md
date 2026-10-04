<a id="sqlseed"></a>

# Project walkthrough and technical presentation

<a id="_1"></a>

## A one-sentence introduction

sqlseed is a declarative database test-data tool for Python development and CI. It generates related data from database structures and rules, offers optional AI suggestions, and preserves offline execution and reproducible experiments.

The [scope and maintenance commitments](maintainable-release.md) define what to demonstrate. The project is not a general data-masking platform and does not claim automatic support for every database constraint or arbitrary business aggregate.

<a id="_2"></a>

## Start with the order example

First follow the [installation guide](guide.md#installation) to install local Core and activate your chosen Python environment. Run the following from the repository root; the output directory must not already exist:

```bash
python examples/order_workflow/run.py --output-dir /tmp/sqlseed-order-showcase
```

See the [order example README](https://github.com/sunbos/sqlseed/blob/main/examples/order_workflow/README.md) for detailed outputs and how to run it again. Open the actual generated report, rule files and database during the demonstration, rather than showing only successful screenshots.

A suggested presentation order:

1. **Problem:** users, products, orders and line items have dependencies. Values that look reasonable in isolation can still violate foreign-key or amount constraints.
2. **Rules:** show the fixed seed, date boundaries, parent-key references, field generation and derived relationships in YAML. Explain which values the database handles.
3. **Failure:** show the actual error from a bad rule and the actual number of records in the database afterward.
4. **Correction:** show the revised rules and real write results. Do not disable CHECK/FK constraints or alter the database structure to make validation pass.
5. **Replay:** generate into a new database with the same rules and compare logical data. Explain that provider versions and initial data are also reproduction conditions.
6. **Boundary:** queries can calculate order totals. Do not present those query results as an implemented general capability to generate cross-table aggregates.

This command demonstrates offline execution and does not call a real LLM. AI is an optional source of rule suggestions. When demonstrating AI, separately record the real analysis results, validation results and confirmed YAML. Regressions using fixed model responses do not replace real model-quality testing.

<a id="_3"></a>

## Architecture decisions to explain

| Decision | Problem it addresses | Cost and boundary |
| --- | --- | --- |
| Separate offline Python Core from entry-point plugins | Model or UI changes do not require rewriting data execution algorithms | Plugins must not reach into private engine internals or borrow CLI runtime code |
| Declarative rules | Keep test-data requirements under version control and replay them | Does not automatically cover every business state machine or cross-table aggregate |
| Combine deterministic processing with AI suggestions | Code checks explicit constraints; a model can supplement semantic requirements | Model output needs validation, and failure recovery needs a defined scope and budget |
| Batch writes | Bound per-batch buffering and report progress | Does not imply constant memory for the complete generation workflow or default multi-table atomicity |
| Explicitly reject unsupported relationships | Explain support boundaries before side effects | The supported scope is narrower, but its commitments can be verified |

<a id="_4"></a>

## A source-level failure example

The first column of a SQLite two-column composite parent key is not necessarily unique. Sampling that column first and then looking up the second column can lose valid parent-key combinations. The existing fix samples complete tuples and verifies the results with real database constraints.

Use `tests/test_core/test_composite_fk_pair_pool.py` to explain the input structure, the old algorithm's failure conditions and the actual reference combinations after the fix. Then explain why this version rejects uncoordinated relationships with three or more columns instead of sampling each column independently and hoping the insert succeeds.

Another useful example is failure in the second insertion batch. `tests/test_core/test_generation_partial.py` uses a real SQLite trigger to reject later batches and checks that the error result still reports the first batch's committed count. This illustrates the relationship between database transactions and application results.

<a id="_5"></a>

## Draft résumé descriptions

Use the following wording according to the design, implementation and verification work you actually performed. Be ready to explain how AI-assisted work was reviewed and verified. Do not add unmeasured throughput, savings, user counts or model success rates.

**For Python backend or test engineering:**

> Developed a declarative database test-data tool with an offline Python core for schema inference, foreign-key dependencies and batch generation. Provided CLI, Web and MCP entry points, and used real SQLite regressions to verify relational constraints, partial-commit results and data replay under fixed conditions.

**For AI application engineering:**

> Implemented optional AI rule suggestions and validation in a database test-data tool, separating model calls from offline execution. Consolidated non-interactive runtime services to reduce Web dependencies on private CLI implementations, and used deterministic regressions to verify candidate processing and failure paths.

When real model or performance experiments become available, add traceable measurements: dataset scope, model and version, run conditions, success criteria, duration and call cost. A passing unit-test count cannot be converted into a model success rate.

<a id="_6"></a>

## Preparing the explanation

Be able to explain: why plugins were chosen instead of microservices; why Core does not depend on model SDKs; when the database supplies IDs or defaults; how FK validity differs from business validity; which batches have committed after a failure; why a seed is not the only reproduction condition; and why unsupported features have been deferred.

A version with a clear scope and inspectable results is enough to start gathering feedback. Project improvements and job-search preparation can proceed in parallel.

<a id="_7"></a>

## Trade-offs in the current showcase version

Prioritize preparing the GitHub showcase and freeze new features. The four-table order example, real database constraints, offline replay, optional AI and Web component management already provide enough material for a technical walkthrough. Adding databases, models or UI features increases the acceptance scope. First make sure other developers can install the project, reproduce results, and understand failures and fixes; then iterate from feedback.

Two further engineering issues have concrete evidence worth discussing. A PostgreSQL bulk optimization previously disabled triggers/FK checks; after the fix, a 10,001-row case, triggers and orphan-record checks verify integrity. Web component maintenance uses process replacement to avoid modifying packages that are executing, and preserves explicit capability status during exceptions, uninstall and recovery. Distinguish same-origin and local-machine protections from multi-user authentication when explaining this work: the current Web app targets trusted local users.

Keep two or three résumé points that you can explain from the source. Commit counts, test counts and lines of code are process evidence, not substitutes for problem difficulty, design reasoning or real results. Fixed-response tests cannot establish model success rates. Provide accessible evidence for cross-platform CI, public releases and real model experiments separately before making those claims.
