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


def test_run_schema_has_no_labels():
    assert "labels" not in RunConfig.model_fields


def test_literal_boolean_is_not_integer():
    from cami.models import Exists, Record
    with pytest.raises(ValidationError):
        Exists.model_validate_json('{"type":"symbol_exists","expected":1}')
    with pytest.raises(ValidationError):
        Record.model_validate_json('{"schema_version":true}')
