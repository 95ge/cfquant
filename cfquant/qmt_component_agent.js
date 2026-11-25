'use strict';

const core = Process.getModuleByName('Qt5Core.dll');
const widgets = Process.getModuleByName('Qt5Widgets.dll');
const user32 = Process.getModuleByName('user32.dll');
const fn = (mod, name, ret, args) => {
  const address = mod.findExportByName(name);
  if (!address) throw new Error('QMT 登录组件缺少接口: ' + mod.name + '!' + name);
  return new NativeFunction(address, ret, args);
};
if (Process.arch !== 'x64' || Process.pointerSize !== 8) throw new Error('QMT 登录组件需要 x64 客户端');
// Read the loaded library's build string, not the on-disk DLL that an updater
// may already have replaced. Vendor Windows builds do not always export qVersion.
const qtBuild = fn(core, '?build@QLibraryInfo@@SAPEBDXZ', 'pointer', [])().readUtf8String();
const qtMatch = /^Qt (\d+\.\d+\.\d+)(?:\s|$)/.exec(qtBuild || '');
const qtVersion = qtMatch ? qtMatch[1] : 'unknown';
if (!['5.6.2', '5.15.2'].includes(qtVersion)) throw new Error('QMT 已加载未适配的 Qt ' + qtVersion);
const findWidget = fn(widgets, '?find@QWidget@@SAPEAV1@_K@Z', 'pointer', ['uint64']);
const children = fn(core, '?children@QObject@@QEBAAEBV?$QList@PEAVQObject@@@@XZ', 'pointer', ['pointer']);
const inherits = fn(core, '?inherits@QObject@@QEBA_NPEBD@Z', 'bool', ['pointer', 'pointer']);
const className = fn(core, '?className@QMetaObject@@QEBAPEBDXZ', 'pointer', ['pointer']);
const isVisible = fn(widgets, '?isVisible@QWidget@@QEBA_NXZ', 'bool', ['pointer']);
const isEnabled = fn(widgets, '?isEnabled@QWidget@@QEBA_NXZ', 'bool', ['pointer']);
const echoMode = fn(widgets, '?echoMode@QLineEdit@@QEBA?AW4EchoMode@1@XZ', 'int', ['pointer']);
const setText = fn(widgets, '?setText@QLineEdit@@QEAAXAEBVQString@@@Z', 'void', ['pointer', 'pointer']);
const stringCtor = fn(core, '??0QString@@QEAA@PEBVQChar@@H@Z', 'pointer', ['pointer', 'pointer', 'int']);
const stringDtor = fn(core, '??1QString@@QEAA@XZ', 'void', ['pointer']);
const stringSize = fn(core, '?size@QString@@QEBAHXZ', 'int', ['pointer']);
const stringData = fn(core, '?utf16@QString@@QEBAPEBGXZ', 'pointer', ['pointer']);
const buttonText = fn(widgets, '?text@QAbstractButton@@QEBA?AVQString@@XZ', 'pointer', ['pointer', 'pointer']);
const editText = fn(widgets, '?text@QLineEdit@@QEBA?AVQString@@XZ', 'pointer', ['pointer', 'pointer']);
const labelText = fn(widgets, '?text@QLabel@@QEBA?AVQString@@XZ', 'pointer', ['pointer', 'pointer']);
const buttonClick = fn(widgets, '?click@QAbstractButton@@QEAAXXZ', 'void', ['pointer']);
const closeWidget = fn(widgets, '?close@QWidget@@QEAA_NXZ', 'bool', ['pointer']);
const comboEditable = fn(widgets, '?isEditable@QComboBox@@QEBA_NXZ', 'bool', ['pointer']);
const comboSetText = fn(widgets, '?setEditText@QComboBox@@QEAAXAEBVQString@@@Z', 'void', ['pointer', 'pointer']);
const getThread = fn(user32, 'GetWindowThreadProcessId', 'uint32', ['pointer', 'pointer']);
const postMessage = fn(user32, 'PostMessageW', 'bool', ['pointer', 'uint32', 'pointer', 'pointer']);
const typeNames = new Map();
let pending = null;
let loginEnvironment = 'live';
const accountSubmissions = new Set();
const exitPrompts = new Set();

function isExitPrompt(text) {
  return /(?:是否|确定|确认).{0,12}(?:退出|关闭).{0,40}(?:系统|程序|客户端|软件|QMT|iQuant|平台)/.test(text)
    || /^\s*(?:您)?(?:是否|确定|确认)(?:要)?退出(?:吗)?[？?！!。\s]*$/.test(text);
}

// Guosen draws message text itself, without QLabel children or a text getter.
// Observe the public constructor's QString argument and retain only whether it
// is an exit prompt; never infer consent from a generic confirmation button.
const dialogModule = Process.findModuleByName('Dialog.dll');
if (dialogModule) {
  for (const symbol of [
    '??0CMessageBox@XP@@IEAA@PEAVCButtonStyle@1@W4Icon@QMessageBox@@AEBVQString@@2222PEAVQWidget@@VQPoint@@@Z',
    '??0CMessageBox@XP@@IEAA@PEAVCButtonStyle@1@W4Icon@QMessageBox@@AEBVQString@@2V?$QFlags@W4StandardButton@QMessageBox@@@@W4StandardButton@4@PEAVQWidget@@PEAVQPixmap@@VQPoint@@@Z'
  ]) {
    const address = dialogModule.findExportByName(symbol);
    if (address) Interceptor.attach(address, {onEnter(args) {
      const key = args[0].toString();
      exitPrompts.delete(key);
      try {
        const size = stringSize(args[4]);
        if (size > 0 && size <= 4096 && isExitPrompt(stringData(args[4]).readUtf16String(size)))
          exitPrompts.add(key);
      } catch (_) { /* Unknown message layouts remain unconfirmed. */ }
    }});
  }
  const destroy = dialogModule.findExportByName('??1CMessageBox@XP@@UEAA@XZ');
  if (destroy) Interceptor.attach(destroy, {onEnter(args) { exitPrompts.delete(args[0].toString()); }});
}

function isGuosen() {
  // Most brokers ship the same Guosen exports. Detect the active client mode,
  // never the directory name or the mere presence of a shared DLL symbol.
  const module = Process.findModuleByName('User.dll');
  if (!module) return false;
  const getConfig = module.findExportByName('?getUserConfig@TC@@YAPEAVCUserConfig@1@XZ');
  const check = module.findExportByName('?isGuosenClientMode@CUserConfig@TC@@QEBA_NXZ');
  if (!getConfig || !check) return false;
  const config = new NativeFunction(getConfig, 'pointer', [])();
  return !config.isNull() && !!new NativeFunction(check, 'bool', ['pointer'])(config);
}

function loginTarget(rows) {
  const guosen = isGuosen();
  const pattern = guosen ? (loginEnvironment === 'simulation' ? /^登录仿真$/ :
    loginEnvironment === 'live' ? /^登录实盘$/ : /a^/) : /^登\s*录(?:[（(]\d+[)）])?$/;
  const matches = rows.filter(row => row.visible && row.enabled && pattern.test(row.label || ''));
  return {broker: guosen ? 'guosen' : 'generic', button: matches.length === 1 ? matches[0] : null};
}

function hasType(object, name) {
  if (!typeNames.has(name)) typeNames.set(name, Memory.allocUtf8String(name));
  return inherits(object, typeNames.get(name));
}

function typeName(object) {
  const metaFn = new NativeFunction(object.readPointer().readPointer(), 'pointer', ['pointer']);
  return className(metaFn(object)).readUtf8String();
}

function childObjects(object) {
  const d = children(object).readPointer();
  if (d.isNull()) throw new Error('Unexpected null QList data');
  // QList<QObject*> has the same header on the two verified Qt 5 versions:
  // refcount, capacity, begin, end, then pointer-sized elements.
  const capacity = d.add(4).readS32();
  const begin = d.add(8).readS32(), end = d.add(12).readS32();
  if (capacity < 0 || begin < 0 || end < begin || end > capacity || end - begin > 5000)
    throw new Error('Unexpected QList layout');
  const result = [];
  for (let i = begin; i < end; i++) result.push(d.add(16 + i * Process.pointerSize).readPointer());
  return result;
}

function label(object) {
  const result = Memory.alloc(Process.pointerSize);
  buttonText(object, result);
  try { return stringData(result).readUtf16String(stringSize(result)); }
  finally { stringDtor(result); }
}

function walk(root) {
  const result = [], queue = [{object: root, parent: null}], seen = new Set();
  while (queue.length) {
    const item = queue.shift(), object = item.object;
    if (object.isNull() || seen.has(object.toString())) continue;
    seen.add(object.toString());
    if (seen.size > 5000) throw new Error('Object tree too large');
    const isWidget = hasType(object, 'QWidget');
    const row = {address: object.toString(), parent: item.parent, class_name: typeName(object)};
    if (isWidget) {
      row.visible = isVisible(object);
      row.enabled = isEnabled(object);
      if (hasType(object, 'QLineEdit')) row.echo_mode = echoMode(object);
      if (hasType(object, 'QAbstractButton')) row.label = label(object);
      if (hasType(object, 'QLabel')) {
        const value = Memory.alloc(Process.pointerSize);
        labelText(object, value);
        try { row.text = stringData(value).readUtf16String(stringSize(value)); }
        finally { stringDtor(value); }
      }
    }
    result.push(row);
    childObjects(object).forEach(child => queue.push({object: child, parent: object.toString()}));
  }
  return result;
}

function getRoot(hwnd) {
  const root = findWidget(uint64(hwnd));
  if (root.isNull()) throw new Error('No Qt widget for target window');
  return root;
}

function passwordEditor(root, requireEnabled = true) {
  if (!hasType(root, 'TC::CLoginDialog')) throw new Error('Not a QMT login dialog');
  const rows = walk(root);
  const edits = rows.filter(row => row.echo_mode === 2 && row.visible && (!requireEnabled || row.enabled));
  if (edits.length !== 1) throw new Error('Expected exactly one visible password editor');
  return {rows, editor: ptr(edits[0].address)};
}

function hasText(editor) {
  const value = Memory.alloc(Process.pointerSize);
  editText(editor, value);
  // Only return emptiness; never copy a remembered password out of the process.
  try { return stringSize(value) > 0; }
  finally { stringDtor(value); }
}

function noticeKind(rows) {
  let credential = false, network = false;
  for (const row of rows) {
    const object = ptr(row.address);
    if (!row.visible || !hasType(object, 'QLabel')) continue;
    const value = Memory.alloc(Process.pointerSize);
    labelText(object, value);
    let text;
    try { text = stringData(value).readUtf16String(stringSize(value)); }
    finally { stringDtor(value); }
    if (/验证码|动态口令|短信验证|captcha/i.test(text)) return 'challenge';
    if (/密码.{0,12}(错误|不正确|失败|无效)|口令.{0,12}(错误|不正确|失败)|password.{0,16}(incorrect|invalid|wrong)/i.test(text)) credential = true;
    if (/(网络|连接|服务器).{0,16}(失败|超时|异常)|network.{0,16}(error|timeout)/i.test(text)) network = true;
  }
  return credential ? 'credential_error' : network ? 'network_error' : null;
}

function submit(root) {
  const rows = walk(root);
  const target = loginTarget(rows);
  const edits = rows.filter(row => row.echo_mode === 2 && row.visible && row.enabled);
  // Check on the GUI thread as well: an update can disable the button after
  // Python has inspected it. A declined submission is safe to retry later.
  if (edits.length !== 1 || !hasText(ptr(edits[0].address)) ||
      !target.button) {
    return {submitted: false};
  }
  passwordEditor(root);
  if (target.broker === 'guosen') {
    buttonClick(ptr(target.button.address));
    return {submitted: true, broker: target.broker, environment: loginEnvironment};
  }
  const login = fn(Process.getModuleByName('LoginDialog.dll'),
    '?slot_loginClicked@CLoginDialog@TC@@QEAAXXZ', 'void', ['pointer']);
  login(root);
  return {submitted: true};
}

function captchaCode(root) {
  const rows = walk(root);
  const code = rows.map(row => row.text || row.label || '').map(text => {
    const match = String(text).match(/(?:\u9a8c\u8bc1\u7801|captcha)\s*[:\uff1a]?\s*([A-Za-z0-9]{4,8})/i);
    return match && match[1];
  }).find(Boolean);
  if (!code) return {solved: false, reason: 'captcha image/code is not readable'};
  const inputs = rows.filter(row => row.visible && row.enabled && row.echo_mode === 0);
  if (inputs.length !== 1) return {solved: false, reason: 'captcha input is not uniquely identifiable'};
  const text = Memory.allocUtf16String(code), string = Memory.alloc(Process.pointerSize);
  stringCtor(string, text, code.length);
  try { setText(ptr(inputs[0].address), string); }
  finally { stringDtor(string); text.writeByteArray(new Uint8Array((code.length + 1) * 2)); }
  return {solved: true, characters: code.length, input_method: 'QLineEdit::setText'};
}

function loginIdentity(root) {
  const getName = fn(Process.getModuleByName('LoginDialog.dll'),
    '?getUserName@CLoginDialog@TC@@IEAA?AVQString@@XZ', 'pointer', ['pointer', 'pointer']);
  const value = Memory.alloc(Process.pointerSize);
  getName(root, value);
  try { return stringData(value).readUtf16String(stringSize(value)); }
  finally { stringDtor(value); }
}

function onGui(hwnd, operation) {
  if (pending) throw new Error('An operation is already pending');
  const thread = getThread(ptr(hwnd), NULL);
  if (!thread) throw new Error('Target window no longer exists');
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (pending && pending.resolve === resolve) {
        pending = null;
        reject(new Error('GUI operation timeout'));
      }
    }, 8000);
    pending = {thread, operation, resolve, reject, timer};
    // Wake the normal message loop without mouse/keyboard events or foreground changes.
    postMessage(ptr(hwnd), 0, NULL, NULL);
  });
}

Interceptor.attach(user32.getExportByName('DispatchMessageW'), {
  onLeave() {
    if (!pending || this.threadId !== pending.thread) return;
    const job = pending;
    pending = null;
    clearTimeout(job.timer);
    try { job.resolve({gui_thread: this.threadId, result: job.operation()}); }
    catch (error) { job.reject(error); }
  }
});

rpc.exports = {
  environment(hwnd, mark = false) {
    const key = Memory.allocUtf16String('CFQuantGuosenEnvironment');
    if (mark) {
      if (!fn(user32, 'SetPropW', 'bool', ['pointer', 'pointer', 'pointer'])(ptr(hwnd), key,
          ptr(loginEnvironment === 'simulation' ? 1 : 2))) throw new Error('Could not record QMT login environment');
    }
    return fn(user32, 'GetPropW', 'pointer', ['pointer', 'pointer'])(ptr(hwnd), key).toInt32();
  },
  broker() { return isGuosen() ? 'guosen' : 'generic'; },
  completeaccount(hwnd, account, accountType) {
    if (!isGuosen()) return Promise.resolve({result: {ready: true, broker: 'generic'}});
    return onGui(hwnd, () => {
      if (!account) return {ready: false, outcome: 'trading_account_required'};
      const root = getRoot(hwnd);
      if (!hasType(root, 'TC::CMainWindow')) throw new Error('Expected a QMT main window');
      const module = Process.getModuleByName('Setting.dll');
      const dialog = fn(module, '?createSettingPage@CSettingDialogNew@TC@@SAPEAV12@PEAVQWidget@@@Z',
        'pointer', ['pointer'])(root);
      fn(module, '?load@CSettingDialogNew@TC@@QEAAXXZ', 'void', ['pointer'])(dialog);
      const page = Process.getModuleByName('PanelUiCommon.dll').getExportByName(
        '?ID_SETTING_ACCOUNT_MANAGER@TC@@3HB').readS32();
      fn(module, '?showPage@CSettingDialogNew@TC@@QEAAXH@Z', 'void', ['pointer', 'int'])(dialog, page);
      const rows = walk(dialog);
      const accountWidgets = rows.filter(r => r.class_name === 'TC::CSettingAccountWidget');
      if (accountWidgets.length !== 1) return {ready: false, outcome: 'account_ui_unsupported'};
      const widget = ptr(accountWidgets[0].address);
      const tables = walk(widget).filter(r => r.class_name === 'XP::IBaseTable');
      if (tables.length !== 1) return {ready: false, outcome: 'account_ui_unsupported'};
      const table = ptr(tables[0].address), base = Process.getModuleByName('BaseWidget.dll');
      const count = fn(base, '?rowCount@IBaseTable@XP@@QEBAHXZ', 'int', ['pointer'])(table);
      const columnCount = fn(base, '?columnCount@IBaseTable@XP@@QEBAHXZ', 'int', ['pointer'])(table);
      if (count < 0 || count > 500 || columnCount < 0 || columnCount > 100) throw new Error('Unexpected account table size');
      function readText(symbol, args, values) {
        const value = Memory.alloc(Process.pointerSize);
        fn(base, symbol, 'pointer', ['pointer', 'pointer'].concat(args))(table, value, ...values);
        try { return stringData(value).readUtf16String(stringSize(value)); }
        finally { stringDtor(value); }
      }
      const columns = {};
      for (let i = 0; i < columnCount; i++) {
        const id = fn(base, '?columnID@IBaseTable@XP@@QEBAHH@Z', 'int', ['pointer', 'int'])(table, i);
        const title = readText('?columnHeader@IBaseTable@XP@@QEBA?AVQString@@H@Z', ['int'], [id]);
        columns[title] = id;
      }
      if (!['账号', '登录状态', '账号类型'].every(k => Object.prototype.hasOwnProperty.call(columns, k)))
        return {ready: false, outcome: 'account_ui_unsupported'};
      const cell = (row, title) => readText('?itemText@IBaseTable@XP@@UEBA?AVQString@@HH@Z',
        ['int', 'int'], [row, columns[title]]);
      const type = {STOCK: '股票账号', CREDIT: '信用账号', STOCK_OPTION: '股票期权账号'}[accountType];
      if (!type) return {ready: false, outcome: 'account_type_unsupported'};
      const matches = [];
      for (let i = 0; i < count; i++) {
        if (cell(i, '账号') === account && cell(i, '账号类型') === type) matches.push(i);
      }
      if (matches.length !== 1) return {ready: false, outcome: 'trading_account_not_found'};
      const row = matches[0], status = cell(row, '登录状态');
      if (status === '登录成功') return {ready: true, broker: 'guosen', status};
      if (/失败|错误|拒绝|锁定/.test(status)) return {ready: false, outcome: 'trading_account_login_failed', status};
      const key = accountType + ':' + account;
      if (!accountSubmissions.has(key) && /^(未登录|准备登录|已登出|已退出|未连接)$/.test(status)) {
        accountSubmissions.add(key);
        const rowId = fn(base, '?rowID@IBaseTable@XP@@QEBAHH@Z', 'int', ['pointer', 'int'])(table, row);
        fn(module, '?forceLogin@CSettingAccountWidget@TC@@QEAAXH@Z', 'void', ['pointer', 'int'])(widget, rowId);
      }
      return {ready: false, outcome: 'trading_account_pending', status};
    });
  },
  configurelogin(environment) {
    if (!['simulation', 'live'].includes(environment)) throw new Error('Expected an explicit QMT login environment');
    loginEnvironment = environment;
    return {environment};
  },
  compatibility() { return {qt_version: qtVersion, architecture: Process.arch}; },
  selectaccount(hwnd, account, replace = false) {
    return onGui(hwnd, () => {
      const root = getRoot(hwnd);
      passwordEditor(root);
      if (!replace && loginIdentity(root) === account) return {changed: false};
      const candidates = walk(root).filter(row => row.visible && row.enabled &&
        hasType(ptr(row.address), 'QComboBox') && comboEditable(ptr(row.address)));
      if (candidates.length !== 1) throw new Error('No unique editable account selector');
      if (replace) {
        const empty = Memory.alloc(Process.pointerSize);
        stringCtor(empty, Memory.allocUtf16String(''), 0);
        try { comboSetText(ptr(candidates[0].address), empty); }
        finally { stringDtor(empty); }
      }
      const data = Memory.allocUtf16String(account), value = Memory.alloc(Process.pointerSize);
      stringCtor(value, data, account.length);
      try { comboSetText(ptr(candidates[0].address), value); }
      finally { stringDtor(value); }
      if (loginIdentity(root) !== account) throw new Error('Could not select configured login account');
      return {changed: true};
    });
  },
  inspect(hwnd) { return onGui(hwnd, () => walk(getRoot(hwnd))); },
  status(hwnd) {
    return onGui(hwnd, () => {
      const root = getRoot(hwnd);
      if (!hasType(root, 'TC::CLoginDialog')) return {is_login: false, is_main: hasType(root, 'TC::CMainWindow')};
      const rows = walk(root);
      const edits = rows.filter(row => row.echo_mode === 2 && row.visible);
      const target = loginTarget(rows);
      if (edits.length > 1) throw new Error('Multiple password editors are visible');
      return {is_login: true, has_password: edits.length === 1 && hasText(ptr(edits[0].address)),
        busy: edits.length === 0 || !edits[0].enabled, login_identity: loginIdentity(root), notice: noticeKind(rows),
        broker: target.broker, environment: loginEnvironment,
        login_enabled: !!target.button};
    });
  },
  notice(hwnd) {
    return onGui(hwnd, () => {
      const rows = walk(getRoot(hwnd));
      return {kind: noticeKind(rows)};
    });
  },
  confirmexit(hwnd) {
    return onGui(hwnd, () => {
      // A Qt native handle may outlive its QWidget during normal shutdown.
      const root = findWidget(uint64(hwnd));
      if (root.isNull() || !hasType(root, 'QDialog')) return {confirmed: false};
      const rows = walk(root);
      const text = rows.filter(row => row.visible).map(row => row.text || '').join(' ');
      if (!isExitPrompt(text) && !exitPrompts.has(root.toString())) return {confirmed: false};
      const buttons = rows.filter(row => row.visible && row.enabled &&
        /^(?:确定|确认|是|退出|Yes|OK)(?:\(&[A-Za-z]\))?$/.test(row.label || ''));
      if (buttons.length !== 1) return {confirmed: false};
      buttonClick(ptr(buttons[0].address));
      return {confirmed: true};
    });
  },
  acknowledge(hwnd) {
    return onGui(hwnd, () => {
      const rows = walk(getRoot(hwnd));
      if (noticeKind(rows) !== 'credential_error') throw new Error('Not a recognized credential failure');
      const buttons = rows.filter(row => row.visible && row.enabled && /^(确定|确认|OK|&OK)$/.test(row.label || ''));
      if (buttons.length !== 1) throw new Error('No unique acknowledgement button');
      buttonClick(ptr(buttons[0].address));
      return {acknowledged: true};
    });
  },
  submit(hwnd) { return onGui(hwnd, () => submit(getRoot(hwnd))); },
  captchacode(hwnd) { return onGui(hwnd, () => captchaCode(getRoot(hwnd))); },
  close(hwnd) { return onGui(hwnd, () => ({closed: closeWidget(getRoot(hwnd))})); },
  clicklabel(hwnd, text) {
    return onGui(hwnd, () => {
      const rows = walk(getRoot(hwnd)).filter(row => row.label === text && row.visible && row.enabled);
      if (rows.length !== 1) throw new Error('Expected one matching enabled button');
      buttonClick(ptr(rows[0].address));
      return {clicked: true};
    });
  },
  fill(hwnd, value, doSubmit) {
    return onGui(hwnd, () => {
      const root = getRoot(hwnd);
      if (!hasType(root, 'TC::CLoginDialog')) throw new Error('Not a QMT login dialog');
      const rows = walk(root);
      const edits = rows.filter(row => row.echo_mode === 2 && row.visible && row.enabled);
      if (edits.length !== 1) throw new Error('Expected exactly one visible password editor');
      const text = Memory.allocUtf16String(value);
      const string = Memory.alloc(Process.pointerSize);
      stringCtor(string, text, value.length);
      try { setText(ptr(edits[0].address), string); }
      finally {
        stringDtor(string);
        text.writeByteArray(new Uint8Array((value.length + 1) * 2));
      }
      const count = value.length;
      value = null;
      const submitted = doSubmit ? submit(root).submitted : false;
      return {filled: true, submitted, characters: count,
              input_method: 'QLineEdit::setText', login_method: submitted ? 'guarded login target' : null};
    });
  }
};
