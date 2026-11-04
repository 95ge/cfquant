// Appended to qmt_component_agent.js. All access runs on QMT's GUI thread.
// The Python backend checks the tested Formula.dll hash before loading this.
const strategyFormula = Process.getModuleByName('Formula.dll');
const strategyXml = Process.getModuleByName('Qt5Xml.dll');
const strategyManager = fn(strategyFormula, '?instance@?$CSingletonT@VCStrategyTradeManager@TC@@@utils@@SAPEAVCStrategyTradeManager@TC@@XZ', 'pointer', []);
const strategySave = fn(strategyFormula, '?saveSettings@CStrategyTradeManager@TC@@QEAAXAEAVQDomElement@@AEAVQDomDocument@@@Z', 'void', ['pointer', 'pointer', 'pointer']);
// isStrategyRun takes a request identifier; isFomrulaRun takes a formula name.
const strategyRunning = fn(strategyFormula, '?isFomrulaRun@CStrategyTradeManager@TC@@QEAA_NAEBVQString@@@Z', 'bool', ['pointer', 'pointer']);
const strategyWhitelistReady = fn(strategyFormula, '?isConnWhiteListReady@CStrategyTradeManager@TC@@QEBA_NXZ', 'bool', ['pointer']);
const strategyRun = fn(strategyFormula, '?runStrategy@CStrategyTradeManager@TC@@QEAAXHAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z', 'void', ['pointer', 'int', 'pointer']);
const strategyDocCtor = fn(strategyXml, '??0QDomDocument@@QEAA@XZ', 'pointer', ['pointer']);
const strategyDocDtor = fn(strategyXml, '??1QDomDocument@@QEAA@XZ', 'void', ['pointer']);
const strategyElemDtor = fn(strategyXml, '??1QDomElement@@QEAA@XZ', 'void', ['pointer']);
const strategyCreateElem = fn(strategyXml, '?createElement@QDomDocument@@QEAA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyFirst = fn(strategyXml, '?firstChildElement@QDomNode@@QEBA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyNext = fn(strategyXml, '?nextSiblingElement@QDomNode@@QEBA?AVQDomElement@@AEBVQString@@@Z', 'pointer', ['pointer', 'pointer', 'pointer']);
const strategyNull = fn(strategyXml, '?isNull@QDomNode@@QEBA_NXZ', 'bool', ['pointer']);
const strategyAttr = fn(strategyXml, '?attribute@QDomElement@@QEBA?AVQString@@AEBV2@0@Z', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']);

function strategyString(text, action) {
  const value = Memory.alloc(8);
  stringCtor(value, Memory.allocUtf16String(text), text.length);
  try { return action(value); } finally { stringDtor(value); }
}

function strategyAttribute(element, name) {
  return strategyString(name, key => strategyString('', empty => {
    const value = Memory.alloc(8);
    strategyAttr(element, value, key, empty);
    try { return stringData(value).readUtf16String(stringSize(value)); }
    finally { stringDtor(value); }
  }));
}

function strategySnapshot(root) {
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
  return {models, whitelist_ready: Boolean(strategyWhitelistReady(manager))};
}

rpc.exports.strategystatus = hwnd => onGui(hwnd, () => strategySnapshot(getRoot(hwnd)));
// These two additional DLL builds are verified by the Python backend before
// accessing the message dialog's content widget (Dialog.dll: setContent).
function illegalIpNotice(hwnd) {
  const root = getRoot(hwnd);
  if (!hasType(root, 'XP::CGlobalMessageDialog') || !isVisible(root)) return null;
  const content = root.add(0xe8).readPointer();
  if (content.isNull() || !childObjects(root).some(child => child.equals(content))) {
    throw new Error('Unexpected QMT message content widget');
  }
  const value = Memory.alloc(8);
  fn(Process.getModuleByName('BaseWidget.dll'), '?getText@CSimpleTextWidget@XP@@QEBA?AVQString@@XZ',
     'pointer', ['pointer', 'pointer'])(content, value);
  let text;
  try { text = stringData(value).readUtf16String(stringSize(value)); }
  finally { stringDtor(value); }
  if (!/^\[防外接\]\s*Python进程访问了网络地址\s*\[[^\]]+\]\s*[，,]\s*策略运行中止[！!]\s*$/.test(text)) return null;
  return {hwnd, text};
}
rpc.exports.illegalipnotice = hwnd => onGui(hwnd, () => illegalIpNotice(hwnd));
rpc.exports.dismissillegalip = (mainHwnd, hwnd, text, expected) => onGui(mainHwnd, () => {
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
  fn(Process.getModuleByName('Dialog.dll'), '?closeMessage@CGlobalMessageDialog@XP@@SAXXZ', 'void', [])();
  const closed = !isVisible(getRoot(hwnd));
  return {outcome: closed ? 'closed' : 'close_failed', closed};
});
rpc.exports.strategystart = (hwnd, expected) => onGui(hwnd, () => {
  // Re-read on the same GUI turn as the mutation. Cached IDs are insufficient.
  const snapshot = strategySnapshot(getRoot(hwnd));
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
  if (!snapshot.whitelist_ready) return {outcome: 'waiting_whitelist', requested: false};
  // Empty MSVC x64 release std::string (SSO). Allowed only on the tested build.
  const reason = Memory.alloc(32);
  reason.writeByteArray(new Uint8Array(32));
  reason.add(24).writeU64(15);
  strategyRun(strategyManager(), Number(model.id), reason);
  return {outcome: 'start_requested', requested: true};
});
