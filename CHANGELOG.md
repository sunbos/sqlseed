# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Core `DataOrchestrator` engine with streaming batch generation
- `ColumnMapper` with 8-level strategy chain (exact → pattern → type → default)
- `DatabaseAdapter` Protocol with `SQLiteUtilsAdapter` and `RawSQLiteAdapter`
- `PragmaOptimizer` with 3-tier optimization (LIGHT / MODERATE / AGGRESSIVE)
- `DataProvider` Protocol with `BaseProvider`, `FakerProvider`, `MimesisProvider`
- `DataStream` streaming generator for memory-efficient batch processing
- `RelationResolver` with topological sorting for foreign key dependencies
- Plugin system based on `pluggy` with 9 hook points
- CLI commands: `fill`, `preview`, `inspect`, `init`, `replay`
- Python API: `sqlseed.fill()`, `sqlseed.connect()`, `sqlseed.fill_from_config()`, `sqlseed.preview()`
- YAML/JSON configuration file support
- Configuration snapshot save and replay
- `sqlseed-ai` plugin skeleton (Phase 4)
- Comprehensive test suite (286 tests, 97% coverage)
- CI/CD with GitHub Actions
- SQL injection prevention via `quote_identifier()` utility

### Fixed
- Hook `firstresult` semantics aligned with design document for `transform_row` and `transform_batch`
- `validate_table_name` now includes regex validation with proper warnings
- Removed redundant seed double-setting in orchestrator
- Extracted duplicated `_is_autoincrement` logic into shared `schema_helpers` utility
- Added `fill()` alias to `DataOrchestrator` for design-doc API compatibility
