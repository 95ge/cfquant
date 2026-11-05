"""Run the actual Frida agent against synthetic Qt exports; no live QMT."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from cfquant.qmt_component_login import _verify_environment_native


AGENT = Path(__file__).resolve().parents[1] / 'qmt_strategy_agent.js'
HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
let nextId = 1, hook, starts = 0, closes = 0, whitelistChecks = 0;
class Pointer {
  constructor(value = {}, offset = 0, id = nextId++) { this.value = value; this.offset = offset; this.id = id; }
  add(offset) { return new Pointer(this.value, this.offset + offset, this.id); }
  isNull() { return this.value === null; }
  toString() { return String(this.id); }
  readPointer() {
    if (this.value.list) return this.value.list;
    return this.value.items[(this.offset - 16) / 8];
  }
  readS32() { return this.offset === 8 ? 0 : this.value.items.length; }
  readUtf16String() { return this.value.text; }
  writeByteArray() {}
  writeU64() {}
}
const target = {id:'7', name:'CFQ_TEST001_LITE', account:'TEST001', m_strAccountKey:'key',
  runMode:'1', startupAutorun:'1', eStrategyType:'4', stock:'SH000300', peroid:'86400'};
const models = [Object.assign({}, target, {running: options.running !== false})];
const main = new Pointer({types:['TC::CMainWindow'], children:[]});
const text = '[防外接] Python进程访问了网络地址 [192.0.2.1]，策略运行中止！';
const content = new Pointer({types:[options.unqualified ? 'CSimpleTextWidget' : 'XP::CSimpleTextWidget'], text, children:[]});
const container = new Pointer({types:['QWidget'], children:[content]});
const notice = new Pointer({types:['XP::CGlobalMessageDialog'], children:[container]});
if (options.duplicate) notice.value.children.push(new Pointer({types:['XP::CSimpleTextWidget'], text, children:[]}));
if (options.unrelated) content.value.text = 'An unrelated message';
const manager = new Pointer({});
function call(symbol, args) {
  const [a,b,c] = args;
  if (symbol === 'DispatchMessageW') return;
  if (symbol === 'GetWindowThreadProcessId') return 1;
  if (symbol === 'PostMessageW') { setImmediate(() => hook.onLeave.call({threadId:1})); return true; }
  if (symbol.startsWith('?find@QWidget')) return String(a) === '1' ? main : notice;
  if (symbol.startsWith('?inherits@')) return a.value.types.includes(b.value.text);
  if (symbol.startsWith('?isVisible@')) return a.value.visible !== false;
  if (symbol.startsWith('??0QString')) { a.value.text = b.value.text; return a; }
  if (symbol.startsWith('??1QString')) return;
  if (symbol.startsWith('?size@QString')) return a.value.text.length;
  if (symbol.startsWith('?utf16@QString')) return a;
  if (symbol.startsWith('?instance@')) return manager;
  if (symbol.startsWith('?saveSettings@')) { b.value.models = models; return; }
  if (symbol.startsWith('?isFomrulaRun@')) return models.some(row => row.name === b.value.text && row.running);
  if (symbol.startsWith('?isConnWhiteListReady@')) { whitelistChecks++; return options.whitelist !== false; }
  if (symbol.startsWith('?runStrategy@')) { starts++; return; }
  if (symbol.startsWith('??0QDomDocument') || symbol.startsWith('??1QDomDocument') || symbol.startsWith('??1QDomElement')) return;
  if (symbol.startsWith('?createElement@')) return b;
  if (symbol.startsWith('?firstChildElement@')) { b.value.models = a.value.models; b.value.index = 0; return b; }
  if (symbol.startsWith('?nextSiblingElement@')) { b.value.models = a.value.models; b.value.index = a.value.index + 1; return b; }
  if (symbol.startsWith('?isNull@QDomNode')) return a.value.index >= a.value.models.length;
  if (symbol.startsWith('?attribute@')) { b.value.text = a.value.models[a.value.index][c.value.text]; return b; }
  if (symbol.startsWith('?children@')) return new Pointer({list:new Pointer({items:a.value.children})});
  if (symbol.startsWith('?getText@')) { b.value.text = a.value.text; return b; }
  if (symbol.startsWith('?closeMessage@')) { closes++; notice.value.visible = false; return; }
  throw new Error('Unimplemented test native call: ' + symbol);
}
const context = {
  Process: {arch:'x64', pointerSize:8, findModuleByName: name => {
    if ((options.missingModules || []).includes(name)) return null;
    return {findExportByName: symbol => (options.missing || []).some(prefix => symbol.startsWith(prefix)) ? null : symbol};
  }},
  NativeFunction: function(symbol) { return (...args) => call(symbol, args); },
  Memory: {alloc: () => new Pointer(), allocUtf8String: text => new Pointer({text}), allocUtf16String: text => new Pointer({text})},
  Interceptor: {attach: (address, callbacks) => { hook = callbacks; }},
  rpc: {exports:{}}, uint64: value => value, ptr: value => value, NULL:null, setTimeout, clearTimeout
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(options.agent, 'utf8'), context);
(async () => {
  const api = context.rpc.exports, result = {capabilities:api.strategycapabilities()};
  if (result.capabilities.can_query) {
    result.snapshot = (await api.strategystatus('1')).result;
    if (options.tryStart) result.start = (await api.strategystart('1', Object.assign({}, target, options.expected || {}))).result;
    if (options.notice) {
      result.notice = (await api.illegalipnotice('2')).result;
      if (result.notice) {
        if (options.changed) content.value.text = text.replace('192.0.2.1','192.0.2.2');
        result.dismiss = (await api.dismissillegalip('1','2',result.notice.text,[target])).result;
      }
    }
  } else {
    try { await api.strategystatus('1'); } catch (error) { result.query_error = error.message; }
  }
  result.starts = starts; result.closes = closes; result.whitelistChecks = whitelistChecks;
  process.stdout.write(JSON.stringify(result));
})().catch(error => { process.stdout.write(JSON.stringify({error:error.message,starts,closes})); });
'''


def run_agent(**options):
    node = shutil.which('node')
    assert node, 'Node is required to validate the actual strategy agent'
    result = subprocess.run([node, '-e', HARNESS], input=json.dumps(dict(options, agent=str(AGENT))),
                            text=True, encoding='utf-8', capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


@pytest.mark.parametrize('missing', [['?isConnWhiteListReady@'], ['?runStrategy@'], ['?getText@'], ['?closeMessage@']])
def test_optional_export_does_not_prevent_query(missing):
    result = run_agent(missing=missing, tryStart=True, running=False)
    assert result['snapshot']['models'][0]['running'] is False
    assert result['capabilities']['can_query']
    if missing[0] == '?runStrategy@':
        assert not result['capabilities']['can_start']
        assert result['start'] == {'outcome': 'detection_only', 'requested': False}
        assert result['starts'] == 0
    if missing[0] == '?isConnWhiteListReady@':
        assert result['snapshot']['whitelist_ready'] is None
        assert result['capabilities']['can_start']
        assert not result['capabilities']['can_check_whitelist']
        assert result['capabilities']['missing_whitelist']
        assert result['capabilities']['missing_start'] == []
        assert result['start'] == {'outcome': 'start_requested', 'requested': True}
        assert result['starts'] == 1 and result['whitelistChecks'] == 0


@pytest.mark.parametrize('module', ['LoginDialog.dll', 'Dialog.dll', 'BaseWidget.dll'])
def test_query_does_not_depend_on_login_or_notice_modules(module):
    result = run_agent(missingModules=[module])
    assert result['snapshot']['models'][0]['running'] is True
    assert result['whitelistChecks'] == 0


def test_missing_core_query_interface_is_explicit():
    result = run_agent(missing=['?isFomrulaRun@'])
    assert not result['capabilities']['can_query']
    assert 'isFomrulaRun' in result['query_error']
    assert result['starts'] == 0


@pytest.mark.parametrize('running,whitelist,outcome,starts', [
    (True, True, 'already_running', 0), (False, False, 'waiting_whitelist', 0),
    (False, True, 'start_requested', 1),
])
def test_supported_start_keeps_native_guards(running, whitelist, outcome, starts):
    result = run_agent(tryStart=True, running=running, whitelist=whitelist)
    assert result['start']['outcome'] == outcome and result['starts'] == starts


@pytest.mark.parametrize('missing', [[], ['?isConnWhiteListReady@']])
def test_start_rejects_changed_binding(missing):
    result = run_agent(missing=missing, tryStart=True, running=False, expected={'account':'WRONG'})
    assert 'binding changed' in result['error'] and result['starts'] == 0


@pytest.mark.parametrize('options,outcome', [({}, 'closed'), ({'unqualified':True}, 'closed'), ({'changed':True}, 'message_changed'),
                                           ({'missing':['?closeMessage@']}, 'notice_close_unavailable')])
def test_notice_uses_nested_widget_types_and_rechecks_text(options, outcome):
    result = run_agent(notice=True, **options)
    assert result['notice']['hwnd'] == '2'
    assert result['dismiss']['outcome'] == outcome
    assert result['closes'] == (1 if outcome == 'closed' else 0)


@pytest.mark.parametrize('options', [{'duplicate':True}, {'unrelated':True}, {'missingModules':['BaseWidget.dll']}])
def test_ambiguous_unrelated_or_unsupported_notice_is_not_closed(options):
    result = run_agent(notice=True, **options)
    assert result['notice'] is None and result['closes'] == 0
    assert result['snapshot']['models'][0]['running'] is True


@pytest.mark.parametrize('qt_version', [(5,6,2), (5,9,9), (5,15,2), (6,5,0)])
def test_strategy_environment_checks_qt_abi_without_exact_version_pin(tmp_path, monkeypatch, qt_version):
    from cfquant import qmt_dependencies
    data = bytearray(128)
    data[0x3c:0x40] = (64).to_bytes(4, 'little')
    data[68:70] = (0x8664).to_bytes(2, 'little')
    (tmp_path / 'XtItClient.exe').write_bytes(data)
    major, minor, patch = qt_version
    api = SimpleNamespace(GetFileVersionInfo=lambda *args: {'FileVersionMS': (major << 16) | minor, 'FileVersionLS': patch << 16})
    monkeypatch.setattr(qmt_dependencies, 'import_login_module', lambda name: api)
    if major == 5:
        _verify_environment_native(tmp_path, strategy=True)
    else:
        with pytest.raises(RuntimeError, match='ABI'):
            _verify_environment_native(tmp_path, strategy=True)
    # Login retains its existing independently validated compatibility policy.
    if qt_version == (5,6,2):
        _verify_environment_native(tmp_path)
    else:
        with pytest.raises(RuntimeError, match='5.6.2'):
            _verify_environment_native(tmp_path)


def test_old_qmt_running_model_is_not_started_again():
    result = run_agent(missing=['?isConnWhiteListReady@'], tryStart=True, running=True)
    assert result['start'] == {'outcome': 'already_running', 'requested': False}
    assert result['starts'] == 0 and result['whitelistChecks'] == 0


def test_missing_start_and_readiness_query_remains_detection_only():
    result = run_agent(missing=['?isConnWhiteListReady@', '?runStrategy@'], tryStart=True, running=False)
    assert result['capabilities']['can_query'] and not result['capabilities']['can_start']
    assert result['start'] == {'outcome': 'detection_only', 'requested': False}
    assert result['starts'] == 0
