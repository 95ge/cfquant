
rpc.exports.compaterror = function () { throw new Error('expected compatibility test error'); };
rpc.exports.selftest = function () {
    function check(ok, detail) { if (!ok) throw new Error(detail); }
    const page = Memory.alloc(Process.pageSize);
    check(Memory.protect(page, Process.pageSize, 'rwx'), 'executable allocation');
    const configAddress = page;
    configAddress.writeByteArray([0x0f,0xb6,0x81,0x10,0x08,0x00,0x00,0xc3,...Array(24).fill(0xcc)]);
    const loginAddress = page.add(256);
    loginAddress.writeByteArray([...Array(16).fill(0x90),0xb0,0x01,0xc3,...Array(32).fill(0xcc)]);
    const runtimeAddress = page.add(512);
    runtimeAddress.writeByteArray([...Array(16).fill(0x90),0xc6,0x02,0xee,0x31,0xc0,0xc3,...Array(32).fill(0xcc)]);
    const readConfig = new NativeFunction(configAddress, 'bool', ['pointer']);
    const login = new NativeFunction(loginAddress, 'bool', []);
    const runtime = new NativeFunction(runtimeAddress, 'bool', ['pointer', 'pointer']);
    const config = Memory.alloc(0x820);
    config.add(0x810).writeU8(1);
    const reason = Memory.alloc(32);
    check(Boolean(readConfig(config)), 'baseline config getter');
    check(Boolean(login()), 'baseline login');
    check(!Boolean(runtime(ptr(0), reason)) && reason.readU8() === 0xee, 'baseline runtime');
    reason.writeByteArray(Array(32).fill(0x5a));
    const discovered = [
        {id: 'login_gate', module: 'User.dll', rva: 256, prefix: bytesHex(loginAddress, 16)},
        {id: 'runtime_gate', module: 'utils.dll', rva: 512, prefix: bytesHex(runtimeAddress, 16),
         symbol: 'test_runtime_export'}
    ];
    const testModule = function (name) {
        check(name === 'User.dll' || name === 'utils.dll', 'known test module');
        return {base: page, size: Process.pageSize, path: 'C:\\qmt-test\\' + name,
                ensureInitialized() {}, getExportByName(symbol) {
                    check(symbol === 'test_runtime_export', 'runtime export identity');
                    return runtimeAddress;
                }};
    };
    let mismatchRejected = false;
    try {
        initializeTargets('C:\\qmt-test',
            [discovered[0], {...discovered[1], prefix: '00'.repeat(16)}], testModule);
    } catch (_) { mismatchRejected = true; }
    check(mismatchRejected && installed.size === 0 && Boolean(login()),
          'second target mismatch leaves first target unchanged');
    let duplicateRejected = false;
    try { initializeTargets('C:\\qmt-test', [discovered[0], discovered[0]], testModule); }
    catch (_) { duplicateRejected = true; }
    check(duplicateRejected && installed.size === 0, 'duplicate targets rejected');
    check(initializeTargets('C:\\qmt-test', discovered, testModule).ready,
          'install at discovered offsets with export lookup');
    Interceptor.flush();
    check(status().ready, 'two gates ready');
    check(!Boolean(login()), 'login bypass result');
    check(Boolean(readConfig(config)) && config.add(0x810).readU8() === 1, 'config getter and value untouched');
    check(Boolean(runtime(ptr(0), reason)), 'runtime bypass result');
    check(bytesHex(reason, 32) === '5a'.repeat(32), 'caller string untouched');
    check(installed.get('login_gate').calls === 1 && installed.get('runtime_gate').calls === 1, 'real intercepted calls');
    dispose();
    check(!status().ready && status().hooks.length === 0, 'clean disposal');
    check(Boolean(login()), 'login restored');
    check(!Boolean(runtime(ptr(0), reason)) && reason.readU8() === 0xee, 'runtime restored');
    let rejected = false;
    try { replaceGate(loginAddress, {...hookSpecs[0], prefix: '00000000'}); }
    catch (_) { rejected = true; }
    check(rejected && installed.size === 0 && Boolean(login()), 'unexpected code rejected without changes');
    return {native_hook_install: true, login_result: false, runtime_result: true,
            login_config_unchanged: true,
            caller_string_unchanged: true, unhook_restores_original: true,
            unexpected_code_rejected: true, discovered_offsets_used: true,
            memory_mismatch_rejected_before_hooking: true, duplicate_targets_rejected: true};
};


rpc.exports.mactest = function () {
    function check(ok, detail) { if (!ok) throw new Error(detail); }
    const mac = [2, 17, 34, 51, 68, 85];
    for (const [name, layout] of Object.entries(macLayouts)) {
        const stride = name === 'GetAdaptersInfo' ? 704 : 256;
        const buffer = Memory.alloc(stride * 2);
        buffer.writeByteArray(Array(stride * 2).fill(0xa5));
        const second = buffer.add(stride);
        buffer.add(layout.next).writePointer(second);
        second.add(layout.next).writePointer(ptr(0));
        if (name === 'GetAdaptersAddresses') {
            buffer.writeU32(stride); second.writeU32(stride);
        }
        buffer.add(layout.length).writeU32(6);
        second.add(layout.length).writeU32(8);
        const before = new Uint8Array(buffer.readByteArray(stride * 2));
        check(rewriteMacList(buffer, stride * 2, layout, mac) === 1, 'six-byte MACs only');
        const after = new Uint8Array(buffer.readByteArray(stride * 2));
        for (let i = 0; i < after.length; i++) {
            const expected = i >= layout.address && i < layout.address + 6
                ? mac[i - layout.address] : before[i];
            check(after[i] === expected, 'only hardware-address bytes changed: ' + name);
        }
        second.add(layout.next).writePointer(buffer);
        buffer.add(layout.address).writeByteArray(Array(6).fill(0x77));
        let rejected = false;
        try { rewriteMacList(buffer, stride * 2, layout, mac); } catch (_) { rejected = true; }
        check(rejected && bytesHex(buffer.add(layout.address), 6) === '77'.repeat(6),
              'cycle rejected before modifying any result');
    }
    const iphlp = Module.load('iphlpapi.dll');
    const getInfo = new NativeFunction(iphlp.getExportByName('GetAdaptersInfo'), 'uint', ['pointer', 'pointer']);
    const size = Memory.alloc(4); size.writeU32(0);
    const initial = getInfo(ptr(0), size);
    check(initial === 111 || initial === 232, 'adapter-size query');
    rpc.exports.configuremac('C:\\qmt-test', '02-11-22-33-44-55');
    if (initial === 111) {
        const result = Memory.alloc(size.readU32());
        check(getInfo(result, size) === 0, 'real adapter API remains usable');
    }
    check(macCalls.GetAdaptersInfo === 0 && macCalls.GetAdaptersAddresses === 0,
          'calls from outside target utils.dll remain untouched');
    disposeMac();
    check(macListeners.length === 0, 'MAC hooks detached');
    return {adapter_layouts_verified: true, other_buffer_fields_unchanged: true,
            invalid_lists_rejected: true, unrelated_callers_untouched: true, mac_hooks_detached: true};
};
