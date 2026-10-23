"""Product searches use independent expected outcomes from captured source text."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cami.errors import ResourceError
from cami.product import store
from cami.product.models import EcmaMatch, EcmaReady
from cami.symbol_search import find_symbols, format_text
from cami.typescript_runtime import compiler_path

FIXTURE = Path(__file__).parent / "fixtures" / "typescript_next"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def next_files():
    return {p.relative_to(FIXTURE).as_posix(): p.read_text()
            for p in FIXTURE.rglob("*") if p.is_file()}


def search(repo, query="createUser", *args, env=None):
    completed = subprocess.run(
        [sys.executable, "-m", "cami.cli", "find", query, "--repo", str(repo.root),
         "--format", "json", *args], capture_output=True, text=True, check=False,
        env={**os.environ, **(env or {})}, timeout=30)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def semantic(data):
    return {k: v for k, v in data.items() if k != "observation"}


def test_next_cli_expected_signature_calls_uses_exports_and_cache(repo):
    repo.commit(next_files())
    before = (repo.git("rev-parse", "HEAD"), repo.git("status", "--porcelain"),
              repo.git("write-tree"))
    data = search(repo)
    match, = data["matches"]
    assert match["language"] == "ts"
    assert match["signature_text"] == "async function createUser(name: string, age?: number): Promise<string>"
    assert match["signature"]["async"] is True
    assert match["site"]["line"] == 1
    assert [r["kind"] for r in match["incoming"]].count("calls") == 2
    assert {r["kind"] for r in match["incoming"]} == {"calls", "imports", "reexports"}
    handler, = search(repo, "UserForm.handleSubmit")["matches"]
    assert handler["language"] == "tsx"
    assert [r["kind"] for r in handler["incoming"]] == ["uses"]
    assert search(repo, "registerUser")["matches"] == [match]
    assert search(repo, "src/lib/index.ts:registerUser")["matches"] == [match]
    second = search(repo, env={"PYTHONHASHSEED": "97"})
    assert second["observation"]["cache_reused"] is True
    assert semantic(data) == semantic(second)
    assert data["typescript"]["analysis"]["offset_unit"] == "utf16_code_units"
    assert before == (repo.git("rev-parse", "HEAD"), repo.git("status", "--porcelain"),
                      repo.git("write-tree"))
    text = format_text(find_symbols(repo.root, "createUser"))
    assert "--calls-->" in text and "UTF" not in text


def test_live_signature_body_delete_revert_and_git_isolation(repo):
    original = next_files()
    repo.commit(original)
    baseline = search(repo)
    path = repo.root / "src/lib/users.ts"
    path.write_text(original["src/lib/users.ts"].replace("name: string", "name: number"))
    edited = search(repo)
    assert "name: number" in edited["matches"][0]["signature_text"]
    assert edited["snapshot"]["generation_id"] != baseline["snapshot"]["generation_id"]
    assert search(repo, "createUser", "--revision", "HEAD")["matches"] == baseline["matches"]
    path.write_text("\n" + original["src/lib/users.ts"])
    moved = search(repo)
    assert moved["matches"][0]["key"] == baseline["matches"][0]["key"]
    assert moved["matches"][0]["occurrence_id"] != baseline["matches"][0]["occurrence_id"]
    path.unlink()
    removed = search(repo)
    assert removed["status"] == "not_found" and removed["absence_confirmed"]
    assert removed["typescript"]["analysis"]["unresolved"]
    path.write_text(original["src/lib/users.ts"])
    assert semantic(search(repo)) == semantic(baseline)


def test_untracked_consumers_targets_and_ignored_outputs(repo):
    repo.commit(next_files())
    baseline = search(repo)
    (repo.root / "extra.ts").write_text("import {createUser} from './src/lib/users'; createUser('x')")
    extended = search(repo)
    assert len(extended["matches"][0]["incoming"]) == len(baseline["matches"][0]["incoming"]) + 2
    (repo.root / ".gitignore").write_text("ignored.ts\n")
    for name in ("ignored.ts", "node_modules/pkg/code.ts", ".next/code.ts", "dist/code.ts", "output/code.ts"):
        path = repo.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export function createUser() {}")
    ignored = search(repo)
    assert len(ignored["matches"]) == 1
    (repo.root / "new.ts").write_text("export const another = () => 3")
    (repo.root / "consumer.ts").write_text("import {another} from './new'; another()")
    assert {r["kind"] for r in search(repo, "another")["matches"][0]["incoming"]} == {"calls", "imports"}


@pytest.mark.parametrize("backend", ["worktree", "git"])
def test_config_jsonc_relative_extends_and_unrelated_huge_json(repo, backend):
    repo.commit({
        "tsconfig.json": '{/*root*/"extends":"./config/base",}',
        "config/base.json": '{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}',
        "src/a.ts": "export function target() {}",
        "other/a.ts": "export function target() {}",
        "src/b.ts": "import {target} from '@/a'; target()",
        "unrelated.json": "x" * (2 * 1024 * 1024 + 1),
        "excluded/huge.json": "x" * (2 * 1024 * 1024 + 1),
    })
    args = ("--revision", "HEAD") if backend == "git" else ()
    data = search(repo, "src/a.ts:target", *args)
    assert {r["kind"] for r in data["matches"][0]["incoming"]} == {"calls", "imports"}
    assert data["coverage"] == "complete"
    assert search(repo, "absent", *args)["absence_confirmed"]
    if backend == "worktree":
        config = repo.root / "config/base.json"
        config.write_text(config.read_text().replace("src/*", "other/*"))
        assert not search(repo, "src/a.ts:target")["matches"][0]["incoming"]
        assert search(repo, "other/a.ts:target")["matches"][0]["incoming"]
        assert search(repo, "src/a.ts:target")["snapshot"] != data["snapshot"]
        config.unlink()
        broken = search(repo, "target")
        assert broken["coverage"] == "partial" and not broken["absence_confirmed"]
        assert not broken["typescript"]["analysis"]["configuration"]["valid"]


def test_barrel_retarget_keeps_unchanged_consumer_honest(repo):
    repo.commit({"a.ts": "export function first() {}", "b.ts": "export function second() {}",
                 "barrel.ts": "export {first as publicName} from './a'",
                 "consumer.ts": "import {publicName} from './barrel'; publicName()"})
    assert search(repo, "publicName")["matches"][0]["qualname"] == "first"
    (repo.root / "barrel.ts").write_text("export {second as publicName} from './b'")
    assert search(repo, "publicName")["matches"][0]["qualname"] == "second"
    assert not search(repo, "first")["matches"][0]["incoming"]


def test_syntax_failure_other_definitions_and_recovery(repo):
    repo.commit({"bad.ts": "export function broken( {", "healthy.ts": "export function healthy(){}"})
    assert search(repo, "healthy")["status"] == "found"
    broken = search(repo, "broken")
    assert broken["coverage"] == "partial" and not broken["absence_confirmed"]
    assert broken["typescript"]["analysis"]["excluded_files"] == [{"path": "bad.ts", "reason": "syntax_error"}]
    (repo.root / "bad.ts").write_text("export function broken() {}")
    assert search(repo, "broken")["coverage"] == "complete"


def test_unavailable_compiler_preserves_python_and_never_false_absence(repo, tmp_path, monkeypatch):
    repo.commit({"a.py": "def python_ok(): pass", "b.ts": "export function target() {}"})
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    python = search(repo, "python_ok")
    assert python["coverage"] == "partial"
    assert python["typescript"]["status"] == "unavailable"
    assert "setup-typescript" in python["typescript"]["message"]
    with pytest.raises(ResourceError, match="setup-typescript"):
        find_symbols(repo.root, "target")
    with pytest.raises(ResourceError, match="setup-typescript"):
        find_symbols(repo.root, "absent")


def test_installing_compiler_invalidates_incomplete_generation(repo, tmp_path, monkeypatch):
    from cami import typescript_runtime

    installed = compiler_path()
    repo.commit({"a.py": "def target(): pass", "a.ts": "export function target(){}"})
    missing = tmp_path / "missing.js"
    monkeypatch.setattr(typescript_runtime, "compiler_path", lambda: missing)
    monkeypatch.setattr("cami.typescript_analyzer.compiler_path", lambda: missing)
    before = find_symbols(repo.root, "target")
    assert len(before.matches) == 1 and before.coverage == "partial"
    monkeypatch.setattr(typescript_runtime, "compiler_path", lambda: installed)
    monkeypatch.setattr("cami.typescript_analyzer.compiler_path", lambda: installed)
    after = find_symbols(repo.root, "target")
    assert len(after.matches) == 2 and after.coverage == "complete"
    assert after.snapshot != before.snapshot
    assert after.snapshot.fingerprint != before.snapshot.fingerprint


def test_node_disappears_after_cache_hit_never_returns_stale_ts(repo, tmp_path, monkeypatch):
    repo.commit({"a.py": "def python_ok(): pass", "a.ts": "export function target(){}"})
    assert find_symbols(repo.root, "target").status == "found"
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    (binary_directory / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(binary_directory))
    with pytest.raises(ResourceError, match="Node"):
        find_symbols(repo.root, "target")
    python = find_symbols(repo.root, "python_ok")
    assert python.coverage == "partial"
    assert python.typescript.status == "unavailable"


def test_transient_bridge_failure_recovers_with_new_result_id_then_reuses_across_processes(repo):
    assert compiler_path().is_file()
    repo.commit({"a.py": "def python_ok(): pass", "a.ts": "export function target(){}"})
    script = """
import sys
import cami.product.ecma as ecma
from cami.cli import main
from cami.typescript_analyzer import TypeScriptAnalyzerError
def fail(*args, **kwargs):
    raise TypeScriptAnalyzerError('controlled transient bridge failure')
ecma.analyze_typescript = fail
raise SystemExit(main(sys.argv[1:]))
"""
    failure = subprocess.run(
        [sys.executable, "-c", script, "find", "python_ok", "--repo", str(repo.root),
         "--format", "json"], capture_output=True, text=True, timeout=30, check=False)
    assert failure.returncode == 0, failure.stderr
    failed = json.loads(failure.stdout)
    assert failed["typescript"]["status"] == "unavailable"
    assert failed["coverage"] == "partial"
    cache = store.GenerationStore(repo.root, store.state_base())
    assert not (cache.path / "current.json").exists()
    assert not (cache.path / "generations" / failed["snapshot"]["generation_id"]).exists()
    recovered = search(repo, "python_ok")
    cached = search(repo, "python_ok")
    assert recovered["snapshot"]["snapshot_id"] == failed["snapshot"]["snapshot_id"]
    assert recovered["snapshot"]["fingerprint"] == failed["snapshot"]["fingerprint"]
    assert recovered["snapshot"]["generation_id"] != failed["snapshot"]["generation_id"]
    assert recovered["typescript"]["status"] == "ready"
    assert recovered["observation"]["cache_reused"] is False
    assert cached["observation"]["cache_reused"] is True
    assert semantic(recovered) == semantic(cached)


def test_python_index_has_no_ecma_records_and_exclude_is_capture_policy(repo):
    repo.commit({"a.py": "def python_ok():pass", "a.ts": "export function target(){}",
                 "excluded/b.ts": "export function target(){}"})
    result = find_symbols(repo.root, "target", excluded_paths=("excluded",))
    assert len(result.matches) == 1 and isinstance(result.matches[0], EcmaMatch)
    cache = store.GenerationStore(repo.root, store.state_base())
    generation = cache.path / "generations" / result.snapshot.generation_id
    payload = json.loads((generation / "index.json").read_bytes())
    assert [module["path"] for module in payload["python"]["modules"]] == ["a.py"]
    assert isinstance(result.typescript, EcmaReady)


def test_alias_default_method_duplicates_shadowing_and_unresolved(repo):
    repo.commit({
        "a.ts": "export default function original(){} export class Users { save(x: string){} } "
                "function duplicate(){} function duplicate(){} duplicate();",
        "b.tsx": "import alias from './a'; import {remote} from 'external'; "
                 "function main(){alias();remote();obj.save()} "
                 "function shadow(alias: unknown){alias()} "
                 "if (enabled){var conditional = () => alias()} conditional();",
    })
    original = search(repo, "default")["matches"][0]
    assert original["qualname"] == "original"
    assert len([r for r in original["incoming"] if r["kind"] == "calls"]) == 2
    assert search(repo, "Users.save")["matches"][0]["signature_text"] == "save(x: string)"
    duplicate = search(repo, "duplicate")
    assert duplicate["status"] == "ambiguous" and len(duplicate["matches"]) == 2
    assert len({m["occurrence_id"] for m in duplicate["matches"]}) == 2
    unresolved = duplicate["typescript"]["analysis"]["unresolved"]
    assert {r["reason"] for r in unresolved} >= {"duplicate_binding", "conditional_binding",
                                                "parameter_binding", "external_or_unmapped_module",
                                                "method_dispatch_unsupported"}


@pytest.mark.parametrize("extension", ["js", "jsx", "ts", "tsx"])
def test_all_extensions_and_unicode_positions(repo, extension):
    repo.commit({f"é.{extension}": "// 😀\nexport const café = () => '🍎'; café()"})
    data = search(repo, "café")
    match, = data["matches"]
    assert match["language"] == extension
    assert match["site"]["line"] == 2 and match["site"]["column"] == 21
    assert data["typescript"]["analysis"]["offset_unit"] == "utf16_code_units"


def test_source_root_keeps_configs_and_relative_base_outside_source(repo):
    repo.commit({"tsconfig.json": '{"extends":"./config/base"}',
                 "config/base.json": '{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}',
                 "src/a.ts": "export function target(){}",
                 "src/b.ts": "import {target} from '@/a'; target()",
                 "other.ts": "export function target(){}"})
    for args in (("--source-root", "src"), ("--source-root", "src", "--revision", "HEAD")):
        data = search(repo, "target", *args)
        assert len(data["matches"]) == 1
        assert len(data["matches"][0]["incoming"]) == 2


@pytest.mark.parametrize("excluded", ["tsconfig.json", "config", "package.json"])
def test_source_exclusion_cannot_hide_effective_configuration_metadata(repo, excluded):
    repo.commit({"tsconfig.json": '{"extends":"./config/base"}',
                 "config/base.json": '{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}',
                 "package.json": '{"type":"module"}',
                 "src/a.ts": "export function target(){}",
                 "src/b.ts": "import {target} from '@/a'; target()"})
    first = search(repo, "target", "--exclude", excluded)
    assert len(first["matches"][0]["incoming"]) == 2
    assert first["typescript"]["analysis"]["configuration"]["valid"]
    config = repo.root / "config/base.json"
    config.write_text(config.read_text().replace("src/*", "missing/*"))
    after = search(repo, "target", "--exclude", excluded)
    assert not after["matches"][0]["incoming"]
    assert first["snapshot"] != after["snapshot"]


def test_ignored_untracked_config_metadata_is_still_effective(repo):
    repo.commit({".gitignore": "tsconfig.json\nconfig/\npackage.json\n",
                 "src/a.ts": "export function target(){}",
                 "src/b.ts": "import {target} from '@/a'; target()"})
    (repo.root / "config").mkdir()
    (repo.root / "config/base.json").write_text('{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}')
    (repo.root / "tsconfig.json").write_text('{"extends":"./config/base"}')
    (repo.root / "package.json").write_text('{"type":"module"}')
    assert len(search(repo, "target")["matches"][0]["incoming"]) == 2


def test_git_directory_symlink_keeps_conservative_coverage_without_target_reads(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.ts").write_text("export function hidden(){}")
    (repo.root / "linked").symlink_to(outside, target_is_directory=True)
    repo.commit({"healthy.ts": "export function healthy(){}"})
    for args in ((), ("--revision", "HEAD")):
        data = search(repo, "hidden", *args)
        assert data["status"] == "not_found" and data["coverage"] == "partial"
        assert not data["absence_confirmed"]
        assert {"path": "linked", "code": "symlink_unsupported"} in data["limitations"]


@pytest.mark.parametrize("backend", ["worktree", "git"])
@pytest.mark.parametrize("directory", ["build", "dist", "excluded"])
def test_active_metadata_under_source_exclusions(repo, backend, directory):
    config = '{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}'
    repo.commit({"tsconfig.json": json.dumps({"extends": f"./{directory}/base"}),
                 f"{directory}/base.json": config,
                 f"{directory}/poison.ts": "export function target(){}",
                 f"{directory}/huge.json": "x" * (2 * 1024 * 1024 + 1),
                 ".gitignore": f"{directory}/\n",
                 "src/a.ts": "export function target(){}",
                 "other/a.ts": "export function target(){}",
                 "consumer.ts": "import {target} from '@/a'; target()"})
    repo.git("add", "-f", f"{directory}/base.json")
    if directory in ("build", "dist"):
        repo.git("add", "-f", f"{directory}/poison.ts", f"{directory}/huge.json")
    repo.git("commit", "-qm", "config fixture")
    args = ("--revision", "HEAD") if backend == "git" else ()
    if directory == "excluded" and backend == "worktree":
        args += ("--exclude", directory)
    before = search(repo, "src/a.ts:target", *args)
    assert before["typescript"]["analysis"]["configuration"]["valid"]
    assert {r["kind"] for r in before["matches"][0]["incoming"]} == {"calls", "imports"}
    assert before["coverage"] == "complete"
    assert f"{directory}/poison.ts" not in before["typescript"]["analysis"]["analyzed_files"]
    config_path = repo.root / directory / "base.json"
    config_path.write_text(config.replace("src/*", "other/*"))
    if backend == "git":
        assert search(repo, "src/a.ts:target", *args)["matches"] == before["matches"]
        repo.git("add", "-f", f"{directory}/base.json")
        repo.git("commit", "-qm", "retarget config fixture")
    after = search(repo, "src/a.ts:target", *args)
    assert not after["matches"][0]["incoming"]
    assert after["snapshot"] != before["snapshot"]
    assert {r["kind"] for r in search(repo, "other/a.ts:target", *args)["matches"][0]["incoming"]} == {"calls", "imports"}


def test_missing_excluded_metadata_created_after_query(repo):
    repo.commit({"tsconfig.json": '{"extends":"./build/base.json"}',
                 "src/a.ts": "export function target(){}",
                 "consumer.ts": "import {target} from '@/a'; target()"})
    before = search(repo, "target")
    assert not before["typescript"]["analysis"]["configuration"]["valid"]
    (repo.root / "build").mkdir()
    (repo.root / "build/base.json").write_text(
        '{"compilerOptions":{"baseUrl":"..","paths":{"@/*":["src/*"]}}}')
    after = search(repo, "target")
    assert after["snapshot"] != before["snapshot"]
    assert after["typescript"]["analysis"]["configuration"]["valid"]
    assert {r["kind"] for r in after["matches"][0]["incoming"]} == {"calls", "imports"}
