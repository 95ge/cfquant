"""Remote version checks must never open an interactive Git credential UI."""

import json
from types import SimpleNamespace


def test_public_github_check_uses_https_api_without_git(monkeypatch):
    from cfquant import runtime_services as web

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return json.dumps({"sha": "abcdef1234567890"}).encode("utf-8")

    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(web.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(
        web.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("git must not run when GitHub API succeeds")),
    )

    result = web.CfquantUpdater(None)._github_remote_version_info(
        "https://github.com/95ge/cfquant.git",
        "main",
        123.0,
    )

    assert result["source"] == "github_api"
    assert result["commit"] == "abcdef1234567890"
    assert requests[0][0].full_url == "https://api.github.com/repos/95ge/cfquant/commits/main"


def test_git_fallback_disables_terminal_and_gui_prompts(monkeypatch):
    from cfquant import runtime_services as web

    monkeypatch.setattr(web.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="abcdef1234567890\trefs/heads/main\n",
            stderr="",
        )

    monkeypatch.setattr(web.subprocess, "run", run)
    result = web.CfquantUpdater(None)._github_remote_version_info(
        "https://git.example.invalid/cfquant.git",
        "main",
        123.0,
    )

    assert result["commit"] == "abcdef1234567890"
    assert len(calls) == 1
    kwargs = calls[0][1]
    assert kwargs["stdin"] is web.subprocess.DEVNULL
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["env"]["GCM_INTERACTIVE"] == "Never"
    assert kwargs["env"]["GCM_GUI_PROMPT"] == "0"
    assert kwargs["env"]["GIT_ASKPASS"] == ""
