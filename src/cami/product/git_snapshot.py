"""Read product inputs from Git objects, independently of dirty checkout files."""

from pathlib import Path

from cami.errors import InputError
from cami.models import safe_path
from cami.product.inputs import code_input, configuration_inputs, excluded, within
from cami.repository import MAX_FILE_BYTES, Blob, Snapshot, git, resolve


def read_product_snapshot(root: Path, revision: str,
                          source_roots: tuple[str, ...] | None) -> Snapshot:
    oid = resolve(root, revision)
    roots = source_roots or (".",)
    available: dict[str, tuple[str, str, str, int]] = {}
    for entry in git(root, "ls-tree", "-rzl", "--full-tree", oid).split(b"\0"):
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        try:
            path = safe_path(raw_path.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise InputError("Git contains an unsupported path") from error
        mode, kind, blob_id, size = info.decode().split()
        available[path] = (mode, kind, blob_id, int(size) if size != "-" else 0)
    blobs: dict[str, Blob] = {}

    def read(path: str) -> bytes | None:
        mode, kind, blob_id, size = available[path]
        limitation = ("submodule_unsupported" if kind == "commit" else
                      "symlink_unsupported" if mode == "120000" else
                      "file_too_large" if size > MAX_FILE_BYTES else None)
        content = git(root, "cat-file", "blob", blob_id) if limitation is None else None
        if content is not None and content.startswith(b"version https://git-lfs.github.com/spec/v1"):
            limitation, content = "lfs_unsupported", None
        blobs[path] = Blob(path, blob_id, mode, content, limitation)
        return content

    sources = sorted(path for path, (mode, kind, _, _) in available.items()
                     if not excluded(path) and (code_input(path, roots)
                     or ((kind == "commit" or (mode == "120000" and not path.endswith(".json")))
                         and any(within(path, root) or within(root, path) for root in roots))))
    for path in sources:
        read(path)
    configuration_inputs(sources, available.__contains__, read)
    return Snapshot("symbol-search", oid, tuple(blobs[path] for path in sorted(blobs)))
