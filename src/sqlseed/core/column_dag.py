from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlseed.core.mapper import GeneratorSpec


@dataclass
class ColumnConstraints:
    """列级约束"""
    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = 100


@dataclass
class ColumnNode:
    """DAG 中的一个节点，代表一个列"""
    name: str
    generator_spec: GeneratorSpec
    depends_on: list[str] = field(default_factory=list)   # 依赖的源列名
    expression: str | None = None                          # 派生表达式
    constraints: ColumnConstraints | None = None           # 约束条件
    is_derived: bool = False                               # 是否为派生列

    @property
    def is_skip(self) -> bool:
        return self.generator_spec.generator_name == "skip"


class ColumnDAG:
    """构建并管理列依赖图"""

    def build(
        self,
        specs: dict[str, GeneratorSpec],
        column_configs: list[Any] | None = None,
    ) -> list[ColumnNode]:
        nodes: dict[str, ColumnNode] = {}
        config_map: dict[str, Any] = {}

        if column_configs:
            for cc in column_configs:
                if hasattr(cc, "name"):
                    config_map[cc.name] = cc

        for col_name, spec in specs.items():
            cc = config_map.get(col_name)
            constraints = None
            expression = None
            depends_on = []
            is_derived = False

            if cc:
                if hasattr(cc, "constraints") and cc.constraints:
                    constraints = ColumnConstraints(
                        unique=cc.constraints.unique,
                        max_retries=cc.constraints.max_retries,
                    )
                if hasattr(cc, "derive_from") and cc.derive_from:
                    depends_on = [cc.derive_from]
                    expression = cc.expression
                    is_derived = True
                    # 派生列的 spec 设为特殊值
                    spec = GeneratorSpec(generator_name="__derive__")

            nodes[col_name] = ColumnNode(
                name=col_name,
                generator_spec=spec,
                depends_on=depends_on,
                expression=expression,
                constraints=constraints,
                is_derived=is_derived,
            )

        return self._topological_sort(nodes)

    def _topological_sort(self, nodes: dict[str, ColumnNode]) -> list[ColumnNode]:
        """Kahn 算法拓扑排序"""
        in_degree: dict[str, int] = {name: 0 for name in nodes}
        adjacency: dict[str, list[str]] = {name: [] for name in nodes}

        for name, node in nodes.items():
            for dep in node.depends_on:
                if dep in adjacency:
                    adjacency[dep].append(name)
                    in_degree[name] += 1

        queue = [name for name, deg in in_degree.items() if deg == 0]
        result: list[ColumnNode] = []

        while queue:
            current = queue.pop(0)
            result.append(nodes[current])
            for neighbor in adjacency.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            raise ValueError("Circular dependency detected in column definitions")

        return result
