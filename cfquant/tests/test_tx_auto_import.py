import json

import cfquant.tx as tx_module


def test_tx_auto_import_missing_orjson_uses_sys_print_alias(monkeypatch):
    client = tx_module.txl.__new__(tx_module.txl)
    client.orjson_on = None
    messages = []
    client.sys_print = lambda data, show_force=False: messages.append(data)

    def fake_import_module(name):
        raise ImportError(name)

    monkeypatch.setattr(tx_module.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        tx_module.subprocess,
        "check_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pip failed")),
    )

    assert client.auto_import("orjson") is json
    assert client.orjson_on is False
    assert len(messages) == 2
    assert "缺少依赖 orjson" in messages[0]
    assert "自动安装orjson模块失败" in messages[1]
