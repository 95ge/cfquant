'use strict';

// Windows x64 iptypes.h layouts. Only buffers returned to this QMT's utils.dll
// are changed; the OS interfaces and all other processes retain their own data.
const macLayouts = {
  GetAdaptersInfo: {bufferArg: 0, sizeArg: 1, next: 0, length: 404, address: 408, minimum: 416},
  GetAdaptersAddresses: {bufferArg: 3, sizeArg: 4, next: 8, length: 88, address: 80, minimum: 92}
};
const macListeners = [];
const macCalls = {};

function rewriteMacList(buffer, size, layout, bytes) {
  if (buffer.isNull() || size < layout.minimum || size > 16 * 1024 * 1024) {
    throw new Error('Invalid adapter buffer bounds');
  }
  const end = buffer.add(size);
  const seen = new Set();
  const addresses = [];
  let node = buffer;
  while (!node.isNull()) {
    if (seen.size >= 512 || seen.has(node.toString()) || node.compare(buffer) < 0 ||
        node.add(layout.minimum).compare(end) > 0) {
      throw new Error('Invalid adapter linked list');
    }
    seen.add(node.toString());
    if (layout === macLayouts.GetAdaptersAddresses &&
        (node.readU32() < layout.minimum || node.add(node.readU32()).compare(end) > 0)) {
      throw new Error('Unexpected IP_ADAPTER_ADDRESSES length');
    }
    const length = node.add(layout.length).readU32();
    if (length > 8) throw new Error('Invalid hardware address length');
    if (length === 6) addresses.push(node.add(layout.address));
    node = node.add(layout.next).readPointer();
  }
  // Validate the whole result before making changes.
  for (const address of addresses) address.writeByteArray(bytes);
  return addresses.length;
}

function disposeMac() {
  for (const listener of macListeners) listener.detach();
  macListeners.length = 0;
}

rpc.exports.configuremac = function (directory, mac) {
  if (Process.platform !== 'windows' || Process.arch !== 'x64') throw new Error('Windows x64 required');
  if (macListeners.length) throw new Error('MAC listeners already installed');
  if (!/^(?:[0-9A-F]{2}-){5}[0-9A-F]{2}$/.test(mac)) throw new Error('Invalid MAC format');
  const bytes = mac.split('-').map(value => parseInt(value, 16));
  if ((bytes[0] & 1) || bytes.every(value => value === 0)) throw new Error('Unicast MAC required');
  const normalize = value => value.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
  const expected = normalize(directory) + '\\utils.dll';
  const iphlp = Process.getModuleByName('iphlpapi.dll');
  iphlp.ensureInitialized();
  try {
    for (const [name, layout] of Object.entries(macLayouts)) {
      macCalls[name] = 0;
      macListeners.push(Interceptor.attach(iphlp.getExportByName(name), {
        onEnter(args) {
          const caller = Process.findModuleByAddress(this.returnAddress);
          this.applies = Boolean(caller && normalize(caller.path) === expected);
          if (!this.applies) return;
          this.buffer = args[layout.bufferArg];
          this.sizePointer = args[layout.sizeArg];
          this.capacity = this.sizePointer.isNull() ? 0 : this.sizePointer.readU32();
        },
        onLeave(retval) {
          if (!this.applies || retval.toUInt32() !== 0 || this.buffer.isNull() || this.sizePointer.isNull()) return;
          try {
            const size = Math.min(this.capacity, this.sizePointer.readU32());
            const count = rewriteMacList(this.buffer, size, layout, bytes);
            macCalls[name]++;
            if (macCalls[name] === 1) send({event: 'mac_override', api: name, adapters: count});
          } catch (error) {
            send({event: 'mac_error', api: name, detail: String(error)});
          }
        }
      }));
    }
    return {ready: true, apis: Object.keys(macLayouts)};
  } catch (error) {
    disposeMac();
    throw error;
  }
};
rpc.exports.macstatus = function () { return {active: macListeners.length === 2, calls: macCalls}; };
rpc.exports.disposemac = disposeMac;
