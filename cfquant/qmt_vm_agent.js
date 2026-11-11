'use strict';

// Predicate identity is resolved from the target files, not a version or fixed RVA.
// Keep the original config getter and hardware/identity collectors intact.
const hookSpecs = [
  {
    id: 'login_gate', module: 'User.dll',
    args: [], result: false
  },
  {
    id: 'runtime_gate', module: 'utils.dll',
    args: ['pointer', 'pointer'], result: true
  }
];
const installed = new Map();

function bytesHex(address, length) {
  return Array.from(new Uint8Array(address.readByteArray(length)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
}

function replaceGate(address, spec) {
  if (installed.has(spec.id)) throw new Error('Duplicate hook: ' + spec.id);
  if (bytesHex(address, spec.prefix.length / 2) !== spec.prefix) {
    throw new Error('Unexpected or not-yet-unpacked function: ' + spec.id);
  }
  const entry = {address, calls: 0, callback: null};
  entry.callback = new NativeCallback(function () {
    entry.calls++;
    if (entry.calls === 1) send({event: 'first_call', hook: spec.id});
    // The caller only consumes the runtime reason string on a false return.
    // Leave the caller-owned C++ objects entirely untouched.
    // Frida's native bool ABI expects numeric 0/1 in this Windows build.
    return spec.result ? 1 : 0;
  }, 'bool', spec.args);
  Interceptor.replace(address, entry.callback);
  installed.set(spec.id, entry);
}

function dispose() {
  for (const entry of installed.values()) Interceptor.revert(entry.address);
  Interceptor.flush();
  installed.clear();
}

function status() {
  return {
    ready: hookSpecs.every(spec => installed.has(spec.id)),
    hooks: Array.from(installed, ([id, entry]) => ({id, calls: entry.calls}))
  };
}

function initializeTargets(directory, discovered, findModule) {
    if (Process.platform !== 'windows' || Process.arch !== 'x64') {
      throw new Error('This build requires Windows x64');
    }
    if (installed.size !== 0) throw new Error('Already initialized');
    if (!Array.isArray(discovered) || discovered.length !== hookSpecs.length ||
        new Set(discovered.map(item => item.id)).size !== hookSpecs.length) {
      throw new Error('Expected exactly two distinct discovered predicates');
    }
    const normalize = value => value.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
    const root = normalize(directory);
    try {
      const resolved = [];
      // Validate both targets before replacing either function.
      for (const spec of hookSpecs) {
        const target = discovered.find(item => item.id === spec.id);
        if (!target || target.module !== spec.module ||
            !Number.isSafeInteger(target.rva) || target.rva < 0 ||
            typeof target.prefix !== 'string' || !/^(?:[0-9a-f]{2}){16,}$/.test(target.prefix)) {
          throw new Error('Invalid discovered target: ' + spec.id);
        }
        const module = findModule(spec.module);
        if (normalize(module.path) !== root + '\\' + spec.module.toLowerCase()) {
          throw new Error('Unexpected module location: ' + spec.module);
        }
        module.ensureInitialized();
        if (target.rva + target.prefix.length / 2 > module.size) {
          throw new Error('Target outside module: ' + spec.id);
        }
        const address = module.base.add(target.rva);
        if (target.symbol && !address.equals(module.getExportByName(target.symbol))) {
          throw new Error('Unexpected export address: ' + spec.module);
        }
        const range = Process.findRangeByAddress(address);
        if (!range || !range.protection.includes('x') ||
            address.add(target.prefix.length / 2).compare(range.base.add(range.size)) > 0 ||
            bytesHex(address, target.prefix.length / 2) !== target.prefix) {
          throw new Error('Memory entry differs from identified file: ' + spec.id);
        }
        resolved.push({address, spec: {...spec, prefix: target.prefix}});
      }
      for (const target of resolved) replaceGate(target.address, target.spec);
      Interceptor.flush();
      return status();
    } catch (error) {
      dispose();
      throw error;
    }
}

rpc.exports = {
  initialize(directory, discovered) {
    return initializeTargets(directory, discovered, name => Process.getModuleByName(name));
  },
  status,
  dispose
};
