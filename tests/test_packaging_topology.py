from pathlib import Path

import pytest

from scripts.collect_packaging_topology import committed_inputs, git, local, select_windows


def frame(length):
    return [f"{index:040x}" for index in range(length)]


@pytest.mark.parametrize("length", [75, 76, 99, 101, 260])
def test_windows_have_exact_horizon_without_parent_child_or_child_child_overlap(length):
    rows = select_windows(frame(length))
    assert [row["parent_position"] for row in rows] == [0, (length - 25) // 2, length - 25]
    parents = {row["parent_commit"] for row in rows}
    children = [oid for row in rows for oid in row["child_commits"]]
    assert len(children) == len(set(children)) == 72
    assert not parents.intersection(children)
    assert rows[-1]["child_commits"][-1] == frame(length)[-1]
    assert all(len(row["child_commits"]) == 24 for row in rows)


@pytest.mark.parametrize("length", [0, 24, 73, 74])
def test_short_frame_stops_instead_of_replacing_horizon(length):
    with pytest.raises(ValueError, match="at least75"):
        select_windows(frame(length))


def test_duplicate_or_symbolic_commits_are_refused():
    for replacement in [frame(75)[1], "HEAD"]:
        candidate = frame(75)
        candidate[0] = replacement
        with pytest.raises(ValueError):
            select_windows(candidate)


def test_root_boundary_rejects_parent_and_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    for name in ["../other", str(tmp_path), "outside/other"]:
        with pytest.raises(ValueError, match="contained"):
            local(root, name)
    assert local(root, "inside/file.json") == root / "inside/file.json"
    assert isinstance(local(root, "inside/file.json"), Path)


def test_ignored_input_and_hidden_worktree_change_cannot_claim_committed_identity(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Authored fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / ".gitignore").write_text("ignored.json\n")
    (tmp_path / "tracked.json").write_text('{"version":1}\n')
    git(tmp_path, "add", ".gitignore", "tracked.json")
    git(tmp_path, "commit", "-qm", "fixed inputs")
    head = git(tmp_path, "rev-parse", "HEAD")
    committed_inputs(tmp_path, head, ["tracked.json"])
    (tmp_path / "ignored.json").write_text('{}\n')
    assert git(tmp_path, "status", "--porcelain", "--untracked-files=all") == ""
    with pytest.raises(ValueError, match="committed HEAD bytes"):
        committed_inputs(tmp_path, head, ["ignored.json"])
    git(tmp_path, "update-index", "--assume-unchanged", "tracked.json")
    (tmp_path / "tracked.json").write_text('{"version":2}\n')
    assert git(tmp_path, "status", "--porcelain") == ""
    with pytest.raises(ValueError, match="committed HEAD bytes"):
        committed_inputs(tmp_path, head, ["tracked.json"])
