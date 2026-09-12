# SonarCloud 误报复核依据

本记录只包含独立复核确认的 31 个误报；服务端尚未登记。原先另外 4 个候选已有等价的源码改进，已撤回误报建议。公开 API `sqlseed.fill` 的 S107 参数数量告警由用户明确要求暂缓，保持 OPEN，不在此列表。

登记前必须核对 PR #10 最新分析 SHA、issue key、规则及源文件。下列两条 JavaScript 哈希问题在 `7fda56e` 复扫后换了 key，其他 key 不变。登记使用逐项英文依据，不能以批量无理由的方式关闭告警。

## AaCRco4dtyo-iTRYo9q_

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/unique_adjuster.py`
- 源码证据：src/sqlseed/core/unique_adjuster.py:171 _adjust_string; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaPQkcuVuZeQceA-

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/unique_adjuster.py`
- 源码证据：src/sqlseed/core/unique_adjuster.py:134 _bound_integer_fallback; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaPQkcuVuZeQceA_

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/unique_adjuster.py`
- 源码证据：src/sqlseed/core/unique_adjuster.py:164 _adjust_string; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaPQkcuVuZeQceBA

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/unique_adjuster.py`
- 源码证据：src/sqlseed/core/unique_adjuster.py:189 _adjust_string; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaPQkcuVuZeQceBB

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/unique_adjuster.py`
- 源码证据：src/sqlseed/core/unique_adjuster.py:301 _adjust_integer; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaqWkcuVuZeQceQ_

- 规则：`python:S8714`
- 文件：`tests/test_pg_fixture.py`
- 源码证据：tests/test_pg_fixture.py:50-62; conftest.py:269 pg_url returns external PG_TEST_URL before Docker handling.
- 复核文件 SHA-256：`4df8a938d459b71ce2ffd46219635e6a10b415e740d25fe774583197c8978447`

登记依据：

The test asserts that an explicitly supplied PostgreSQL service URL works without Docker. pytest.skip.Exception must be converted to pytest.fail: allowing it to propagate would mark this exact regression as skipped, not failed. pytest.raises would incorrectly require the skip to occur. This is a test-outcome boundary, not boilerplate checking that an ordinary exception is absent.

替代方案核对：Direct invocation can silently skip the regression. Monkeypatching pytest.skip into another exception or introducing a wrapper hides the same outcome conversion without improving this short test.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S8714.html)
- [依据 2](https://docs.pytest.org/en/stable/reference/reference.html#pytest-skip)

## AaCOzaQakcuVuZeQceBE

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

10.0.0.0/8 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaQakcuVuZeQceBF

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

172.16.0.0/12 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaQakcuVuZeQceBG

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

192.168.0.0/16 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaQakcuVuZeQceBH

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

10.0.0.0/24 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaQakcuVuZeQceBI

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

172.16.0.0/24 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaQakcuVuZeQceBJ

- 规则：`python:S1313`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:256-268 _TYPE_RULES CIDR choice; downstream mapping returns GeneratorSpec parameters for generated rows.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

192.168.1.0/24 is a generated PostgreSQL CIDR column sample in the type-to-generator mapping. It is inserted as synthetic row data; it is not a network endpoint, binding address or outbound request destination. The infrastructure-configurability risk of hard-coded IP addresses therefore does not apply.

替代方案核对：Replacing these private-network samples with configuration or different address ranges changes the generated data domain without removing any deployment coupling or security risk.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1313.html)

## AaCOzaONkcuVuZeQceAs

- 规则：`python:S1244`
- 文件：`src/sqlseed/core/relation.py`
- 源码证据：src/sqlseed/core/relation.py:549 _prepare_fk_upgrade tests null_ratio together with absence of _ref_values before fixing the conditional column.
- 复核文件 SHA-256：`eeaf5877c5f1cb1bb56991ce2bcc424199f686042057903abd60f86f1f270b9f`

登记依据：

null_ratio == 1.0 means every generated value is NULL. This value is an exact input/configuration sentinel, not the result of rounding-sensitive arithmetic. Approximate equality would incorrectly classify probabilities immediately below 1.0 as all-NULL and alter conditional foreign-key repair.

替代方案核对：isclose admits near-one ratios; >= broadens accepted invalid values and differs for NaN. Both change the exact all-NULL condition.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1244.html)
- [依据 2](https://docs.python.org/3/library/math.html#math.isclose)

## AaCOzaNQkcuVuZeQceAh

- 规则：`python:S1172`
- 文件：`src/sqlseed/generators/base_provider.py`
- 源码证据：base_provider.py:244-252; faker_provider.py:156 and mimesis_provider.py:116 expose the same mask keyword; generator dispatch forwards params as keywords.
- 复核文件 SHA-256：`09f5da33b618715fc9d7d695472d5a2f47474bb0e4afb01a0448d519cdea1a36`

登记依据：

BaseProvider._gen_phone intentionally accepts the mask keyword used by the shared generator dispatch and by the Faker/Mimesis overrides. The base provider supplies deterministic placeholder values and its existing docstring explicitly documents why mask is ignored. Removing or renaming this parameter breaks method(**params) calls. This also falls under the rule documentation exception for parameters already explained in the method docstring.

替代方案核对：Adding formatting behavior changes the base placeholder contract. **kwargs weakens the signature, and renaming mask to _mask breaks callers. No new comment or suppression is proposed.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1172.html)

## AaCOzaQakcuVuZeQceBK

- 规则：`python:S5886`
- 文件：`src/sqlseed/core/mapper.py`
- 源码证据：src/sqlseed/core/mapper.py:457 map_column; explicit GeneratorSpec input; replacement only updates selected fields.
- 复核文件 SHA-256：`a42e3f948df0377a15a46505425b502f27cdc948e86dcb39d1f8eb15163ecaf9`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a GeneratorSpec, so the result satisfies the annotated GeneratorSpec boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCOzaMbkcuVuZeQceAX

- 规则：`python:S1172`
- 文件：`src/sqlseed/database/_base_adapter.py`
- 源码证据：src/sqlseed/database/_base_adapter.py:104; database/_protocol.py:138; core/schema.py combines indexes and supplementary UNIQUE constraints.
- 复核文件 SHA-256：`26a7645d3981107367586e77909553151837e0b3109b8542bca3e4044bf96d0d`

登记依据：

get_unique_constraints(table_name) implements the shared DatabaseAdapter contract. Raw SQLite already reports UNIQUE constraints through PRAGMA index_list, so its supplementary constraint method intentionally returns an empty list for every table. Keeping the table_name keyword preserves structural substitutability and keyword callers; it is not a removable application parameter.

替代方案核对：Removing/renaming the keyword breaks the adapter contract. Re-querying SQLite merely to use the parameter adds unnecessary I/O; repeating UNIQUE metadata changes behavior.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1172.html)
- [依据 2](https://typing.python.org/en/latest/spec/protocol.html)

## AaCOzaPDkcuVuZeQceA8

- 规则：`python:S2245`
- 文件：`src/sqlseed/core/expression.py`
- 源码证据：src/sqlseed/core/expression.py:70-71 SAFE_FUNCTIONS; __init__ and _get_functions install local seeded RNG methods. tests/test_core/test_expression_seed.py verifies repeatability, isolation and unseeded compatibility.
- 复核文件 SHA-256：`a2abdc4e028dee0555f7a503b4f124ca3c65f1aee42ec9c05453bfa1832bd80a`

登记依据：

These random_int/random_float functions generate synthetic row expression values, not security-sensitive values. The flagged SAFE_FUNCTIONS entries intentionally provide the unseeded compatibility path; seeded ExpressionEngine instances override them with their own random.Random methods. Cryptographic randomness is unnecessary and would break the documented seeded replay behavior.

替代方案核对：secrets/SystemRandom is appropriate for security outputs, but these paths generate reproducible synthetic data only; changing generators introduces nondeterminism with no risk reduction.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S2245.html)
- [依据 2](https://docs.python.org/3/library/random.html)

## AaCOzaPDkcuVuZeQceA9

- 规则：`python:S2245`
- 文件：`src/sqlseed/core/expression.py`
- 源码证据：src/sqlseed/core/expression.py:70-71 SAFE_FUNCTIONS; __init__ and _get_functions install local seeded RNG methods. tests/test_core/test_expression_seed.py verifies repeatability, isolation and unseeded compatibility.
- 复核文件 SHA-256：`a2abdc4e028dee0555f7a503b4f124ca3c65f1aee42ec9c05453bfa1832bd80a`

登记依据：

These random_int/random_float functions generate synthetic row expression values, not security-sensitive values. The flagged SAFE_FUNCTIONS entries intentionally provide the unseeded compatibility path; seeded ExpressionEngine instances override them with their own random.Random methods. Cryptographic randomness is unnecessary and would break the documented seeded replay behavior.

替代方案核对：secrets/SystemRandom is appropriate for security outputs, but these paths generate reproducible synthetic data only; changing generators introduces nondeterminism with no risk reduction.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S2245.html)
- [依据 2](https://docs.python.org/3/library/random.html)

## AaCOzaMikcuVuZeQceAZ

- 规则：`python:S1172`
- 文件：`src/sqlseed/database/_bulk_optimizer.py`
- 源码证据：database/_bulk_optimizer.py:45 protocol,83 SQLite implementation,138 PostgreSQL implementation; database/_helpers.py:137 shared caller.
- 复核文件 SHA-256：`03721057070e4cd0ebc9e83ac9a6f977706fb0c27ca9ab30e2220f60ad3c2ae4`

登记依据：

PostgresBulkOptimizer.optimize(expected_rows) implements BulkWriteOptimizer. PostgreSQL session optimization is independent of the row count, while the SQLite implementation uses this same argument. Shared callers pass expected_rows by keyword, so removing or renaming it breaks the protocol. The unused value is an implementation-specific consequence of a valid common interface.

替代方案核对：Different per-dialect signatures complicate callers and violate substitutability; fabricated use of row count alters optimization policy without need.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S1172.html)
- [依据 2](https://typing.python.org/en/latest/spec/protocol.html)

## AaCVnmj7k0u9GTZlJlnx

- 规则：`python:S5655`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py`
- 源码证据：plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1039 _execute_replacement; explicit Connection input; replacement only updates selected fields.
- 复核文件 SHA-256：`b8c42f12d0addf9e1ebb1e7008f8d2fac1c4a6e6e853f60ac09a40a33833bfe7`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a Connection, so the result satisfies the annotated Connection boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5655.html)

## AaCOzajJkcuVuZeQceOJ

- 规则：`python:S6418`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/ai_settings.py`
- 源码证据：ai_settings.py:96 storage_info; _FIELDS only includes backend/model/base_url; tests/test_web_settings.py confirms keys are not persisted across restart or written to the settings file.
- 复核文件 SHA-256：`ff30307e6570bb149b672e4b0825391d490b5ddaf1762f73259be790b06686a0`

登记依据：

The api_key value here is the literal session_or_environment, a storage-policy description returned by storage_info. It is not an API credential and cannot authenticate any request. Actual credentials are resolved from the current environment/session and are excluded from persistent settings.

替代方案核对：Renaming a metadata field or moving its harmless label to an environment variable only disguises the scanner trigger and worsens the response contract.

官方依据：

- [依据 1](https://sonarcloud.io/api/rules/show?key=python%3AS6418&organization=sunbos)

## AaCOzai5kcuVuZeQceOF

- 规则：`python:S5886`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/state.py`
- 源码证据：plugins/sqlseed-web/src/sqlseed_web/state.py:280 job_snapshot; explicit Job input; replacement only updates selected fields.
- 复核文件 SHA-256：`581c597c9e4c9f5bd31df6347bc28c92e09020632fdf359deb39111bd7fbf9c7`

登记依据：

dataclasses.replace returns a new object of the same concrete dataclass type as its input. Here the input is a Job, so the result satisfies the annotated Job boundary. This is not a DataclassInstance value of a different runtime type. Keeping the standard replacement operation also preserves fields not explicitly changed. Strict mypy and an independent runtime type/field-preservation probe confirm the contract.

替代方案核对：Field-by-field reconstruction duplicates the dataclass schema and can drop future fields. A cast, wrapper, suppression or widened return annotation only conceals an analyzer inference limitation and provides no runtime improvement.

官方依据：

- [依据 1](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
- [依据 2](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S5886.html)

## AaCXPFuEyyKf7W-fda0h

- 规则：`javascript:S7767`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/static/js/pages/connect.js`
- 源码证据：connect.js:326-331; groupBadge at 319 consumes hash modulo six; independent real-source probe sqlite:/data/accounts.db gives 803751198 (palette 0), versus Math.trunc 2.3768048664034815e36 (palette 2).
- 复核文件 SHA-256：`3e85436e7cbe191c3f80519a200540318748f35b4a0a353f35041e03243f26b8`
- 原 key：`AaCOzagUkcuVuZeQceLR`

登记依据：

Intentional signed-32-bit overflow, not number truncation. hashStr folds UTF-16 code units using a 31-based polynomial; | 0 is the modulo-2^32 operation. Math.trunc neither preserves this overflow nor the existing connection-group palette. The rule targets accidental truncation idioms and is inapplicable to this hash algorithm.

官方依据：

- [依据 1](https://github.com/SonarSource/SonarJS/blob/master/packages/analysis/src/jsts/rules/README.md)
- [依据 2](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/prefer-math-trunc.md)

## AaCXPFuEyyKf7W-fda0i

- 规则：`javascript:S7758`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/static/js/pages/connect.js`
- 源码证据：connect.js:326-331 visits every index; groupBadge at 319. Real-source probe for emoji yields hash 1772899/palette 1, versus direct codePointAt replacement 4040704/palette 4.
- 复核文件 SHA-256：`3e85436e7cbe191c3f80519a200540318748f35b4a0a353f35041e03243f26b8`
- 原 key：`AaCOzagUkcuVuZeQceLS`

登记依据：

This function hashes all UTF-16 code units, including both halves of surrogate pairs; it does not interpret one code unit as a complete Unicode character. Unicode strings are accepted without data loss. A code-point hash is a different algorithm and changes existing group colors, so the rule's character-processing preference is not applicable. The upstream rule explicitly acknowledges that replacing charCodeAt in numeric hashes is not a safe rename.

官方依据：

- [依据 1](https://github.com/SonarSource/SonarJS/blob/master/packages/analysis/src/jsts/rules/README.md)
- [依据 2](https://github.com/sindresorhus/eslint-plugin-unicorn/blob/main/docs/rules/prefer-code-point.md)

## AaCRcpvgtyo-iTRYo9rG

- 规则：`githubactions:S8544`
- 文件：`.github/workflows/ci.yml`
- 源码证据：.github/workflows/ci.yml:64-80 builds five local distributions then installs local wheel paths; .github/actions/install-ci-deps/action.yml verifies bootstrap and CI dependency hashes first.
- 复核文件 SHA-256：`5eb38c354c21ed946b42e91af24f2c1c5ff99a17c1f8faa217b573e603c60402`

登记依据：

This step installs only dist/*.whl artifacts built from the checked-out project earlier in the same CI job, with --no-deps. Third-party dependencies were already installed from fully pinned --require-hashes manifests by install-ci-deps. No dependency resolution/download occurs in the flagged command, and wheel installation does not execute a source build backend. pip check then validates the installed graph. The dependency-integrity concern is already addressed at the actual external dependency boundary.

替代方案核对：Adding a version pin to dynamically named local project wheels or --require-hashes for artifacts produced in the same job does not pin an external dependency. --no-index is redundant for explicit local paths with --no-deps. No weaker install boundary is introduced.

官方依据：

- [依据 1](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-no-deps)
- [依据 2](https://pip.pypa.io/en/stable/topics/secure-installs/)

## AaCOzaqnkcuVuZeQceRE

- 规则：`plsql:S1192`
- 文件：`examples/scenario_lab/schema.sql`
- 源码证据：schema.sql:1-7,39,74,308; build.py:364-365 executes this exact SQL in sqlite3. Fixed default value is 2026-01-01 00:00:00.
- 复核文件 SHA-256：`2f4fd2a19401da343cc6e63a88cebc3f92d12577eda6f557d4f7210e7cd48825`

登记依据：

This file is standalone SQLite CREATE TABLE DDL executed verbatim through sqlite3.Connection.executescript, not Oracle PL/SQL. The repeated fixed timestamp is an intentional reproducible DEFAULT in four tables. SQLite DEFAULT expressions cannot reference variables, bound parameters, other columns/tables or subqueries; PL/SQL constant declarations are not valid SQLite. Introducing an external SQL preprocessor or application-defined function solely to deduplicate four defaults would add a runtime dependency and weaken the standalone fixture.

官方依据：

- [依据 1](https://sonarcloud.io/api/rules/show?key=plsql%3AS1192&organization=sunbos)
- [依据 2](https://www.sqlite.org/lang_createtable.html#the_default_clause)
- [依据 3](https://www.sqlite.org/lang_createtable.html#check_constraints)

## AaCOzaqnkcuVuZeQceRD

- 规则：`plsql:S1192`
- 文件：`examples/scenario_lab/schema.sql`
- 源码证据：schema.sql:109 order status,179 shipment status,192 shipment event type; build.py:364-365 executes SQLite DDL directly.
- 复核文件 SHA-256：`2f4fd2a19401da343cc6e63a88cebc3f92d12577eda6f557d4f7210e7cd48825`

登记依据：

The repeated delivered literal belongs to three independent SQLite CHECK domains: order state, shipment state and shipment event type. PL/SQL constants cannot be used in this SQLite DDL, and SQLite CHECK expressions cannot reference a lookup subquery. Replacing the CHECKs with a shared status foreign-key table would change domain constraints, dependency structure and the purpose of this fixture, rather than provide a local maintainability improvement.

官方依据：

- [依据 1](https://sonarcloud.io/api/rules/show?key=plsql%3AS1192&organization=sunbos)
- [依据 2](https://www.sqlite.org/lang_createtable.html#the_default_clause)
- [依据 3](https://www.sqlite.org/lang_createtable.html#check_constraints)

## AaCOzaqnkcuVuZeQceRC

- 规则：`plsql:S1192`
- 文件：`examples/scenario_lab/schema.sql`
- 源码证据：schema.sql:179 shipment DEFAULT and CHECK,192 shipment event type; build.py:364-365 uses sqlite3.executescript.
- 复核文件 SHA-256：`2f4fd2a19401da343cc6e63a88cebc3f92d12577eda6f557d4f7210e7cd48825`

登记依据：

The created literal appears as a shipment DEFAULT, in its CHECK domain, and in the separate shipment-event CHECK domain. Repetition between DEFAULT and its allowed domain is necessary to define both semantics explicitly in standalone SQLite DDL. SQLite has no applicable PL/SQL constant declaration; a lookup table cannot replace a DEFAULT and cannot be queried from CHECK. A preprocessor solely to remove this literal adds complexity without improving these independent domains.

官方依据：

- [依据 1](https://sonarcloud.io/api/rules/show?key=plsql%3AS1192&organization=sunbos)
- [依据 2](https://www.sqlite.org/lang_createtable.html#the_default_clause)
- [依据 3](https://www.sqlite.org/lang_createtable.html#check_constraints)

## AaCOzardkcuVuZeQceRV

- 规则：`python:S2245`
- 文件：`scripts/complex_validation/randomized_roundtrip.py`
- 源码证据：scripts/complex_validation/randomized_roundtrip.py:335 main takes/defaults a seed, creates random.Random(seed), then a per-round Random(r_seed) used by schema/data generation.
- 复核文件 SHA-256：`d100688480b6cc7af271606b407fb3d682469c3814c17f5197b9ea052bab4b89`

登记依据：

This seeded PRNG selects reproducible schema-validation rounds and generated fixture values. The script prints each round seed so a failure can be replayed. It is never used for credentials, tokens, cryptographic keys or authorization decisions; cryptographic randomness would destroy deterministic replay.

替代方案核对：secrets/SystemRandom is appropriate for security outputs, but these paths generate reproducible synthetic data only; changing generators introduces nondeterminism with no risk reduction.

官方依据：

- [依据 1](https://raw.githubusercontent.com/SonarSource/sonar-python/master/python-checks/src/main/resources/org/sonar/l10n/py/rules/python/S2245.html)
- [依据 2](https://docs.python.org/3/library/random.html)

## AaCOzaivkcuVuZeQceNs

- 规则：`css:S7924`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/static/style.css`
- 源码证据：style.css:1744-1746; pages/workbench.js:1113-1118 and 1837-1842 create native input elements with a boolean disabled property.
- 复核文件 SHA-256：`1ea78164106d5371e9de550fe001ebd1f5071070c4579d553ca36cf55cbfdd4a`

登记依据：

This declaration applies exclusively to .count-setting input:disabled, a native inactive input. Workbench creates an input with disabled set when its table is not selected. WCAG 2.2 SC 1.4.3 explicitly exempts inactive user-interface components, so the contrast finding is inapplicable; enabled input styling is separate.

官方依据：

- [依据 1](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html#inactive-user-interface-components)

## AaCOzaivkcuVuZeQceNt

- 规则：`css:S7924`
- 文件：`plugins/sqlseed-web/src/sqlseed_web/static/style.css`
- 源码证据：style.css:2419-2421; pages/workbench.js:1798-1802 uses button helper for graph-field; workbench/ui.js:109-135 creates native button.
- 复核文件 SHA-256：`1ea78164106d5371e9de550fe001ebd1f5071070c4579d553ca36cf55cbfdd4a`

登记依据：

This declaration applies exclusively to .graph-field:disabled. Actual graph-field controls are native buttons produced by workbench/ui.js; a CSS class or aria-disabled alone cannot activate this selector. Text is therefore inside an inactive control when this rule applies, which WCAG 2.2 SC 1.4.3 exempts from contrast requirements.

官方依据：

- [依据 1](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html#inactive-user-interface-components)
