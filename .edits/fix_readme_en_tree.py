"""Fix README.md architecture tree: stream.py lives in core/ (not generators/), add enrichment.py."""
from pathlib import Path

p = Path("/tmp/wt-contract/README.md")
text = p.read_text(encoding="utf-8")
orig = text

text = text.replace(
    """│   ├── constraints.py       # ConstraintSolver — unique backtracking
│   ├── transform.py         # TransformLoader — dynamic user script loading
│   └── result.py            # GenerationResult dataclass
├── generators/              # ===== Generator Layer =====
│   ├── _protocol.py         # DataProvider Protocol + UnknownGeneratorError
│   ├── registry.py          # ProviderRegistry (entry-point auto-discovery)
│   ├── base_provider.py     # Built-in base generators (zero dependencies)
│   ├── faker_provider.py    # Faker adapter
│   ├── mimesis_provider.py  # Mimesis adapter
│   └── stream.py            # DataStream streaming + constraint backtracking""",
    """│   ├── constraints.py       # ConstraintSolver — unique backtracking
│   ├── enrichment.py        # EnrichmentEngine — infer distribution from existing data
│   ├── stream.py            # DataStream — streaming generation + constraint backtracking
│   ├── transform.py         # TransformLoader — dynamic user script loading
│   └── result.py            # GenerationResult dataclass
├── generators/              # ===== Generator Layer =====
│   ├── _protocol.py         # DataProvider Protocol + UnknownGeneratorError
│   ├── registry.py          # ProviderRegistry (entry-point auto-discovery)
│   ├── base_provider.py     # Built-in base generators (zero dependencies)
│   ├── faker_provider.py    # Faker adapter
│   └── mimesis_provider.py  # Mimesis adapter""",
)

if text == orig:
    raise SystemExit("NO CHANGES MADE — check patterns")
p.write_text(text, encoding="utf-8")
print("README.md tree updated")
