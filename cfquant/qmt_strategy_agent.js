'use strict';

// A scope also permits an older Python host to append this agent to its login
// agent while the project is being upgraded.
(() => {
// Resolve query, start and notice APIs independently of the login agent.
const missing = {gui: [], query: [], start: [], whitelist: [], notice: [], dismiss: []};
function native(group, moduleName, name, result, args) {
  const module = Process.findModuleByName(moduleName);
  const address = module && module.findExportByName(name);
  if (!address) {
    missing[group].push(moduleName + ':' + name);
    return null;
  }
  return new NativeFunction(address, result, args);
}
const findWidget = native('gui', 'Qt5Widgets.dll', '?find@QWidget@@SAPEAV1@_K@Z', 'pointer', ['uint64']);
const inherits = native('gui', 'Qt5Core.dll', '?inherits@QObject@@QEBA_NPEBD@Z', 'bool', ['pointer', 'pointer']);
const getThread = native('gui', 'user32.dll', 'GetWindowThreadProcessId', 'uint32', ['pointer', 'pointer']);
const postMessage = native('gui', 'user32.dll', 'PostMessageW', 'bool', ['pointer', 'uint32', 'pointer', 'pointer']);
const dispatchModule = Process.findModuleByName('user32.dll');
const dispatchAddress = dispatchModule && dispatchModule.findExportByName('DispatchMessageW');
if (!dispatchAddress) missing.gui.push('user32.dll:DispatchMessageW');
if (Process.arch !== 'x64' || Process.pointerSize !== 8) missing.gui.push('x64 ABI');
const stringCtor = native('query', 'Qt5Core.dll', '??0QString@@QEAA@PEBVQChar@@H@Z', 'pointer', ['pointer', 'pointer', 'int']);
const stringDtor = native('query', 'Qt5Core.dll', '??1QString@@QEAA@XZ', 'void', ['pointer']);
const stringSize = native('query', 'Qt5Core.dll', '?size@QString@@QEBAHXZ', 'int', ['pointer']);
const stringData = native('query', 'Qt5Core.dll', '?utf16@QString@@QEBAPEBGXZ', 'pointer', ['pointer']);
const strategyManager = native('query', 'Formula.dll', '?instance@?$CSingletonT@VCStrategyTradeManager@TC@@@utils@@SAPEAVCStrategyTradeManager@TC@@XZ', 'pointer', []);
const strategySave = native('query', 'Formula.dll', '?saveSettings@CStrategyTradeManager@TC@@QEAAXAEAVQDomElement@@AEAVQDomDocument@@@Z', 'void', ['pointer', 'pointer', 'pointer']);
// isStrategyRun takes a request identifier; isFomrulaRun takes a formula name.
const strategyRunning = native('query', 'Formula.dll', '?isFomrulaRun@CStrategyTradeManager@TC@@QEAA_NAEBVQString@@@Z', 'bool', ['pointer', 'pointer']);
// Older QMT builds expose runStrategy without a separate readiness query.
// Use their native start path; never replace or change QMT whitelist checks.
const strategyWhitelistReady = native('whitelist', 'Formula.dll', '?isConnWhiteListReady@CStrategyTradeManager@TC@@QEBA_NXZ', 'bool', ['pointer']);
const strategyRun = native('start', 'Formula.dll', '?runStrategy@CStrategyTradeManager@TC@@QEAAXHAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z', 'void', ['pointer', 'int', 'pointer']);
const strategyDocCtor = native('query', 'Qt5Xml.dll', '??0QDomDocument@@QEAA@XZ', 'pointer', ['pointer']);
const strategyDocDtor = native('query', 'Qt5Xml.dll', '??1QDomDocument@@QEAA@XZ', 'void', ['pointer']);
const strategyElemDtor = native('query', 'Qt5Xml.dll', '??1QDomElement@@QEAA@XZ', 'void', ['pointer']);
const strategyCreateElem = native('query', 'Qt5Xml.dll', '?createElement@QDomDocument@@QEAA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyFirst = native('query', 'Qt5Xml.dll', '?firstChildElement@QDomNode@@QEBA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyNext = native('query', 'Qt5Xml.dll', '?nextSiblingElement@QDomNode@@QEBA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyNull = native('query', 'Qt5Xml.dll', '?isNull@QDomNode@@QEBA_NXZ', 'bool', ['pointer']);
const strategyAttr = native('query', 'Qt5Xml.dll', '?attribute@QDomElement@@QEBA?AVQString@@AEBV2@0@Z', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);
const isVisible = native('notice', 'Qt5Widgets.dll', '?isVisible@QWidget@@QEBA_NXZ', 'bool', ['pointer']);
const children = native('notice', 'Qt5Core.dll', '?children@QObject@@QEBAAEBV?$QList@PEAVQObject@@@@XZ', 'pointer', ['pointer']);
const noticeText = native('notice', 'BaseWidget.dll', '?getText@CSimpleTextWidget@XP@@QEBA?AVQString@@XZ', 'pointer', ['pointer', 'pointer']);
const closeNotice = native('dismiss', 'Dialog.dll', '?closeMessage@CGlobalMessageDialog@XP@@SAXXZ', 'void', []);

function capabilities() {
  const query = missing.gui.concat(missing.query);
  const start = query.concat(missing.start);
  const whitelist = query.concat(missing.whitelist);
  const notice = query.concat(missing.notice);
  const dismiss = notice.concat(missing.dismiss);
  return {can_query: !query.length, can_start: !start.length, can_check_whitelist: !whitelist.length,
    can_read_notices: !notice.length, can_dismiss_notices: !dismiss.length,
    missing_query: query, missing_start: start, missing_whitelist: whitelist, missing_notice: notice, missing_dismiss: dismiss};
}
const typeNames = new Map();
function hasType(object, name) {
  if (!typeNames.has(name)) typeNames.set(name, Memory.allocUtf8String(name));
  return inherits(object, typeNames.get(name));
}
function getRoot(hwnd) {
  const root = findWidget(uint64(hwnd));
  if (root.isNull()) throw new Error('No Qt widget for target window');
  return root;
}
let pending = null;
function onGui(hwnd, operation) {
  if (missing.gui.length) throw new Error('Missing Qt GUI interfaces: ' + missing.gui.join(', '));
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
    if (!postMessage(ptr(hwnd), 0, NULL, NULL)) {
      pending = null;
      clearTimeout(timer);
      reject(new Error('Cannot wake QMT GUI thread'));
    }
  });
}
if (!missing.gui.length) Interceptor.attach(dispatchAddress, {
  onLeave() {
    if (!pending || this.threadId !== pending.thread) return;
    const job = pending;
    pending = null;
    clearTimeout(job.timer);
    try { job.resolve({gui_thread: this.threadId, result: job.operation()}); }
    catch (error) { job.reject(error); }
  }
});

function strategyString(text, action) {
  const value = Memory.alloc(Process.pointerSize);
  stringCtor(value, Memory.allocUtf16String(text), text.length);
  try { return action(value); } finally { stringDtor(value); }
}

function readString(value) {
  const size = stringSize(value);
  if (size < 0 || size > 65536) throw new Error('Invalid Qt string size');
  return size ? stringData(value).readUtf16String(size) : '';
}

function strategyAttribute(element, name) {
  return strategyString(name, key => strategyString('', empty => {
    const value = Memory.alloc(Process.pointerSize);
    strategyAttr(element, value, key, empty);
    try { return readString(value); }
    finally { stringDtor(value); }
  }));
}

function strategySnapshot(root, checkStartup = false) {
  const support = capabilities();
  if (!support.can_query) throw new Error('Missing strategy query interfaces: ' + support.missing_query.join(', '));
  if (!hasType(root, 'TC::CMainWindow')) throw new Error('QMT is not logged in');
  const manager = strategyManager();
  if (manager.isNull()) throw new Error('Strategy manager unavailable');
  const doc = Memory.alloc(64), parent = Memory.alloc(64), models = [];
  strategyDocCtor(doc);
  try {
    strategyString('Models', tag => strategyCreateElem(doc, parent, tag));
    try {
      // Serializes only into our temporary DOM; no configuration is written.
      strategySave(manager, parent, doc);
      strategyString('item', tag => {
        let element = Memory.alloc(64);
        strategyFirst(parent, element, tag);
        try {
          while (!strategyNull(element)) {
            if (models.length >= 1000) throw new Error('Too many QMT models');
            const row = {};
            for (const key of ['id', 'name', 'account', 'm_strAccountKey', 'runMode',
                               'startupAutorun', 'eStrategyType', 'stock', 'peroid']) {
              row[key] = strategyAttribute(element, key);
            }
            row.running = Boolean(strategyString(row.name, name => strategyRunning(manager, name)));
            models.push(row);
            const next = Memory.alloc(64);
            strategyNext(element, next, tag);
            strategyElemDtor(element);
            element = next;
          }
        } finally { strategyElemDtor(element); }
      });
    } finally { strategyElemDtor(parent); }
  } finally { strategyDocDtor(doc); }
  return {models, capabilities: support,
    whitelist_ready: checkStartup && strategyWhitelistReady ? Boolean(strategyWhitelistReady(manager)) : null};
}

rpc.exports.strategycapabilities = capabilities;
rpc.exports.status = hwnd => onGui(hwnd, () => {
  const root = getRoot(hwnd);
  return {is_main: hasType(root, 'TC::CMainWindow'), is_login: hasType(root, 'TC::CLoginDialog'), login_identity: null};
});
rpc.exports.strategystatus = hwnd => onGui(hwnd, () => strategySnapshot(getRoot(hwnd)));
function childObjects(object) {
  // Qt 5 x64 QList<QObject*>; never assume broker-specific widget offsets.
  const data = children(object).readPointer();
  const begin = data.add(8).readS32(), end = data.add(12).readS32();
  if (begin < 0 || end < begin || end > 5000) throw new Error('Unexpected QList layout');
  const result = [];
  for (let index = begin; index < end; index++) result.push(data.add(16 + index * Process.pointerSize).readPointer());
  return result;
}
function illegalIpNotice(hwnd) {
  if (!capabilities().can_read_notices) return null;
  const root = getRoot(hwnd);
  if (!(hasType(root, 'XP::CGlobalMessageDialog') || hasType(root, 'CGlobalMessageDialog')) || !isVisible(root)) return null;
  const queue = [root], seen = new Set(), matches = [];
  while (queue.length) {
    const object = queue.shift();
    if (object.isNull() || seen.has(object.toString())) continue;
    seen.add(object.toString());
    if (seen.size > 512) throw new Error('Message widget tree too large');
    if ((hasType(object, 'XP::CSimpleTextWidget') || hasType(object, 'CSimpleTextWidget')) && isVisible(object)) {
      const value = Memory.alloc(Process.pointerSize);
      noticeText(object, value);
      let text;
      try { text = readString(value); } finally { stringDtor(value); }
      if (/^\[防外接\]\s*Python进程访问了网络地址\s*\[[^\]]+\]\s*[，,]\s*策略运行中止[！!]\s*$/.test(text)) matches.push(text);
    }
    queue.push(...childObjects(object));
  }
  return matches.length === 1 ? {hwnd, text: matches[0]} : null;
}
rpc.exports.illegalipnotice = hwnd => onGui(hwnd, () => illegalIpNotice(hwnd));
rpc.exports.dismissillegalip = (mainHwnd, hwnd, text, expected) => onGui(mainHwnd, () => {
  if (!capabilities().can_dismiss_notices) return {outcome: 'notice_close_unavailable', closed: false};
  const models = strategySnapshot(getRoot(mainHwnd)).models;
  for (const target of expected) {
    const matches = models.filter(model => model.name === target.name);
    if (matches.length !== 1 || Object.keys(target).some(key => matches[0][key] !== target[key])) {
      throw new Error('Strategy binding changed before warning dismissal');
    }
  }
  if (!expected.length) throw new Error('No bound strategy');
  const current = illegalIpNotice(hwnd);
  if (!current) return {outcome: 'already_hidden_or_changed', closed: false};
  if (current.text !== text) return {outcome: 'message_changed', closed: false};
  closeNotice();
  const closed = !isVisible(getRoot(hwnd));
  return {outcome: closed ? 'closed' : 'close_failed', closed};
});
rpc.exports.strategystart = (hwnd, expected) => onGui(hwnd, () => {
  if (!capabilities().can_start) return {outcome: 'detection_only', requested: false};
  // Re-read on the same GUI turn as the mutation. Cached IDs are insufficient.
  const snapshot = strategySnapshot(getRoot(hwnd), true);
  const matches = snapshot.models.filter(row => row.name === expected.name);
  if (matches.length !== 1) throw new Error('No unique bound strategy');
  const model = matches[0];
  for (const key of ['id', 'name', 'account', 'm_strAccountKey', 'runMode',
                     'startupAutorun', 'eStrategyType', 'stock', 'peroid']) {
    if (typeof expected[key] !== 'string' || !expected[key] || model[key] !== expected[key]) {
      throw new Error('Strategy binding changed: ' + key);
    }
  }
  if (!/^CFQ_[A-Za-z0-9_]+$/.test(model.name) || model.startupAutorun !== '1' ||
      model.eStrategyType !== '4' || !/^[1-9][0-9]*$/.test(model.id) || Number(model.id) > 2147483647) {
    throw new Error('Not an eligible managed strategy');
  }
  if (model.running) return {outcome: 'already_running', requested: false};
  if (snapshot.whitelist_ready === false) return {outcome: 'waiting_whitelist', requested: false};
  // Empty release-mode MSVC x64 std::string (SSO), matching the exported ABI.
  const reason = Memory.alloc(32);
  reason.writeByteArray(new Uint8Array(32));
  reason.add(24).writeU64(15);
  strategyRun(strategyManager(), Number(model.id), reason);
  return {outcome: 'start_requested', requested: true};
});
})();
