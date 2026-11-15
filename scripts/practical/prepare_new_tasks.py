"""Prepare source-bound historical issue tasks, before model execution."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runs/practical-complete-20261115/tasks"

# Selection is by concrete historical behavior, never by model outcome.
TASKS = [
    (
        "click",
        "bf1e8be",
        "flag-default-map",
        "Fix boolean flag help defaults when default_map overrides the default. For a --name/--no-name flag, help must display the effective flag name matching the context's default_map, including nested command defaults.",
        "test_defaults.py",
    ),
    (
        "click",
        "61f8101",
        "empty-default",
        'Fix option help for default="" with show_default=True. It must explicitly show [default: ""] rather than silently hiding the empty string. Preserve other default formatting.',
        "test_options.py",
    ),
    (
        "click",
        "3f91d21",
        "escaped-path",
        "Fix Path conversion errors for directory names containing literal backslashes or control characters. The offending path should use an escaped representation so the error stays readable on one line. Preserve other path validation.",
        "test_types.py",
    ),
    (
        "click",
        "4cf7c6c",
        "completion-hidden-argument",
        "Fix shell completion for arguments with expose_value=False. Such arguments are intentionally absent from Context.params; completing them must not raise KeyError and should still return their completions.",
        "test_shell_completion.py",
    ),
    (
        "requests",
        "3ff3ff21",
        "json-error-pickle",
        "Fix requests.exceptions.JSONDecodeError pickle round trips. pickle.loads(pickle.dumps(error)) must preserve the JSON error message, document and position, so invalid JSON errors can cross process boundaries.",
        "test_utils.py",
    ),
    (
        "requests",
        "3fd309a5",
        "utf8-body-length",
        "Fix super_len on str bodies to count their UTF-8 encoded bytes, including non-ASCII text. Preserve bytes, stream offsets and existing non-string length behavior. The runtime uses urllib3 2.x.",
        "test_utils.py",
    ),
    (
        "requests",
        "60389df6",
        "leading-url-slashes",
        "Fix HTTPAdapter.request_url for URLs with multiple leading path separators. For http://127.0.0.1:10000//v:h without a proxy, return /v:h so urllib3 does not reinterpret it as a host. Preserve query strings and proxy behavior.",
        "test_utils.py",
    ),
    (
        "requests",
        "e45b4289",
        "http-status-aliases",
        "Add RFC 9110 HTTP status aliases to requests.codes: content_too_large=413, uri_too_long=414 and unprocessable_content=422. Preserve the older names for those status codes and ordinary existing status aliases.",
        "test_utils.py",
    ),
    (
        "packaging-development-v1",
        "2b06f90",
        "iterable-specifiers",
        "Allow SpecifierSet to be constructed from an iterable of Specifier objects, including lists and generators. Preserve string construction, duplicate removal and the prereleases override.",
        "test_specifiers.py",
    ),
    (
        "packaging-development-v1",
        "a716c52",
        "dynamic-field-error",
        "Improve the invalid dynamic metadata error. When a disallowed dynamic field such as name or version is supplied, identify that particular field in the InvalidMetadata message rather than formatting the entire list of fields. Preserve validation of supported dynamic fields.",
        "test_metadata.py",
    ),
    (
        "packaging-development-v1",
        "c385b58",
        "provided-full-version",
        "Repair python_full_version values ending in a lone + even when supplied explicitly to Marker.evaluate. For example python_full_version < '3.12' with {'python_full_version':'3.11.1+'} must evaluate successfully. Keep default-environment repair and valid version handling.",
        "test_markers.py",
    ),
    (
        "packaging-development-v1",
        "3e67fc7",
        "platform-full-version",
        "Handle non-tagged CPython platform.python_version() values such as 3.11.1+ when evaluating environment markers. Repair the default environment so python_full_version < '3.12' evaluates instead of raising InvalidVersion. Preserve valid versions.",
        "test_markers.py",
    ),
]

ACCEPT = {
    "flag-default-map": """import click
from click.testing import CliRunner
def test_effective_flag_default():
    @click.group()
    def cli(): pass
    @cli.command()
    @click.option('--name/--no-name', show_default=True, help='name flag')
    def foo(name): click.echo(name)
    r=CliRunner()
    assert 'default: no-name' in r.invoke(cli,['foo','--help']).output
    assert 'default: name' in r.invoke(cli,['foo','--help'],default_map={'foo':{'name':True}}).output
    assert r.invoke(cli,['foo'],default_map={'foo':{'name':True}}).output.strip()=='True'
""",
    "empty-default": """import click
def test_empty_default():
    ctx=click.Context(click.Command('cli'))
    assert '[default: ""]' in click.Option(['--limit'],default='',show_default=True).get_help_record(ctx)[1]
    assert 'default: 3' in click.Option(['--limit'],default=3,show_default=True).get_help_record(ctx)[1]
""",
    "escaped-path": """import click, tempfile, pytest
def test_escaped_directory():
    with tempfile.TemporaryDirectory(prefix=r'my\\ndir') as d:
        with pytest.raises(click.BadParameter) as e: click.Path(dir_okay=False,resolve_path=True).convert(d,None,None)
        assert r'my\\\\ndir' in e.value.message
    with tempfile.TemporaryDirectory(prefix='my\\ndir') as d:
        with pytest.raises(click.BadParameter) as e: click.Path(dir_okay=False,resolve_path=True).convert(d,None,None)
        assert '\\n' not in e.value.message
""",
    "completion-hidden-argument": """import click
from click.shell_completion import ShellComplete,CompletionItem
def test_hidden_argument_completion():
    @click.command()
    @click.argument('value',expose_value=False,shell_complete=lambda c,p,i:[CompletionItem('hello')])
    def cli(): pass
    assert [x.value for x in ShellComplete(cli,{},'cli','_CLI_COMPLETE').get_completions([],'he')]==['hello']
""",
    "json-error-pickle": """import pickle,pytest
from requests.exceptions import JSONDecodeError
@pytest.mark.parametrize('doc,pos',[('{bad}',1),('abc',2),('',0)])
def test_json_error_roundtrip(doc,pos):
    e=JSONDecodeError('Invalid',doc,pos); r=pickle.loads(pickle.dumps(e))
    assert (r.msg,r.doc,r.pos,str(r))==(e.msg,e.doc,e.pos,str(e))
""",
    "utf8-body-length": """from requests.utils import super_len
from io import BytesIO
import pytest
@pytest.mark.parametrize('value',['é','你好','plain','😀',''])
def test_utf8_length(value): assert super_len(value)==len(value.encode('utf-8'))
def test_stream_offset():
    b=BytesIO(b'abc');b.read(1);assert super_len(b)==2
""",
    "leading-url-slashes": """import requests,pytest
@pytest.mark.parametrize('path',['//v:h','///v:h?q=2','////abc'])
def test_leading_path_slashes(path):
    p=requests.Request('GET','http://127.0.0.1:10000'+path).prepare()
    assert requests.adapters.HTTPAdapter().request_url(p,{})=='/'+path.lstrip('/')
""",
    "http-status-aliases": """from requests import codes
import pytest
@pytest.mark.parametrize('alias,value',[('content_too_large',413),('uri_too_long',414),('unprocessable_content',422),('request_entity_too_large',413),('request_uri_too_large',414),('unprocessable_entity',422),('ok',200)])
def test_alias(alias,value): assert codes[alias]==value
""",
    "iterable-specifiers": "from packaging.specifiers import Specifier,SpecifierSet\nimport pytest\n@pytest.mark.parametrize('factory',[list,tuple,iter])\ndef test_iterable(factory):\n    s=SpecifierSet(factory([Specifier('>=1'),Specifier('<3'),Specifier('>=1')]))\n    assert len(s)==2 and s.contains('2') and not s.contains('3')\ndef test_override(): assert SpecifierSet([Specifier('>=1')],prereleases=True).prereleases is True\n",
    "prerelease-inequalities": """from packaging.specifiers import Specifier
import pytest
@pytest.mark.parametrize('spec,version',[('>3.0.0a7','3.0.0a8'),('<3.0.0a8','3.0.0a7'),('>1.0.dev1','1.0.dev2')])
def test_prerelease(spec,version): assert Specifier(spec).contains(version)
def test_exclusion(): assert not Specifier('!=1.0.dev1').prereleases
""",
    "dynamic-field-error": """from packaging.metadata import Metadata,InvalidMetadata
import pytest
@pytest.mark.parametrize('field',['name','version','metadata-version'])
def test_dynamic_error(field):
    m=Metadata.from_raw({'dynamic':[field,'summary']},validate=False)
    with pytest.raises(InvalidMetadata) as e: m.dynamic
    assert repr(field)+' is not allowed' in str(e.value)
    assert '[' not in str(e.value)
""",
    "provided-full-version": """from packaging.markers import Marker
import pytest
@pytest.mark.parametrize('version',['3.11.1+','3.10.0+'])
def test_provided_version(version): assert Marker("python_full_version < '3.12'").evaluate({'python_full_version':version})
def test_valid_version(): assert Marker("python_full_version >= '3.12'").evaluate({'python_full_version':'3.12.1'})
""",
    "platform-full-version": """from packaging.markers import Marker
from unittest.mock import patch
import pytest
@pytest.mark.parametrize('version',['3.11.1+','3.10.0+'])
def test_default_version(version):
    with patch('platform.python_version',return_value=version): assert Marker("python_full_version < '3.12'").evaluate()
""",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    manifest = []
    for repository, revision, name, description, regression in TASKS:
        repo = ROOT / "data/corpora" / repository
        commit = git(repo, "rev-parse", revision).decode().strip()
        parent = git(repo, "rev-parse", revision + "^").decode().strip()
        task = OUT / name
        task.mkdir()
        workspace = task / "base"
        workspace.mkdir()
        raw = git(repo, "archive", parent)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(workspace, filter="data")
        # Detached input snapshot: no future Git history or remote access in tasks.
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "-c",
                "user.name=CAMI benchmark",
                "-c",
                "user.email=benchmark@example.invalid",
                "commit",
                "-qm",
                "Canonical task input",
            ],
            check=True,
        )
        prompt = (
            description
            + "\n\nImplement the source change and run relevant local tests. Preserve unrelated behavior. Work only in this repository."
        )
        (task / "prompt.txt").write_text(prompt)
        evaluator = task / "evaluation"
        evaluator.mkdir()
        (evaluator / "test_acceptance.py").write_text(ACCEPT[name])
        # Full fixed upstream module from corrected revision, withheld from model.
        regression_raw = git(repo, "show", f"{commit}:tests/{regression}")
        (evaluator / "test_regression.py").write_bytes(regression_raw)
        if repository == "click":
            (evaluator / "conftest.py").write_bytes(
                git(repo, "show", f"{commit}:tests/conftest.py")
            )
        if repository == "requests":
            (evaluator / "__init__.py").write_text("")
            (evaluator / "compat.py").write_bytes(git(repo, "show", f"{commit}:tests/compat.py"))
        if repository.startswith("packaging"):
            (evaluator / "__init__.py").write_text("")
            if name == "iterable-specifiers":
                (evaluator / "test_version.py").write_bytes(
                    git(repo, "show", f"{commit}:tests/test_version.py")
                )
            if name == "dynamic-field-error":
                metadata_archive = git(repo, "archive", commit, "tests/metadata")
                with tarfile.open(fileobj=io.BytesIO(metadata_archive)) as archive:
                    for item in archive:
                        if item.isfile():
                            target = evaluator / Path(item.name).relative_to("tests")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(archive.extractfile(item).read())
        source_patch = git(repo, "diff", parent, commit, "--", "src")
        (task / "gold.patch").write_bytes(source_patch)
        manifest.append(
            {
                "id": name,
                "repository": repository,
                "parent": parent,
                "gold": commit,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "gold_patch_sha256": hashlib.sha256(source_patch).hexdigest(),
                "regression_module": regression,
                "evaluator_files": {
                    str(p.relative_to(evaluator)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in evaluator.rglob("*")
                    if p.is_file()
                },
                "source_root": "src",
                "package": "packaging" if repository.startswith("packaging") else repository,
            }
        )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {len(manifest)} tasks at {OUT}")


if __name__ == "__main__":
    main()
