"""Version checks can refresh releases without waiting for QMT channels."""

import json
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from cfquant.tests.test_management import service


@pytest.mark.parametrize("query, remote_force, probe_count", [
    ("remote=1&force=1&probe_qmt=0", True, 0),
    ("remote=1&force_remote=1&probe_qmt=0", True, 0),
    ("remote=0&probe_qmt=1", None, 1),
    ("remote=0&force=1", None, 1),  # Existing clients retain their behaviour.
    ("remote=0&force=1&qmt=0", None, 0),
    ("remote=0", None, 0),
])
def test_version_http_separates_release_refresh_and_qmt_probe(service, monkeypatch, query, remote_force, probe_count):
    web = service.web
    probes, releases = [], []
    saved = {"version": "1.0.0", "reported": False, "has_report": True}
    live = {"version": "1.1.0", "reported": True, "has_report": True}
    monkeypatch.setattr(web, "read_qmt_runtime_marker_reports", lambda *a: None)
    monkeypatch.setattr(web, "RUNTIME_VERSIONS", SimpleNamespace(latest=lambda *a: dict(saved)))
    monkeypatch.setattr(web, "refresh_runtime_version_report",
                        lambda *a, **kw: probes.append((a, kw)) or dict(live))
    monkeypatch.setattr(web, "_local_project_version_info", lambda: {"version": "1.0.0"})
    monkeypatch.setattr(web, "_remote_project_version_info",
                        lambda **kw: releases.append(kw) or {"version": "2.0.0"})
    request = Request(service.runtime.base_url + "/api/version?bridge_id=test&" + query,
                      headers={"X-CFQuant-Management-Key": "test-management-key"})
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)
    assert payload["ok"]
    data = payload["data"]
    assert len(probes) == probe_count
    assert data["qmt_runtime"]["version"] == ("1.1.0" if probe_count else "1.0.0")
    assert data["bridge_id"] == "test"
    if remote_force is None:
        assert not releases
        assert data["remote"] is None
    else:
        assert releases[0]["force"] is remote_force
        assert data["comparison"] == "newer"


def test_failed_release_cache_recovers_sooner_than_successful_cache(monkeypatch):
    from cfquant import runtime_services as web

    cache, calls = {}, []
    monkeypatch.setattr(web, "_PROJECT_VERSION_CACHE", cache)
    monkeypatch.setattr(web, "UPDATE_REMOTE_CACHE_SECONDS", 300)

    def offline(*args, **kwargs):
        calls.append("offline")
        raise OSError("test offline")

    monkeypatch.setattr(web, "official_release_info", offline)
    monkeypatch.setattr(web.urllib.request, "urlopen", offline)
    assert web._remote_project_version_info()["error"]
    count = len(calls)
    assert web._remote_project_version_info()["cached"]
    assert len(calls) == count
    next(iter(cache.values()))["checked_at"] -= 16
    monkeypatch.setattr(web, "official_release_info", lambda *a: calls.append("online") or {"version": "2.0.0"})
    assert web._remote_project_version_info()["version"] == "2.0.0"
    assert calls[-1] == "online"
    count = len(calls)
    next(iter(cache.values()))["checked_at"] -= 60
    assert web._remote_project_version_info()["cached"]
    assert len(calls) == count
    assert not web._remote_project_version_info(force=True)["cached"]
    assert len(calls) == count + 1
