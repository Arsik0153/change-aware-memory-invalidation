import json

import pytest
from pydantic import ValidationError

from cami.artifacts import parse
from cami.models import Claim, RunConfig, safe_path


def test_strict_claim():
    row = dict(schema_version=1, claim_id="c", repo_id="r", origin_commit="abc",
               kind="symbol_exists", text="f exists", scope="exact",
               subject=dict(path="a.py", qualname="f", node_kind="function"),
               predicate=dict(type="symbol_exists", expected=True))
    assert Claim.model_validate_json(json.dumps(row)).claim_id == "c"
    for update in ({"labels": []}, {"schema_version": "1"}, {"kind": "prose"}):
        with pytest.raises(ValidationError):
            Claim.model_validate_json(json.dumps(row | update))


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_reject_invalid_json(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize("path", ["../x", "/tmp/x", "a/../../x", "a\\x", "a//x"])
def test_paths(path):
    with pytest.raises(ValueError):
        safe_path(path)


@pytest.mark.parametrize("path", [".", "a.py", "src/a.py", "α/日本語.py", "a..b",
                                 "a/..b", "a b/c", "a" * 512, "a" * 513,
                                 "a/" * 300 + "b"])
def test_repeated_valid_paths_preserve_input(path):
    for _ in range(2):
        assert safe_path(path) is path


@pytest.mark.parametrize("path,kind", [
    ("", "unsafe"), ("/a", "unsafe"), ("//a", "unsafe"), ("..", "unsafe"),
    ("a/../b", "unsafe"), ("a\\b", "unsafe"), ("a\x00b", "unsafe"),
    ("a//b", "noncanonical"), ("a/", "noncanonical"), ("./a", "noncanonical"),
    ("a/./b", "noncanonical"), ("a" * 513 + "/../b", "unsafe"),
    ("a" * 513 + "//b", "noncanonical"),
])
def test_repeated_invalid_paths_keep_error_contract(path, kind):
    for _ in range(2):
        with pytest.raises(ValueError) as error:
            safe_path(path)
        assert str(error.value) == f"{kind} repository path: {path!r}"


def test_unhashable_string_subclass_keeps_validation_and_identity():
    class PathText(str):
        __hash__ = None

    path = PathText("src/a.py")
    assert safe_path(path) is path
    with pytest.raises(ValueError, match="unsafe repository path"):
        safe_path(PathText("../a"))


def test_run_schema_has_no_labels():
    assert "labels" not in RunConfig.model_fields


def test_literal_boolean_is_not_integer():
    from cami.models import Exists, Record
    with pytest.raises(ValidationError):
        Exists.model_validate_json('{"type":"symbol_exists","expected":1}')
    with pytest.raises(ValidationError):
        Record.model_validate_json('{"schema_version":true}')
