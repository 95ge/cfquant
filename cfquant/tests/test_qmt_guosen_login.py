"""Execute the real login selector against broker and button variations."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_custom_exit_dialog_requires_observed_exit_text_and_clears_on_destroy():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise native dialog handling")
    source = Path(__file__).parents[1].joinpath("qmt_component_agent.js").read_text(encoding="utf-8")
    hooks = source[source.index("const exitPrompts"):source.index("function isGuosen()")]
    confirm = source[source.index("  confirmexit("):source.index("  acknowledge(")]
    script = r"""
const assert = require('node:assert/strict');
const callbacks = new Map(), clicks = [];
const Process = {findModuleByName: () => ({findExportByName: name => name})};
const Interceptor = {attach: (name, callback) => callbacks.set(name, callback)};
const stringSize = value => value.length, stringData = value => ({readUtf16String: () => value});
const onGui = (h, operation) => ({result: operation()}), getRoot = h => h;
const uint64 = h => h, findWidget = h => ({isNull: () => h === 'transient', toString: () => h});
const hasType = () => true, ptr = x => x, buttonClick = x => clicks.push(x);
let rows = [{label:'确定',address:'confirm',visible:true,enabled:true}];
const walk = () => rows;
""" + hooks + "const api = {\n" + confirm + "};\n" + r"""
const construct = [...callbacks.entries()].find(([name]) => name.startsWith('??0'))[1];
const destroy = [...callbacks.entries()].find(([name]) => name.startsWith('??1'))[1];
const prompt = '您确认需要退出国信iQuant策略交易平台吗？';
assert.equal(api.confirmexit('transient').result.confirmed, false);
assert.equal(api.confirmexit('dialog').result.confirmed, false);
construct.onEnter(['dialog',null,null,'Title','确认提交股票买入委托？']);
assert.equal(api.confirmexit('dialog').result.confirmed, false);
construct.onEnter(['dialog',null,null,'Title',prompt]);
assert.equal(api.confirmexit('dialog').result.confirmed, true);
assert.deepEqual(clicks,['confirm']);
destroy.onEnter(['dialog']);
assert.equal(api.confirmexit('dialog').result.confirmed, false);
construct.onEnter(['dialog',null,null,'Title',prompt]);
construct.onEnter(['dialog',null,null,'Title','确认登录此账号？']);
assert.equal(api.confirmexit('dialog').result.confirmed, false);
rows.push({...rows[0], address:'duplicate'});
construct.onEnter(['dialog',null,null,'Title',prompt]);
assert.equal(api.confirmexit('dialog').result.confirmed, false);
assert.deepEqual(clicks,['confirm']);
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_native_broker_selector_and_environment_routing():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JavaScript selector")
    source = Path(__file__).parents[1].joinpath("qmt_component_agent.js").read_text(encoding="utf-8")
    selector = source[source.index("function isGuosen()"):source.index("function hasType(")]
    script = r"""
const assert = require('node:assert/strict');
let mode = true, loginEnvironment = 'simulation';
const Process = {findModuleByName: () => ({findExportByName: name =>
  name.startsWith('?getUserConfig') ? 'config' : 'check'})};
function NativeFunction(name) { return name === 'config' ? () => ({isNull: () => false}) : () => mode; }
""" + selector + r"""
const button = label => ({label,visible:true,enabled:true});
const rows = [button('登录实盘'),button('登录仿真')];
assert.equal(loginTarget(rows).button.label,'登录仿真');
loginEnvironment = 'live';
assert.equal(loginTarget(rows).button.label,'登录实盘');
loginEnvironment = null;
assert.equal(loginTarget(rows).button,null);
loginEnvironment = 'simulation';
assert.equal(loginTarget([button('登录实盘')]).button,null);
assert.equal(loginTarget([button('登录仿真'),button('登录仿真')]).button,null);
assert.equal(loginTarget([{...button('登录仿真'),enabled:false}]).button,null);
mode = false; // Other brokers expose the same shared DLL functions.
assert.equal(loginTarget(rows).broker,'generic');
assert.equal(loginTarget(rows).button,null);
assert.equal(loginTarget([button('登录')]).button.label,'登录');
assert.equal(loginTarget([button('登录（3）')]).button.label,'登录（3）');
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_account_login_targets_only_matching_row_and_never_reads_password():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JavaScript account adapter")
    source = Path(__file__).parents[1].joinpath("qmt_component_agent.js").read_text(encoding="utf-8")
    method = source[source.index("  completeaccount("):source.index("  configurelogin(")]
    script = r"""
const assert = require('node:assert/strict');
const accountSubmissions = new Set(), calls = [];
let guosen = true;
const isGuosen = () => guosen, getRoot = () => 'main', hasType = () => true, ptr = x => x;
const onGui = (h, operation) => ({result: operation()});
const Process = {pointerSize:8, getModuleByName: () => ({getExportByName:()=>({readS32:()=>1112})})};
const Memory = {alloc: () => ({text:''})}, stringDtor = () => {}, stringSize = x => x.text.length;
const stringData = x => ({readUtf16String: () => x.text});
const walk = root => root === 'dialog'
  ? [{class_name:'TC::CSettingAccountWidget',address:'widget'}]
  : [{class_name:'XP::IBaseTable',address:'table'}];
// Column IDs deliberately differ from their display positions.
const cols = [[31,'账号类型'],[17,'账号密码'],[42,'账号'],[99,'登录状态']];
let accounts = [
  {id:'other',type:'股票账号',status:'未登录'},
  {id:'target',type:'信用账号',status:'未登录'},
  {id:'target',type:'股票账号',status:'未登录'}
];
function fn(module, symbol) {
  if(symbol.startsWith('?createSettingPage')) return () => 'dialog';
  if(symbol.startsWith('?load@')||symbol.startsWith('?showPage@')) return () => {};
  if(symbol.startsWith('?rowCount')) return () => accounts.length;
  if(symbol.startsWith('?columnCount')) return () => cols.length;
  if(symbol.startsWith('?columnID')) return (p,i) => cols[i][0];
  if(symbol.startsWith('?columnHeader')) return (p,out,id) => {out.text=cols.find(c=>c[0]===id)[1];};
  if(symbol.startsWith('?itemText')) return (p,out,row,col) => {
    assert.notEqual(col,17,'Account passwords must never be read');
    out.text=accounts[row][{31:'type',42:'id',99:'status'}[col]];
  };
  if(symbol.startsWith('?rowID')) return (p,row) => row + 100;
  if(symbol.startsWith('?forceLogin')) return (widget,row) => calls.push(row);
  throw Error(symbol);
}
""" + "const api = {\n" + method + "};\n" + r"""
const run = (id='target',type='STOCK') => api.completeaccount('main',id,type).result;
assert.equal(run().outcome,'trading_account_pending');
assert.deepEqual(calls,[102]); // Only the matching stock account, never the credit account.
run(); assert.deepEqual(calls,[102]); // An uncertain result must not trigger a repeat login.
accounts[2].status='登录成功';assert.equal(run().ready,true);
assert.equal(run('missing').outcome,'trading_account_not_found');
assert.equal(run('').outcome,'trading_account_required');
assert.equal(run('target','FUTURE').outcome,'account_type_unsupported');
accounts[2].status='登录失败';assert.equal(run().outcome,'trading_account_login_failed');
accounts.push({...accounts[2]});assert.equal(run().outcome,'trading_account_not_found');
assert.deepEqual(calls,[102]);
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
