from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from cami.errors import InputError

T = TypeVar("T", bound=BaseModel)


def canonical(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise InputError(f"invalid JSON number: {value}")


def parse(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


def read_json(path: Path) -> Any:
    return parse(path.read_text(encoding="utf-8"))


def load(path: Path, model: type[T]) -> T:
    return model.model_validate_json(canonical(read_json(path)))


def read_jsonl(path: Path) -> list[Any]:
    return [parse(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_jsonl(path: Path, model: type[T], unique: str | None = None) -> tuple[T, ...]:
    records = tuple(model.model_validate_json(canonical(row)) for row in read_jsonl(path))
    if unique:
        ids = [getattr(row, unique) for row in records]
        if len(ids) != len(set(ids)):
            raise InputError(f"duplicate {unique} in {path}")
    return records


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, data: Any) -> None:
    write_bytes(path, canonical(data) + b"\n")


def write_jsonl(path: Path, rows: Any) -> None:
    write_bytes(path, b"".join(canonical(row) + b"\n" for row in rows))


def reserve(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InputError(f"output already exists: {path}") from exc


def within(base: Path, relative: str) -> Path:
    from cami.models import safe_path
    safe_path(relative)
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise InputError(f"path escapes input directory: {relative}")
    return path


def write_immutable(path: Path, value: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".cache-pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
            return True
        except FileExistsError:
            return False
    finally:
        os.unlink(name)
