"""Change detection in 04_tools/07_upload_pdfs_to_buckets.py.

The uploader must re-send an object whose bytes changed under an unchanged
key, because keys here are registration numbers / source-URL hashes, not
content hashes. Skipping on mere existence would pin a stale EPD forever.
"""
import hashlib
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "uploader", _ROOT / "04_tools" / "07_upload_pdfs_to_buckets.py"
)
up = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(up)


@pytest.fixture
def local_pdf(tmp_path):
    p = tmp_path / "EPD-IT-0001.pdf"
    p.write_bytes(b"x" * 500)
    return p


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


# ── the size test (default behaviour) ────────────────────────────────────────

def test_same_size_is_skipped(local_pdf):
    assert up._needs_upload(local_pdf, 500, None, checksum=False) is None


def test_changed_size_is_resent(local_pdf):
    reason = up._needs_upload(local_pdf, 480, None, checksum=False)
    assert reason is not None and "480 -> 500" in reason


def test_missing_remote_size_is_skipped(local_pdf):
    """A provider that advertises no Content-Length must not trigger a re-send
    of all 1.24 GB on every routine run."""
    assert up._needs_upload(local_pdf, None, None, checksum=False) is None


# ── the checksum test (--checksum) ───────────────────────────────────────────

def test_checksum_catches_same_size_edit(local_pdf):
    """The case size cannot see: identical length, different bytes."""
    other = _md5(b"y" * 500)
    reason = up._needs_upload(local_pdf, 500, f'"{other}"', checksum=True)
    assert reason == "checksum differs"


def test_checksum_match_is_skipped(local_pdf):
    same = _md5(b"x" * 500)
    assert up._needs_upload(local_pdf, 500, f'"{same}"', checksum=True) is None


def test_multipart_etag_is_not_compared(local_pdf):
    """A multipart ETag is <md5>-<parts> and is not a whole-file digest, so
    comparing it would re-upload every large object on every run."""
    assert up._needs_upload(local_pdf, 500, '"abc123-4"', checksum=True) is None


def test_checksum_not_read_when_size_already_differs(local_pdf, monkeypatch):
    """Size short-circuits, so a changed file is never hashed needlessly."""
    monkeypatch.setattr(up, "_local_md5", lambda p: pytest.fail("hashed unnecessarily"))
    assert up._needs_upload(local_pdf, 1, None, checksum=True) is not None


# ── end to end through upload_to_r2 with a stub client ───────────────────────

class _StubR2:
    def __init__(self, remote, bucket_error=None):
        self.remote = remote          # {key: (size, etag)}
        self.uploaded = []
        self.bucket_error = bucket_error

    def head_bucket(self, Bucket):
        if self.bucket_error:
            raise self.bucket_error
        return {}

    def head_object(self, Bucket, Key):
        if Key not in self.remote:
            raise RuntimeError("404")
        size, etag = self.remote[Key]
        out = {"ETag": etag} if etag else {}
        if size is not None:
            out["ContentLength"] = size
        return out

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploaded.append(key)


def _run(monkeypatch, tmp_path, remote, force=False, checksum=False):
    stub = _StubR2(remote)
    monkeypatch.setattr(up, "_r2_client", lambda secrets: (stub, "epd-documents", "https://pub.r2.dev"))
    unchanged = tmp_path / "unchanged.pdf"; unchanged.write_bytes(b"a" * 100)
    revised = tmp_path / "revised.pdf";     revised.write_bytes(b"b" * 300)
    brand_new = tmp_path / "new.pdf";       brand_new.write_bytes(b"c" * 50)
    items = [(unchanged, "unchanged.pdf"), (revised, "revised.pdf"), (brand_new, "new.pdf")]
    up.upload_to_r2({}, items, force, False, 604800, checksum)
    return stub


def test_end_to_end_sends_only_the_revised_and_the_new(monkeypatch, tmp_path):
    stub = _run(monkeypatch, tmp_path, {
        "unchanged.pdf": (100, None),
        "revised.pdf": (299, None),   # an EPD re-issued under the same number
    })
    assert sorted(stub.uploaded) == ["new.pdf", "revised.pdf"]


def test_force_sends_everything(monkeypatch, tmp_path):
    stub = _run(monkeypatch, tmp_path, {
        "unchanged.pdf": (100, None),
        "revised.pdf": (299, None),
    }, force=True)
    assert sorted(stub.uploaded) == ["new.pdf", "revised.pdf", "unchanged.pdf"]


def test_old_behaviour_would_have_missed_the_revision(monkeypatch, tmp_path):
    """Regression guard: existence-only skipping leaves the stale bytes."""
    stub = _run(monkeypatch, tmp_path, {
        "unchanged.pdf": (100, None),
        "revised.pdf": (299, None),
    })
    assert "revised.pdf" in stub.uploaded, "a same-key revision must be re-sent"


# ── root resolution: a git checkout carries no assets and no secrets ─────────

def test_root_defaults_to_the_scripts_app_folder(monkeypatch):
    monkeypatch.delenv(up._ENV_ROOT, raising=False)
    assert up._resolve_root(None) == _ROOT


def test_cli_root_wins_over_env(tmp_path, monkeypatch):
    other = tmp_path / "other"; other.mkdir()
    monkeypatch.setenv(up._ENV_ROOT, str(tmp_path))
    assert up._resolve_root(str(other)) == other.resolve()


def test_env_root_used_when_no_cli_root(tmp_path, monkeypatch):
    monkeypatch.setenv(up._ENV_ROOT, str(tmp_path))
    assert up._resolve_root(None) == tmp_path.resolve()


def test_nonexistent_root_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        up._resolve_root(str(tmp_path / "nope"))
    assert "not a directory" in str(exc.value)


def test_set_root_redirects_assets_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "_ROOT", up._ROOT)
    up._set_root(tmp_path)
    try:
        assert up._PDF_DIR == (tmp_path / "01_data" / "pdf").resolve()
        assert up._IMG_DIR == (tmp_path / "01_data" / "img").resolve()
        assert up._SECRETS_PATH == (tmp_path / ".streamlit" / "secrets.toml").resolve()
    finally:
        up._set_root(_ROOT)


def test_checkout_hint_names_the_cause(tmp_path):
    """The bare 'No such directory' gave no clue why; the hint must name
    .gitignore and point at --root."""
    (tmp_path / ".git").mkdir()
    up._set_root(tmp_path)
    try:
        msg = up._missing_dir_hint(up._PDF_DIR)
    finally:
        up._set_root(_ROOT)
    assert "git checkout" in msg
    assert "--root" in msg
    assert up._ENV_ROOT in msg


def test_collect_exits_with_the_hint_not_a_bare_path(tmp_path):
    up._set_root(tmp_path)
    try:
        with pytest.raises(SystemExit) as exc:
            up._collect("docs")
        assert "--root" in str(exc.value)
    finally:
        up._set_root(_ROOT)


# ── auth failure must not look like "nothing uploaded yet" ──────────────────

def _client_error(code, status=403):
    """A botocore-shaped exception without requiring botocore in the test."""
    exc = Exception(code)
    exc.response = {"Error": {"Code": code},
                    "ResponseMetadata": {"HTTPStatusCode": status}}
    return exc


def test_error_code_read_from_error_block():
    assert up._s3_error_code(_client_error("AccessDenied")) == "AccessDenied"


def test_error_code_falls_back_to_http_status():
    exc = Exception("x")
    exc.response = {"ResponseMetadata": {"HTTPStatusCode": 404}}
    assert up._s3_error_code(exc) == "404"


def test_error_code_of_plain_exception_is_blank():
    assert up._s3_error_code(RuntimeError("boom")) == ""


@pytest.mark.parametrize("code", ["InvalidAccessKeyId", "SignatureDoesNotMatch",
                                  "AccessDenied", "NoSuchBucket", "403"])
def test_preflight_exits_on_credential_errors(code):
    stub = _StubR2({}, bucket_error=_client_error(code))
    with pytest.raises(SystemExit) as exc:
        up._r2_preflight(stub, "eetra-mat-lib")
    assert code in str(exc.value)


def test_preflight_passes_on_a_good_bucket():
    up._r2_preflight(_StubR2({}), "eetra-mat-lib")   # must not raise


def test_bad_credentials_abort_instead_of_uploading_everything(monkeypatch, tmp_path):
    """The regression that matters: a wrong key must not be reported as an
    empty bucket with 1,456 objects 'to upload'."""
    stub = _StubR2({}, bucket_error=_client_error("InvalidAccessKeyId"))
    monkeypatch.setattr(up, "_r2_client", lambda s: (stub, "eetra-mat-lib", "https://pub.r2.dev"))
    f = tmp_path / "a.pdf"; f.write_bytes(b"x" * 10)
    with pytest.raises(SystemExit):
        up.upload_to_r2({}, [(f, "a.pdf")], False, True, 604800, False)
    assert stub.uploaded == []


def test_per_object_fatal_code_aborts(monkeypatch, tmp_path):
    class _Denies(_StubR2):
        def head_object(self, Bucket, Key):
            raise _client_error("AccessDenied")
    stub = _Denies({})
    monkeypatch.setattr(up, "_r2_client", lambda s: (stub, "b", "https://pub.r2.dev"))
    f = tmp_path / "a.pdf"; f.write_bytes(b"x" * 10)
    with pytest.raises(SystemExit):
        up.upload_to_r2({}, [(f, "a.pdf")], False, False, 604800, False)


def test_absent_object_is_not_fatal(monkeypatch, tmp_path):
    class _Absent(_StubR2):
        def head_object(self, Bucket, Key):
            raise _client_error("404", status=404)
    stub = _Absent({})
    monkeypatch.setattr(up, "_r2_client", lambda s: (stub, "b", "https://pub.r2.dev"))
    f = tmp_path / "a.pdf"; f.write_bytes(b"x" * 10)
    stats = up.upload_to_r2({}, [(f, "a.pdf")], False, False, 604800, False)
    assert stub.uploaded == ["a.pdf"] and stats["uploaded"] == 1


# ── stats bookkeeping feeds the log summary ─────────────────────────────────

def test_stats_count_bytes_actually_sent(monkeypatch, tmp_path):
    stub = _StubR2({"unchanged.pdf": (100, None)})
    monkeypatch.setattr(up, "_r2_client", lambda s: (stub, "b", "https://pub.r2.dev"))
    unchanged = tmp_path / "unchanged.pdf"; unchanged.write_bytes(b"a" * 100)
    fresh = tmp_path / "new.pdf"; fresh.write_bytes(b"c" * 50)
    stats = up.upload_to_r2({}, [(unchanged, "unchanged.pdf"), (fresh, "new.pdf")],
                            False, False, 604800, False)
    assert stats["skipped"] == 1
    assert stats["uploaded"] == 1
    assert stats["bytes"] == 50, "skipped bytes must not be counted as transferred"


def test_merge_stats_adds_counters_and_failures():
    a = up._empty_stats()
    b = {"uploaded": 2, "replaced": 1, "skipped": 3, "failed": 1,
         "bytes": 500, "failures": [("x.pdf", "boom")]}
    up._merge_stats(a, b)
    assert (a["uploaded"], a["replaced"], a["skipped"], a["failed"], a["bytes"]) == (2, 1, 3, 1, 500)
    assert a["failures"] == [("x.pdf", "boom")]


def test_mask_never_reveals_a_whole_identifier():
    assert up._mask("38f77d02a49dc885ae5510e665692c31") == "38f77d...2c31"
    assert up._mask("short") == "***"
