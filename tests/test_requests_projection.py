import pytest

from cami.errors import InputError, ResourceError
from cami.repository import Blob, Snapshot, materialize
from scripts.check_requests_projection import project


def test_projection_preserves_package_bytes_and_unsupported_entries(tmp_path):
    source = Blob('src/requests/utils.py', 'one', '100644', b'# frozen\xff', None)
    link = Blob('src/requests/link', 'two', '120000', None, 'symlink_unsupported')
    certificate = Blob('tests/certs/link', 'three', '120000', None, 'symlink_unsupported')
    unrelated = Blob('requests_other/file.py', 'four', '100644', b'other', None)
    original = Snapshot('requests', 'parent', (source, link, certificate, unrelated))
    projected = project(original, ('requests/', 'src/requests/'))
    assert projected == Snapshot('requests', 'parent', (source, link))
    assert original.blobs == (source, link, certificate, unrelated)
    with pytest.raises(ResourceError, match='symlink_unsupported'):
        materialize(projected, tmp_path / 'materialized')
    assert (tmp_path / 'materialized/src/requests/utils.py').read_bytes() == b'# frozen\xff'


def test_projection_rejects_missing_package_and_ambiguous_prefix():
    original = Snapshot('requests', 'parent', ())
    with pytest.raises(InputError, match='no package blobs'):
        project(original, ('requests/',))
    with pytest.raises(InputError, match='must end in /'):
        project(original, ('requests',))
