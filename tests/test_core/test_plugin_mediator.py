from __future__ import annotations

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.plugin_mediator import PluginMediator


class TestPluginMediator:
    def test_ai_applicable_generators(self) -> None:
        assert "string" in PluginMediator.AI_APPLICABLE_GENERATORS
        assert "integer" not in PluginMediator.AI_APPLICABLE_GENERATORS
        assert "email" not in PluginMediator.AI_APPLICABLE_GENERATORS

    def test_apply_ai_suggestions_no_unmatched(self, mediator_ctx) -> None:
        specs = {"name": GeneratorSpec(generator_name="email")}
        result = mediator_ctx.mediator.apply_ai_suggestions("t", mediator_ctx.schema.get_column_info("t"), specs)
        assert result["name"].generator_name == "email"

    def test_apply_batch_transforms_no_hooks(self, mediator_ctx) -> None:
        batch = [{"name": "alice"}, {"name": "bob"}]
        result = mediator_ctx.mediator.apply_batch_transforms("t", batch)
        assert result == batch

    def test_apply_template_pool_no_hooks(self, mediator_ctx) -> None:
        specs = {"name": GeneratorSpec(generator_name="string")}
        result = mediator_ctx.mediator.apply_template_pool("t", mediator_ctx.schema.get_column_info("t"), specs, 10)
        assert result["name"].generator_name == "string"
