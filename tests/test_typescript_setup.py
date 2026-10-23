import subprocess

import pytest

from cami.cli import main
from cami.typescript_runtime import (
    TypeScriptSetupError,
    compiler_path,
    runtime_directory,
    setup_typescript,
)


def test_setup_is_idempotent_and_does_not_use_target_manifest(tmp_path, monkeypatch):
    import cami.typescript_runtime as runtime

    target = tmp_path / "target"
    target.mkdir()
    marker = target / "executed"
    (target / "package.json").write_text('{"scripts":{"install":"touch executed"}}')
    monkeypatch.chdir(target)
    monkeypatch.setenv("NODE_OPTIONS", "--require=/missing/injected.js")
    monkeypatch.setenv("NODE_PATH", str(target / "node_modules"))
    original = runtime._command
    commands = []

    def command(args, cwd):
        commands.append(args)
        return original(args, cwd)

    monkeypatch.setattr(runtime, "_command", command)
    before = compiler_path().read_bytes()
    assert setup_typescript() == runtime_directory()
    assert all("ci" not in args for args in commands)
    assert compiler_path().read_bytes() == before
    assert not marker.exists() and not (target / "node_modules").exists()


def test_failed_new_setup_preserves_published_compiler_and_removes_pending(tmp_path, monkeypatch):
    import cami.typescript_runtime as runtime

    published = compiler_path()
    before = published.read_bytes()
    new = tmp_path / "new-runtime"
    monkeypatch.setattr(runtime, "runtime_directory", lambda: new)
    original = runtime._command

    def command(args, cwd):
        if "ci" in args:
            assert args == ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
            assert (cwd / "package-lock.json").read_bytes() == (runtime.sidecar_directory() / "package-lock.json").read_bytes()
            raise TypeScriptSetupError("simulated offline registry")
        return original(args, cwd)

    monkeypatch.setattr(runtime, "_command", command)
    with pytest.raises(TypeScriptSetupError, match="offline registry"):
        setup_typescript()
    assert not new.exists() and not list(tmp_path.glob(".pending-*"))
    assert published.read_bytes() == before


def test_setup_missing_node_and_wrong_versions_are_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert main(["setup-typescript"]) == 3
    assert "node" in capsys.readouterr().err
    monkeypatch.setattr("cami.typescript_runtime._command", lambda args, cwd: "v22.1.0")
    assert main(["setup-typescript"]) == 3
    assert "Node.js 24 and npm 11" in capsys.readouterr().err


def test_setup_nonzero_npm_is_nonzero_cli(tmp_path, monkeypatch, capsys):
    import cami.typescript_runtime as runtime

    monkeypatch.setattr(runtime, "runtime_directory", lambda: tmp_path / "not-published")
    original = runtime.subprocess.run

    def run(args, **kwargs):
        if "ci" in args:
            return subprocess.CompletedProcess(args, 1, "", "offline failure")
        return original(args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert main(["setup-typescript"]) == 3
    assert "offline failure" in capsys.readouterr().err
    assert not (tmp_path / "not-published").exists()


@pytest.mark.parametrize("damage", ["missing", "syntax", "incomplete", "manifest", "ready"])
def test_setup_repairs_owned_invalid_cache(tmp_path, monkeypatch, damage):
    import json
    import shutil
    import cami.typescript_runtime as runtime

    healthy = runtime.runtime_directory()
    destination = tmp_path / "runtime"
    shutil.copytree(healthy, destination)
    compiler = destination / "node_modules/typescript/lib/typescript.js"
    if damage == "missing":
        compiler.unlink()
    elif damage == "syntax":
        compiler.write_text("this is invalid JavaScript !!!")
    elif damage == "incomplete":
        shutil.rmtree(destination / "node_modules")
    elif damage == "manifest":
        (destination / "package.json").write_text('{}')
    else:
        (destination / "ready.json").write_text('{}')
    monkeypatch.setattr(runtime, "runtime_directory", lambda: destination)
    assert setup_typescript() == destination
    assert compiler.read_bytes() == (healthy / "node_modules/typescript/lib/typescript.js").read_bytes()
    assert json.loads((destination / "ready.json").read_text())["manifest"] == runtime.manifest_fingerprint()
    quarantined, = list(tmp_path.glob(".invalid-*"))
    assert quarantined.is_dir()
    assert setup_typescript() == destination
    assert len(list(tmp_path.glob(".invalid-*"))) == 1
    assert not list(tmp_path.glob(".pending-*"))


def test_failed_repair_preserves_invalid_cache_for_retry(tmp_path, monkeypatch):
    import shutil
    import cami.typescript_runtime as runtime

    destination = tmp_path / "runtime"
    shutil.copytree(runtime.runtime_directory(), destination)
    (destination / "node_modules/typescript/lib/typescript.js").write_text("broken compiler")
    before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    monkeypatch.setattr(runtime, "runtime_directory", lambda: destination)
    original = runtime._command

    def command(args, cwd):
        if "ci" in args:
            raise TypeScriptSetupError("simulated offline repair")
        return original(args, cwd)

    monkeypatch.setattr(runtime, "_command", command)
    with pytest.raises(TypeScriptSetupError, match="offline repair"):
        setup_typescript()
    assert before == {p.relative_to(destination): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    assert not list(tmp_path.glob(".invalid-*")) and not list(tmp_path.glob(".pending-*"))
    monkeypatch.setattr(runtime, "_command", original)
    assert setup_typescript() == destination


def test_cache_ancestor_symlink_is_not_a_trusted_compiler(tmp_path):
    from cami.typescript_runtime import trusted_compiler

    alias = tmp_path / "alias"
    alias.symlink_to(runtime_directory(), target_is_directory=True)
    assert not trusted_compiler(alias / "node_modules/typescript/lib/typescript.js")
    deeper = tmp_path / "parent"
    deeper.symlink_to(runtime_directory().parent, target_is_directory=True)
    assert not trusted_compiler(deeper / runtime_directory().name / "node_modules/typescript/lib/typescript.js")


def test_setup_quarantines_symlink_cache_without_touching_target(tmp_path, monkeypatch):
    import cami.typescript_runtime as runtime

    target = tmp_path / "target"
    target.mkdir()
    marker = target / "marker"
    marker.write_text("preserve")
    destination = tmp_path / "runtime"
    destination.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(runtime, "runtime_directory", lambda: destination)
    assert setup_typescript() == destination
    assert not destination.is_symlink()
    assert marker.read_text() == "preserve" and list(target.iterdir()) == [marker]
    quarantined, = list(tmp_path.glob(".invalid-*"))
    assert quarantined.is_symlink() and quarantined.readlink() == target
