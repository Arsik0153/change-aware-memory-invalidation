import shutil

import pytest

from integrations.opencode.task_replay import inventory
from scripts.practical.analyze_new_study import canonical_inventory


def test_inventory_matches_actual_materialized_input(tmp_path):
    base = tmp_path / "base"
    (base / "tests/certs/expired/ca").mkdir(parents=True)
    (base / "tests/certs/expired/ca/cert.txt").write_text("authored fixture")
    (base / "tests/certs/valid").mkdir()
    (base / "tests/certs/valid/ca").symlink_to("../expired/ca", target_is_directory=True)
    workspace = tmp_path / "workspace"
    shutil.copytree(base, workspace)
    with pytest.raises(ValueError, match="nonregular"):
        inventory(base)
    assert canonical_inventory(base) == inventory(workspace)


def test_external_fixture_links_are_rejected(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (base / "external").symlink_to(outside)
    with pytest.raises(ValueError, match="external link"):
        canonical_inventory(base)
