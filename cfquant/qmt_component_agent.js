'use strict';

const core = Process.getModuleByName('Qt5Core.dll');
const widgets = Process.getModuleByName('Qt5Widgets.dll');
const user32 = Process.getModuleByName('user32.dll');
const fn = (mod, name, ret, args) => new NativeFunction(mod.getExportByName(name), ret, args);
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
  const begin = d.add(8).readS32(), end = d.add(12).readS32();
  if (begin < 0 || end < begin || end - begin > 5000) throw new Error('Unexpected QList layout');
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
  passwordEditor(root);
  const login = fn(Process.getModuleByName('LoginDialog.dll'),
    '?slot_loginClicked@CLoginDialog@TC@@QEAAXXZ', 'void', ['pointer']);
  login(root);
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
      if (edits.length > 1) throw new Error('Multiple password editors are visible');
      return {is_login: true, has_password: edits.length === 1 && hasText(ptr(edits[0].address)),
        busy: edits.length === 0, login_identity: loginIdentity(root), notice: noticeKind(rows),
        login_enabled: rows.some(row => row.visible && row.enabled && /^登\s*录(?:[（(]\d+[)）])?$/.test(row.label || ''))};
    });
  },
  notice(hwnd) {
    return onGui(hwnd, () => {
      const rows = walk(getRoot(hwnd));
      return {kind: noticeKind(rows)};
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
  submit(hwnd) { return onGui(hwnd, () => { submit(getRoot(hwnd)); return {submitted: true}; }); },
  close(hwnd) { return onGui(hwnd, () => ({closed: closeWidget(getRoot(hwnd))})); },
  clicklabel(hwnd, text) {
    return onGui(hwnd, () => {
      const rows = walk(getRoot(hwnd)).filter(row => row.label === text && row.visible && row.enabled);
      if (rows.length !== 1) throw new Error('Expected one matching enabled button');
      buttonClick(ptr(rows[0].address));
      return {clicked: true};
    });
  },
  fill(hwnd, value, submit) {
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
      if (submit) {
        const login = fn(Process.getModuleByName('LoginDialog.dll'),
          '?slot_loginClicked@CLoginDialog@TC@@QEAAXXZ', 'void', ['pointer']);
        login(root);
      }
      return {filled: true, submitted: Boolean(submit), characters: count,
              input_method: 'QLineEdit::setText', login_method: submit ? 'CLoginDialog::slot_loginClicked' : null};
    });
  }
};
