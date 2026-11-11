"""Execute actual Windows x64 hooks in a disposable Python, never in QMT."""
import os
from pathlib import Path
import struct
import sys

import pytest

from cfquant.qmt_vm_worker import agent_source
from cfquant.qmt_vm_settings import normalize_qmt_vm_settings


@pytest.mark.skipif(os.name != 'nt' or struct.calcsize('P') != 8, reason='Windows x64 native hooks')
def test_native_hooks_and_mac_buffers():
    frida = pytest.importorskip('frida')
    source = agent_source(normalize_qmt_vm_settings({
        'disable_vm': True, 'inject_mac': True, 'mac_address': '02-11-22-33-44-55'}))
    source += '\n' + Path(__file__).with_name('qmt_vm_native_fixture.js').read_text(encoding='utf-8')
    device = frida.get_local_device()
    pid = device.spawn([sys.executable, '-c', 'import time; time.sleep(60)'], stdio='pipe')
    session = None
    messages = []
    try:
        session = device.attach(pid)
        script = session.create_script(source)
        script.on('message', lambda message, data: messages.append(message))
        script.load()
        vm = script.exports_sync.selftest()
        mac = script.exports_sync.mactest()
        assert vm['native_hook_install'] and vm['memory_mismatch_rejected_before_hooking']
        assert vm['unhook_restores_original'] and vm['login_config_unchanged']
        assert all(mac.values()), mac
        assert not [m for m in messages if m.get('type') == 'error']
        script.unload()
    finally:
        if session is not None:
            session.detach()
        try:
            device.kill(pid)
        except frida.ProcessNotFoundError:
            pass
