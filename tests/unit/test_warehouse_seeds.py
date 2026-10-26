"""The dbt seed CSVs are exactly what the contracts render to (no hand edits, no drift)."""

import importlib.util

from druksmart_common.config import REPO_ROOT

SCRIPT = REPO_ROOT / "warehouse" / "scripts" / "generate_seeds.py"


def _generator():
    spec = importlib.util.spec_from_file_location("generate_seeds", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_csvs_match_the_contracts():
    rendered = _generator().render()
    seeds_dir = REPO_ROOT / "warehouse" / "seeds"
    on_disk = {p.name for p in seeds_dir.glob("*.csv")}
    assert on_disk == set(rendered), "run python warehouse/scripts/generate_seeds.py"
    for name, text in rendered.items():
        assert (seeds_dir / name).read_text("utf-8") == text, (
            f"{name} is stale; regenerate the seeds"
        )


def test_every_mapping_target_is_a_canonical_value():
    rendered = _generator().render()
    approvals = {
        line.split(",")[-1] for line in rendered["map_leave_approval_status.csv"].splitlines()[1:]
    }
    assert approvals <= {"pending", "approved", "rejected", "cancelled"}
    states = {line.split(",")[-1] for line in rendered["map_document_state.csv"].splitlines()[1:]}
    assert states == {"draft", "posted", "cancelled"}
