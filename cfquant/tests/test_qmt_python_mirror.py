"""Source routing, byte integrity and cancellation without contacting live QMT."""
from dataclasses import replace
import hashlib
import http.client
import io
import json
import threading
import urllib.error

import pytest

from cfquant import qmt_python_runtime as runtime

DATA = b'QMT test runtime archive' * 100


class Response(io.BytesIO):
    def __init__(self, data=DATA, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {'Content-Length': str(len(data))}

    def getcode(self):
        return self.status


@pytest.fixture
def setup(tmp_path, monkeypatch):
    manager = runtime.QmtPythonRuntime(tmp_path)
    package = runtime.QmtPythonPackage('py312', '2.0.3.12', 'http://xuntou.test/runtime.zip',
                                       'runtime.zip', hashlib.md5(DATA).hexdigest(), True,
                                       hashlib.sha256(DATA).hexdigest(), len(DATA))
    snapshot = dict(ok=True, schema=1, busy=False, packages={'py312': package.as_dict()})
    monkeypatch.setattr(manager, '_mirror_status', lambda: snapshot)
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs.get('headers', {})))
        return Response()
    monkeypatch.setattr(manager, '_request', request)
    return manager, package, snapshot, calls


def test_mirror_first_and_verified_cache_needs_no_network(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    assert manager.fetch_package() == package
    assert manager.download(package=package).read_bytes() == DATA
    assert calls[0][0].startswith(runtime._MIRROR_BASE)
    assert calls[0][1][runtime._MIRROR_KEY_HEADER] == runtime._MIRROR_KEY
    monkeypatch.setattr(manager, '_mirror_status', lambda: pytest.fail('cached file should work offline'))
    manager.download(package=package)
    assert len(calls) == 1


def test_busy_uses_upstream_without_mirror_auth_header(setup):
    manager, package, snapshot, calls = setup
    snapshot['busy'] = True
    manager.download(package=package)
    assert calls == [(package.url, {'Accept-Encoding': 'identity'})]


@pytest.mark.parametrize('busy', [True, False])
def test_upstream_failure_forces_website_even_when_busy(setup, monkeypatch, busy):
    manager, package, snapshot, calls = setup
    snapshot['busy'] = busy
    def request(url, **kwargs):
        calls.append(url)
        if 'force=1' not in url:
            raise urllib.error.URLError('offline')
        return Response()
    monkeypatch.setattr(manager, '_request', request)
    assert manager.download(package=package).read_bytes() == DATA
    assert calls[-1].endswith('&force=1')
    assert calls[-2] == package.url
    assert len(calls) == (2 if busy else 3)


def test_unavailable_status_still_attempts_direct_forced_download(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    monkeypatch.setattr(manager, '_mirror_status', lambda: None)
    def request(url, **kwargs):
        calls.append(url)
        if url == package.url:
            raise TimeoutError('timeout')
        return Response()
    monkeypatch.setattr(manager, '_request', request)
    manager.download(package=package)
    assert len(calls) == 2 and calls[-1].endswith('&force=1')


def test_corrupt_download_is_discarded_before_fallback(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    def request(url, **kwargs):
        calls.append((url, kwargs['headers']))
        return Response(b'x' * len(DATA)) if len(calls) == 1 else Response()
    monkeypatch.setattr(manager, '_request', request)
    assert manager.download(package=package).read_bytes() == DATA
    assert calls[-1][0] == package.url and 'Range' not in calls[-1][1]


def test_truncated_response_resumes_at_other_source(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    def request(url, **kwargs):
        calls.append((url, kwargs['headers']))
        if len(calls) == 1:
            return Response(DATA[:100], headers={'Content-Length': str(len(DATA))})
        assert kwargs['headers']['Range'] == 'bytes=100-'
        return Response(DATA[100:], status=206,
                        headers={'Content-Range': 'bytes 100-%d/%d' % (len(DATA)-1, len(DATA))})
    monkeypatch.setattr(manager, '_request', request)
    assert manager.download(package=package).read_bytes() == DATA
    assert len(calls) == 2


def test_incorrect_range_cannot_be_appended(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    def request(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return Response(DATA[:100], headers={'Content-Length': str(len(DATA))})
        if len(calls) == 2:
            return Response(DATA, status=206, headers={'Content-Range': 'bytes 0-%d/%d' % (len(DATA)-1, len(DATA))})
        return Response()  # A server may ignore Range and send a complete 200.
    monkeypatch.setattr(manager, '_request', request)
    assert manager.download(package=package).read_bytes() == DATA
    assert len(calls) == 3


def test_sha256_failure_cannot_be_installed(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    package = replace(package, sha256='0' * 64)
    with pytest.raises(runtime.QmtPythonRuntimeError, match='SHA-256 mismatch'):
        manager.download(package=package)
    assert len(calls) == 3
    assert not (manager.download_dir / package.filename).exists()


def test_cancel_does_not_fall_back(setup):
    manager, package, snapshot, calls = setup
    cancel = threading.Event()
    def progress(event):
        if event['bytes_done']:
            cancel.set()
    with pytest.raises(runtime.QmtPythonRuntimeError, match='cancelled'):
        manager.download(package=package, cancel_event=cancel, progress_callback=progress)
    assert len(calls) == 1


def test_local_write_failure_does_not_fall_back(setup, monkeypatch):
    manager, package, snapshot, calls = setup
    monkeypatch.setattr(runtime.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        manager.download(package=package)
    assert len(calls) == 1


def test_config_fallback_and_status_timeout_cache(tmp_path, monkeypatch):
    manager = runtime.QmtPythonRuntime(tmp_path)
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url.startswith(runtime._MIRROR_BASE):
            raise TimeoutError('offline')
        return Response(b'[python]\nversion=2.0.3.12\nurl=http://xuntou.test/runtime.zip\nfilename=runtime.zip\nmd5=' + b'1'*32)
    monkeypatch.setattr(manager, '_request', request)
    assert manager.fetch_package().md5 == '1'*32
    assert manager.fetch_package().md5 == '1'*32
    assert len(calls) == 3
    assert calls[0][1]['timeout'] == 5
    assert 'headers' not in calls[-1][1]


def test_manifest_version_mismatch_never_uses_normal_mirror(setup):
    manager, package, snapshot, calls = setup
    snapshot['packages']['py312']['md5'] = '0'*32
    manager.download(package=package)
    assert calls[0][0] == package.url


def test_key_is_not_forwarded_on_redirect():
    handler = runtime._NoMirrorRedirect()
    assert handler.redirect_request(None, None, 302, '', {}, 'https://third-party.test') is None
