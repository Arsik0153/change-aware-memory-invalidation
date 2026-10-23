import json
from pathlib import Path

import pytest

from cami.ecma_models import EcmaAnalysis
from cami.typescript_analyzer import (
    TypeScriptAnalyzerError,
    TypeScriptAnalyzerUnavailable,
    _validate_analysis,
    analyze_typescript,
)

FIXTURE = Path(__file__).parent / "fixtures" / "typescript_next"


def capture() -> dict[str, str]:
    return {
        p.relative_to(FIXTURE).as_posix(): p.read_text() for p in FIXTURE.rglob("*") if p.is_file()
    }


def names(result: EcmaAnalysis) -> dict[str, str]:
    return {d.id: d.key.qualname for d in result.definitions}


def calls(result: EcmaAnalysis) -> set[tuple[str | None, str]]:
    symbols = names(result)
    return {
        (symbols.get(r.source), symbols[r.target]) for r in result.relations if r.kind == "calls"
    }


def test_next_fixture_independent_expected_graph() -> None:
    files = capture()
    result = analyze_typescript(files, request_id="next-fixture")
    assert result.request_id == "next-fixture"
    assert result.compiler_version == "6.0.3"
    assert result.configuration.valid
    assert result.configuration.module_resolution == "Bundler"
    assert not result.diagnostics
    assert {d.key.qualname for d in result.definitions} == {
        "createUser",
        "POST",
        "UserForm",
        "UserForm.handleSubmit",
    }
    assert calls(result) == {("POST", "createUser"), ("UserForm.handleSubmit", "createUser")}
    symbols = names(result)
    assert {
        (symbols.get(r.source), symbols[r.target]) for r in result.relations if r.kind == "uses"
    } == {("UserForm", "UserForm.handleSubmit")}
    create = next(d for d in result.definitions if d.name == "createUser")
    assert create.site.line == 1 and create.site.end_line == 3
    assert create.signature.async_
    assert [(p.pattern, p.annotation, p.optional) for p in create.signature.parameters] == [
        ("name", "string", False),
        ("age", "number", True),
    ]
    assert create.signature.return_annotation == "Promise<string>"
    assert {(e.path, e.name) for e in result.exports if e.target == create.id} == {
        ("src/lib/users.ts", "createUser"),
        ("src/lib/index.ts", "registerUser"),
    }
    assert len([r for r in result.relations if r.kind == "imports"]) == 2
    assert len([r for r in result.relations if r.kind == "reexports"]) == 1
    assert (
        analyze_typescript(dict(reversed(list(files.items()))), request_id="next-fixture") == result
    )


def test_edit_delete_revert_and_new_consumer_captures() -> None:
    files = capture()
    baseline = analyze_typescript(files)
    edited = {
        **files,
        "src/lib/users.ts": files["src/lib/users.ts"].replace("age?: number", "age = 18"),
    }
    changed = analyze_typescript(edited)
    assert (
        next(d for d in changed.definitions if d.name == "createUser")
        .signature.parameters[1]
        .default
        == "18"
    )
    assert calls(changed) == calls(baseline)
    assert (
        next(d for d in baseline.definitions if d.name == "createUser").syntax_hash
        != next(d for d in changed.definitions if d.name == "createUser").syntax_hash
    )
    deleted = analyze_typescript({k: v for k, v in files.items() if k != "src/lib/users.ts"})
    assert "createUser" not in names(deleted).values()
    assert not calls(deleted)
    assert {u.reason for u in deleted.unresolved if u.kind == "calls"} == {"missing_module"}
    assert analyze_typescript(files) == baseline
    added = analyze_typescript(
        {
            **files,
            "untracked.ts": "import {createUser} from './src/lib/users'; export function extra() {createUser('x')}",
        }
    )
    assert calls(added) == calls(baseline) | {("extra", "createUser")}


@pytest.mark.parametrize(
    "body,reason",
    [
        ("function outer(createUser) { createUser() }", "parameter_binding"),
        ("function outer() { createUser(); const createUser = unknown }", "unsupported_binding"),
        (
            "function outer() { { createUser(); let createUser = () => 1 } }",
            "before_initialization",
        ),
        ("function outer() { try {} catch(createUser) { createUser() } }", "catch_binding"),
        ("function outer() { for (let createUser of []) { createUser() } }", "unsupported_binding"),
        ("function outer({createUser}) { createUser() }", "parameter_binding"),
        ("function outer() { const {createUser} = obj; createUser() }", "unsupported_binding"),
        ("function outer() { createUser = replacement; createUser() }", "reassigned_binding"),
        ("function outer() { [createUser] = list; createUser() }", "reassigned_binding"),
        ("function outer() { ({x:createUser} = obj); createUser() }", "reassigned_binding"),
        ("function outer() { for(createUser of xs) {} createUser() }", "reassigned_binding"),
    ],
)
def test_shadowing_and_writes_never_fall_through_to_import(body: str, reason: str) -> None:
    result = analyze_typescript(
        {
            "a.ts": "export function createUser() {}",
            "b.ts": "import {createUser} from './a'; " + body,
        }
    )
    assert not calls(result)
    assert reason in {u.reason for u in result.unresolved if u.kind == "calls"}


def test_conditional_duplicate_alias_and_temporal_bindings() -> None:
    result = analyze_typescript(
        {
            "a.js": """
function original() {}
if (enabled) { var conditional = () => original() }
conditional();
function duplicate() {}
function duplicate() {}
duplicate();
const alias = original; alias();
before(); const before = () => original();
"""
        }
    )
    assert calls(result) == {("conditional", "original"), ("before", "original")}
    assert {u.reason for u in result.unresolved if u.kind == "calls"} >= {
        "conditional_binding",
        "duplicate_binding",
        "unsupported_binding",
        "before_initialization",
    }
    duplicates = [d for d in result.definitions if d.name == "duplicate"]
    assert len(duplicates) == 2 and len({d.id for d in duplicates}) == 2
    assert all(d.ambiguous for d in duplicates)
    duplicate_ref = next(u for u in result.unresolved if u.name == "duplicate")
    assert set(duplicate_ref.candidates) == {d.id for d in duplicates}


def test_default_named_function_expressions_nested_methods_and_signatures() -> None:
    result = analyze_typescript(
        {
            "a.ts": """
export default async function* create<T extends string>({x}: {x: T}, y?: number, ...rest: T[]): AsyncGenerator<T> { yield x }
export const expression = function inner() { inner(); function nested() {} nested(); };
export class Users { async save(x: string = 'x') { return create() } }
""",
            "b.ts": "import alias from './a'; function consumer() { alias(); obj.save(); this.save(); obj['save'](); }",
        }
    )
    assert {d.key.qualname for d in result.definitions} == {
        "create",
        "expression",
        "expression.nested",
        "Users.save",
        "consumer",
    }
    assert calls(result) == {
        ("expression", "expression"),
        ("expression", "expression.nested"),
        ("Users.save", "create"),
        ("consumer", "create"),
    }
    assert {u.reason for u in result.unresolved if u.kind == "calls"} >= {
        "method_dispatch_unsupported",
        "computed_dispatch_unsupported",
    }
    create = next(d for d in result.definitions if d.name == "create")
    assert create.signature.generator and create.signature.async_
    assert create.signature.type_parameters == ("T extends string",)
    assert create.signature.parameters[0].pattern == "{x}"
    assert create.signature.parameters[2].rest
    assert create.signature.parameters[2].annotation == "T[]"
    method = next(d for d in result.definitions if d.name == "save")
    assert method.signature.parameters[0].default == "'x'"


def test_anonymous_callbacks_have_own_scope_and_function_props_are_uses() -> None:
    result = analyze_typescript(
        {
            "a.tsx": """
function save() {}
function Container() {
  run(() => { save(); function nested() {save()} });
  return <Button onClick={save} />;
}
"""
        }
    )
    nested = next(d for d in result.definitions if d.name == "nested")
    assert "<callback@" in nested.key.qualname
    assert calls(result) == {(None, "save"), (nested.key.qualname, "save")}
    symbols = names(result)
    assert {
        (symbols.get(r.source), symbols[r.target]) for r in result.relations if r.kind == "uses"
    } == {("Container", "save")}


def test_namespace_typeonly_external_dynamic_and_declaration_files() -> None:
    result = analyze_typescript(
        {
            "a.ts": "export function f() {}",
            "types.d.ts": "export function declared(): void",
            "b.ts": """
import * as ns from './a';
import type {f as TypeF} from './a';
import {remote} from 'remote-package';
import {declared} from './types';
function main(x: TypeF) { ns.f(); TypeF(); remote(); declared(); import('./a'); require('./a'); }
""",
        }
    )
    assert calls(result) == {("main", "f")}
    assert {u.reason for u in result.unresolved} >= {
        "type_only_reference",
        "external_or_unmapped_module",
        "declaration_only_module",
        "dynamic_call_unsupported",
        "unknown_binding",
    }
    assert any(u.type_only and u.kind == "uses" for u in result.unresolved)
    assert [(x.path, x.reason) for x in result.excluded_files] == [
        ("types.d.ts", "declaration_file")
    ]
    mutated = analyze_typescript(
        {
            "a.ts": "export function f() {}",
            "b.ts": "import * as ns from './a'; function main(){ns.f = other; ns.f()}",
        }
    )
    assert not calls(mutated)
    assert any(u.reason == "reassigned_binding" and u.kind == "calls" for u in mutated.unresolved)


def test_syntax_error_excludes_file_and_fix_restores_without_stale_edges() -> None:
    files = {
        "a.ts": "export function f() {}",
        "bad.ts": "export function broken( {",
        "b.ts": "import {broken} from './bad'; function healthy(){broken()}",
    }
    bad = analyze_typescript(files)
    assert {d.name for d in bad.definitions} == {"f", "healthy"}
    assert any(d.code.startswith("TS") and d.severity == "error" for d in bad.diagnostics)
    assert {u.reason for u in bad.unresolved if u.kind == "calls"} == {
        "excluded_or_uncaptured_module"
    }
    fixed = analyze_typescript({**files, "bad.ts": "export function broken() {}"})
    assert calls(fixed) == {("healthy", "broken")}
    assert not fixed.excluded_files


def test_config_paths_edit_relative_extends_jsonc_and_jsconfig() -> None:
    files = {
        "jsconfig.json": '{"extends":"./config/base"}',
        "config/base.json": '{/* JSONC */ "compilerOptions": {"baseUrl":"..", '
        '"paths":{"@/*":["src/*"]},"moduleResolution":"bundler"}}',
        "src/a.ts": "export function f() {}",
        "other/a.ts": "export function f() {}",
        "b.ts": "import {f} from '@/a'; function b(){f()}",
    }
    first = analyze_typescript(files)
    target = next(r.target for r in first.relations if r.kind == "calls")
    assert next(d.key.path for d in first.definitions if d.id == target) == "src/a.ts"
    changed = analyze_typescript(
        {**files, "config/base.json": files["config/base.json"].replace("src/*", "other/*")}
    )
    target = next(r.target for r in changed.relations if r.kind == "calls")
    assert next(d.key.path for d in changed.definitions if d.id == target) == "other/a.ts"
    assert first.configuration.fingerprint != changed.configuration.fingerprint


@pytest.mark.parametrize(
    "config,extra,code",
    [
        (
            '{"extends":"./base"}',
            {"base.json": '{"extends":"./tsconfig"}'},
            "config_cycle_or_depth",
        ),
        ('{"extends":"package-config"}', {}, "external_extends"),
        ('{"extends":"../outside"}', {}, "config_escape"),
        ('{"extends":"./absent"}', {}, "missing_config"),
        ('{"compilerOptions":{"moduleResolution":"nonsense"}}', {}, "TS6046"),
        ('{"references":[]}', {}, "project_references_unsupported"),
    ],
)
def test_invalid_configs_are_explicit_and_disable_resolution(
    config: str, extra: dict[str, str], code: str
) -> None:
    result = analyze_typescript(
        {
            "tsconfig.json": config,
            **extra,
            "a.ts": "export function f() {}",
            "b.ts": "import {f} from './a'; f()",
        }
    )
    assert not result.configuration.valid
    assert code in {d.code for d in result.diagnostics}
    assert not calls(result)
    assert any(u.reason == "invalid_config" for u in result.unresolved)


def test_reexport_cycle_star_and_duplicate_exports_do_not_guess() -> None:
    result = analyze_typescript(
        {
            "a.ts": "export {f} from './b'",
            "b.ts": "export {f} from './a'",
            "star.ts": "export * from './a'",
            "consumer.ts": "import {f} from './a'; f()",
            "dup.ts": "function x(){} function y(){} export {x as f, y as f}",
        }
    )
    assert not calls(result)
    assert {u.reason for u in result.unresolved} >= {"reexport_cycle", "export_star_unsupported"}
    assert all(e.target is None for e in result.exports)
    duplicates = [e for e in result.exports if e.path == "dup.ts"]
    assert len(duplicates) == 2
    assert all(e.reason == "ambiguous_export" and len(e.candidates) == 2 for e in duplicates)


def test_unicode_offsets_are_utf16_and_hashes_ignore_comments_only_in_ast() -> None:
    text = "// 😀\r\nconst café = async (名: string = '🍎') => 名;\r\ncafé();"
    result = analyze_typescript({"é.ts": text.encode()})
    definition = result.definitions[0]
    fragment = text.encode("utf-16-le")[definition.site.start * 2 : definition.site.end * 2].decode(
        "utf-16-le"
    )
    assert fragment == "async (名: string = '🍎') => 名"
    assert definition.site.line == 2 and definition.site.column == 14
    assert calls(result) == {(None, "café")}
    commented = analyze_typescript({"é.ts": text.replace("=> 名", "=> /*note*/ 名")})
    assert commented.definitions[0].ast_hash == definition.ast_hash
    assert commented.definitions[0].syntax_hash != definition.syntax_hash


@pytest.mark.parametrize(
    "name",
    [
        "../a.ts",
        "/a.ts",
        "a//b.ts",
        "a/./b.ts",
        "a\\b.ts",
        "C:a.ts",
        "node_modules/a.ts",
        "a\x00.ts",
    ],
)
def test_reject_unsafe_capture_paths(name: str) -> None:
    with pytest.raises(ValueError):
        analyze_typescript({name: "function f(){}"})


def test_node_absence_timeout_and_environment_sanitization(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeScriptAnalyzerUnavailable, match="Node"):
        analyze_typescript({}, node_executable="/nonexistent/node")
    with pytest.raises(TypeScriptAnalyzerError, match="timeout"):
        analyze_typescript({"a.ts": "function f(){}"}, timeout=0.000001)
    monkeypatch.setenv("NODE_OPTIONS", "--require=/nonexistent/evil.js")
    monkeypatch.setenv("NODE_PATH", "/nonexistent/target/node_modules")
    assert len(analyze_typescript({"a.ts": "function f(){}"}).definitions) == 1


def test_missing_dependency_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("cami.typescript_analyzer.compiler_path", lambda: tmp_path / "missing.js")
    with pytest.raises(TypeScriptAnalyzerUnavailable, match="npm ci --ignore-scripts"):
        analyze_typescript({})


def test_boundary_rejects_wrong_request_unknown_paths_and_dangling_targets() -> None:
    files = {"a.ts": "function f(){} f()"}
    result = analyze_typescript(files)
    for mutate in (
        lambda d: d.update(request_id="wrong"),
        lambda d: d["definitions"][0]["site"].update(path="other.ts"),
        lambda d: d["relations"][0].update(target="unknown"),
        lambda d: d["definitions"][0]["site"].update(end=9999),
    ):
        data = json.loads(result.model_dump_json(by_alias=True))
        mutate(data)
        with pytest.raises(ValueError):
            _validate_analysis(
                EcmaAnalysis.model_validate_json(json.dumps(data)), files, "snapshot"
            )


def test_catch_and_loop_bindings_do_not_leak_and_function_hoisting_is_supported() -> None:
    result = analyze_typescript(
        {
            "a.js": """
function createUser() {}
function outer() {
  try {} catch (createUser) { createUser() }
  for (let createUser of []) {createUser()}
  createUser(); hoisted(); function hoisted() {}
}
"""
        }
    )
    assert calls(result) == {("outer", "createUser"), ("outer", "outer.hoisted")}


def test_dynamic_eval_and_with_scopes_are_explicit() -> None:
    result = analyze_typescript(
        {
            "a.js": """
function f() {}
function a() {eval('var f = replacement'); f()}
function b() {with (object) {f()}}
"""
        }
    )
    assert not calls(result)
    assert any(u.reason == "dynamic_scope_unsupported" and u.name == "f" for u in result.unresolved)
    assert any(d.code == "dynamic_scope_unsupported" for d in result.diagnostics)


def test_direct_node_transport_uses_capture_only_without_executing_sources(tmp_path: Path) -> None:
    import subprocess

    from cami.typescript_analyzer import sidecar_directory
    from cami.typescript_runtime import compiler_path

    marker = tmp_path / "executed"
    (tmp_path / "live.ts").write_text("export function f() {}")
    source = f"require('node:fs').writeFileSync({json.dumps(str(marker))}, 'executed'); "
    source += "import {f} from './live'; function healthy(){f()}"
    payload = dict(
        schema_version=1, request_id="direct-node", root_config=None, files={"a.ts": source}
    )
    completed = subprocess.run(
        ["node", str(sidecar_directory() / "analyze.cjs"), str(compiler_path())],
        input=json.dumps(payload).encode(),
        cwd=tmp_path,
        capture_output=True,
        timeout=15,
        check=True,
    )
    result = EcmaAnalysis.model_validate_json(completed.stdout)
    assert result.request_id == "direct-node"
    assert not calls(result)
    assert any(u.reason == "missing_module" for u in result.unresolved)
    assert not marker.exists()
    assert (tmp_path / "live.ts").read_text() == "export function f() {}"


def test_index_extensions_default_anonymous_and_commonjs_are_explicit() -> None:
    result = analyze_typescript(
        {
            "lib/index.jsx": "export default () => null; export function f() {}",
            "main.js": "import view from './lib'; import {f} from './lib/index.js'; "
            "import 'external-side-effect'; view(); f(); module.exports = f;",
        }
    )
    assert calls(result) == {(None, "<default>"), (None, "f")}
    assert any(u.kind == "imports" and u.reason == "side_effect_import" for u in result.unresolved)
    assert any(u.reason == "method_dispatch_unsupported" for u in result.unresolved)


def test_barrel_edit_recomputes_targets_with_unchanged_consumer() -> None:
    files = {
        "a.ts": "export function f() {}",
        "b.ts": "export function g() {}",
        "barrel.ts": "export {f as publicName} from './a'",
        "consumer.ts": "import {publicName} from './barrel'; function use(){publicName()}",
    }
    assert calls(analyze_typescript(files)) == {("use", "f")}
    assert calls(
        analyze_typescript({**files, "barrel.ts": "export {g as publicName} from './b'"})
    ) == {("use", "g")}


def test_overloads_and_mutated_default_export_are_not_chosen() -> None:
    result = analyze_typescript(
        {
            "a.ts": """
export function f(x: number): number;
export function f(x: string): string;
export function f(x: unknown) {return x}
export default function other() {}
other = replacement;
""",
            "b.ts": "import other, {f} from './a'; f(); other();",
        }
    )
    assert not calls(result)
    overloads = [d for d in result.definitions if d.name == "f"]
    assert len(overloads) == 3 and sum(d.implementation for d in overloads) == 1
    assert all(d.ambiguous for d in overloads)
    assert any(u.reason == "reassigned_binding" for u in result.unresolved)


def test_recursive_arrow_and_jsx_function_argument_are_not_conflated() -> None:
    result = analyze_typescript(
        {
            "a.tsx": """
const recursive = (n: number) => n ? recursive(n - 1) : null;
function Parent() { return <Button render={recursive} /> }
"""
        }
    )
    assert calls(result) == {("recursive", "recursive")}
    symbols = names(result)
    assert {
        (symbols.get(r.source), symbols[r.target]) for r in result.relations if r.kind == "uses"
    } == {("Parent", "recursive")}


def test_wire_schema_rejects_bool_version_and_extra_fields() -> None:
    raw = json.loads(analyze_typescript({}).model_dump_json(by_alias=True))
    for fields in ({"schema_version": True}, {"unknown": "field"}):
        with pytest.raises(ValueError):
            EcmaAnalysis.model_validate_json(json.dumps({**raw, **fields}))


def test_implicit_arguments_binding_and_ts_wrapped_assignments() -> None:
    result = analyze_typescript(
        {
            "a.ts": """
const arguments = () => 1;
function outer() { arguments(); }
let f = () => 1;
f! = replacement;
f();
"""
        }
    )
    assert not calls(result)
    assert {u.reason for u in result.unresolved if u.kind == "calls"} >= {
        "implicit_arguments_binding",
        "reassigned_binding",
    }


def test_case_collisions_and_excluded_namespace_bodies() -> None:
    result = analyze_typescript(
        {
            "A.ts": "export function f(){}",
            "a.ts": "export function g(){}",
            "b.ts": "import {f} from './A'; function healthy(){f()} namespace N { function inner(){healthy()} }",
        }
    )
    assert {x.path for x in result.excluded_files} == {"A.ts", "a.ts"}
    assert {d.name for d in result.definitions} == {"healthy"}
    assert not calls(result)
    assert {d.code for d in result.diagnostics} >= {
        "case_collision",
        "namespace_or_enum_unsupported",
    }


def test_transport_limits_invalid_utf8_and_explicit_root_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        analyze_typescript({"a.ts": b"\xff"})
    monkeypatch.setattr("cami.typescript_analyzer.MAX_FILES", 1)
    with pytest.raises(ValueError, match="files"):
        analyze_typescript({"a.ts": "", "b.ts": ""})
    monkeypatch.setattr("cami.typescript_analyzer.MAX_INPUT_BYTES", 100)
    with pytest.raises(ValueError, match="16 MiB"):
        analyze_typescript({"a.ts": "x" * 101})
    with pytest.raises(ValueError, match="Serialized"):
        analyze_typescript({"a.ts": "x" * 50})
    monkeypatch.setattr("cami.typescript_analyzer.MAX_INPUT_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr("cami.typescript_analyzer.MAX_OUTPUT_BYTES", 1)
    with pytest.raises(TypeScriptAnalyzerError, match="32 MiB"):
        analyze_typescript({})
    monkeypatch.setattr("cami.typescript_analyzer.MAX_OUTPUT_BYTES", 32 * 1024 * 1024)
    result = analyze_typescript(
        {"config/custom.json": '{"compilerOptions":{"moduleResolution":"node16"}}'},
        root_config="config/custom.json",
    )
    assert result.configuration.root_config == "config/custom.json"
    assert result.configuration.module_resolution == "Node16"


def test_nodenext_package_format_changes_extensionless_resolution() -> None:
    files = {
        "tsconfig.json": '{"compilerOptions":{"module":"nodenext","moduleResolution":"nodenext"}}',
        "package.json": '{"type":"module"}',
        "a.ts": "export function f() {}",
        "b.ts": "import {f} from './a'; function b(){f()}",
        "c.ts": "import {f} from './a.js'; function c(){f()}",
    }
    esm = analyze_typescript(files)
    assert calls(esm) == {("c", "f")}
    assert any(
        u.name == "f" and u.kind == "calls" and u.reason == "missing_module" for u in esm.unresolved
    )
    commonjs = analyze_typescript({**files, "package.json": '{"type":"commonjs"}'})
    assert calls(commonjs) == {("b", "f"), ("c", "f")}
    assert esm.configuration.fingerprint != commonjs.configuration.fingerprint


@pytest.mark.parametrize(
    "body,expected,unresolved_reason",
    [
        ("function run(){ const {handler = (createUser) => createUser()} = {}; }", set(), "parameter_binding"),
        ("function run(){ const [handler = (createUser) => createUser()] = []; }", set(), "parameter_binding"),
        ("function run(){ const {outer: {handler = (createUser) => createUser()}} = {}; }", set(), "parameter_binding"),
        ("function run(){ const {handler = () => { function createUser(){} createUser(); }} = {}; }", {(None, "run.<callback@65>.createUser")}, None),
        ("function run(){ const {handler = () => createUser()} = {}; }", {(None, "createUser")}, None),
        ("function run(){ const {[(() => createUser())()]: handler} = {}; }", {(None, "createUser")}, None),
        ("function run(){ const {handler = () => { const createUser = unknown; createUser(); }} = {}; }", set(), "unsupported_binding"),
        ("function run(){ const {handler = () => { try {} catch(createUser) { createUser(); } }} = {}; }", set(), "catch_binding"),
        ("function run(cb = () => createUser()){ function createUser(){} cb(); }", {(None, "createUser")}, None),
        ("function run(cb = createUser()){ function createUser(){} }", {("run", "createUser")}, None),
        ("function run({cb = () => createUser()} = {}){ var createUser; }", {(None, "createUser")}, None),
        ("function run([cb = (createUser) => createUser()] = []){}", set(), "parameter_binding"),
        ("function run(cb = () => createUser(), createUser = unknown){}", set(), "parameter_binding"),
        ("function run(){ const handler = () => createUser(); handler(); }", {("run.handler", "createUser"), ("run", "run.handler")}, None),
    ],
)
def test_binding_expression_scopes_and_parameter_body_environments(body, expected, unresolved_reason):
    result = analyze_typescript({"a.ts": "export function createUser(){}",
                                 "b.ts": "import {createUser} from './a'; " + body})
    actual = calls(result)
    assert actual == expected
    if unresolved_reason:
        assert any(u.kind == "calls" and u.name == "createUser" and u.reason == unresolved_reason
                   for u in result.unresolved)
    for relation in result.relations:
        if relation.kind == "calls" and relation.source is None and relation.site.path == "b.ts":
            assert ":function" in relation.scope or ":block" in relation.scope


@pytest.mark.parametrize("body", [
    "export default [(createUser) => createUser()]",
    "export default ((createUser) => createUser())(unknown)",
])
def test_unsupported_export_expression_still_collects_lexical_scopes(body):
    result = analyze_typescript({"a.ts": "export function createUser(){}",
                                 "b.ts": "import {createUser} from './a'; " + body})
    assert not calls(result)
    unresolved, = [u for u in result.unresolved if u.kind == "calls" and u.name == "createUser"]
    assert unresolved.reason == "parameter_binding" and unresolved.source is None
