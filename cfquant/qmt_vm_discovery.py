"""Read-only discovery of the known QMT predicates, independent of versions."""
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

import pefile


# Mask address-dependent displacements, preserving the complete control flow.
LOGIN_PATTERN = (
    '48 83 ec 28 80 3d ?? ?? ?? ?? 00 75 0c e8 ?? ?? ?? ?? '
    'c6 05 ?? ?? ?? ?? 01 e8 ?? ?? ?? ?? 85 c0 75 17 '
    'e8 ?? ?? ?? ?? 85 c0 75 0e e8 ?? ?? ?? ?? 85 c0 75 05 '
    '48 83 c4 28 c3 b0 01 48 83 c4 28 c3'
)
LOGIN_REGEX = re.compile(b''.join(
    b'.' if token == '??' else re.escape(bytes([int(token, 16)]))
    for token in LOGIN_PATTERN.split()
), re.DOTALL)
RUNTIME_SYMBOL = (
    '?detectVMEnv@utils@@YA_NAEBV?$set@V?$basic_string@DU?$char_traits@D@std@@'
    'V?$allocator@D@2@@std@@U?$less@V?$basic_string@DU?$char_traits@D@std@@'
    'V?$allocator@D@2@@std@@@2@V?$allocator@V?$basic_string@DU?$char_traits@D@std@@'
    'V?$allocator@D@2@@std@@@2@@std@@AEAV?$basic_string@DU?$char_traits@D@std@@'
    'V?$allocator@D@2@@3@@Z'
)


class Image:
    def __init__(self, path):
        pe = pefile.PE(str(path))
        try:
            if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b:
                raise RuntimeError('{} 必须是 Windows x64 程序。'.format(path.name))
            self.name = path.name
            section_names = {section.Name.rstrip(b'\0') for section in pe.sections}
            self.is_upx_packed = {b'UPX0', b'UPX1'}.issubset(section_names)
            self.was_upx = False
            self.data = pe.get_memory_mapped_image()
            self.functions = {
                entry.struct.BeginAddress: entry.struct.EndAddress
                for entry in getattr(pe, 'DIRECTORY_ENTRY_EXCEPTION', [])
            }
            self.sections = [
                (section.VirtualAddress,
                 section.VirtualAddress + section.Misc_VirtualSize,
                 section.Characteristics)
                for section in pe.sections
            ]
            self.exports = [
                (symbol.name, symbol.address, symbol.forwarder)
                for symbol in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', [])
            ]
            self.version = None
            fixed = getattr(pe, 'VS_FIXEDFILEINFO', [])
            if fixed:
                ms, ls = fixed[0].FileVersionMS, fixed[0].FileVersionLS
                self.version = '{}.{}.{}.{}'.format(ms >> 16, ms & 65535, ls >> 16, ls & 65535)
        finally:
            pe.close()

    def executable(self, rva, length=1):
        return any(start <= rva and rva + length <= end and flags & 0x20000000
                   for start, end, flags in self.sections)

    def writable(self, rva):
        return any(start <= rva < end and flags & 0x80000000
                   for start, end, flags in self.sections)

    def relative_target(self, rva, operand_offset, instruction_size):
        return rva + instruction_size + struct.unpack_from('<i', self.data, rva + operand_offset)[0]

    def body(self, rva):
        end = self.functions.get(rva)
        if end is None or end <= rva or end > len(self.data) or not self.executable(rva, end - rva):
            return b''
        return self.data[rva:end]


def find_login(image):
    candidates = set()
    for start, end, flags in image.sections:
        if not flags & 0x20000000:
            continue
        for match in LOGIN_REGEX.finditer(image.data, start, end):
            rva = match.start()
            if image.functions.get(rva) != rva + 64:
                continue
            # Both accesses must reference the same writable initialization flag.
            flag = image.relative_target(rva + 4, 2, 7)
            if flag != image.relative_target(rva + 18, 2, 7) or not image.writable(flag):
                continue
            calls = [image.relative_target(rva + offset, 1, 5) for offset in (13, 25, 34, 43)]
            bodies = [image.body(target) for target in calls]
            if not all(bodies) or len(set(calls)) != 4:
                continue
            # Identify firmware checks, not just an unrelated three-way boolean wrapper.
            if b'\xb9\x49\x50\x43\x41' not in bodies[1]:
                continue
            if b'\xb9\x42\x4d\x53\x52' not in bodies[2]:
                continue
            candidates.add(rva)
    if len(candidates) != 1:
        raise RuntimeError('User.dll 登录检测函数无法唯一识别（匹配 {} 处）；'
                           '当前检测实现需要适配，未按版本号拒绝。'.format(len(candidates)))
    rva = candidates.pop()
    return {'id': 'login_gate', 'module': image.name, 'rva': rva,
            'prefix': image.data[rva:rva + 64].hex(), 'method': 'signature+firmware-calls'}


def find_runtime(image):
    matches = [(rva, forwarder) for name, rva, forwarder in image.exports
               if name == RUNTIME_SYMBOL.encode('ascii')]
    if len(matches) != 1 or matches[0][1] is not None:
        raise RuntimeError('utils.dll 未找到唯一且签名匹配的 detectVMEnv 导出函数。')
    rva = matches[0][0]
    body = image.body(rva)
    if len(body) < 16:
        raise RuntimeError('utils.dll 的 detectVMEnv 不是可识别的 x64 函数入口。')
    return {'id': 'runtime_gate', 'module': image.name, 'rva': rva,
            'prefix': body[:16].hex(), 'symbol': RUNTIME_SYMBOL, 'method': 'export'}


def locate_upx(explicit=None):
    if explicit is not None:
        candidate = Path(explicit).resolve()
        if not candidate.is_file():
            raise RuntimeError('指定的 UPX 工具不存在：{}'.format(candidate))
        return candidate
    bundled = Path(__file__).resolve().parent / 'tools' / 'upx' / 'upx.exe'
    if bundled.is_file():
        return bundled
    installed = shutil.which('upx')
    if installed:
        return Path(installed).resolve()
    raise RuntimeError('检测到 UPX 压缩的 QMT 文件；请保留 cfquant/tools/upx 目录，'
                       '或在系统 PATH 中安装 upx.exe。只会解压临时副本。')


def load_image(path, upx=None):
    image = Image(path)
    if not image.is_upx_packed:
        return image
    tool = locate_upx(upx)
    # Both command-line paths stay in this private temporary directory. The
    # original installation is never passed to UPX or overwritten by it.
    with tempfile.TemporaryDirectory(prefix='qmt_vm_upx_') as scratch:
        root = Path(scratch)
        source = root / 'packed' / path.name
        target = root / 'unpacked' / path.name
        source.parent.mkdir()
        target.parent.mkdir()
        shutil.copyfile(path, source)
        result = subprocess.run(
            [str(tool), '-d', '-q', '-o', str(target), str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0 or not target.is_file():
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError('{} 的 UPX 临时副本解压失败：{}'.format(path.name, detail))
        unpacked = Image(target)
        if unpacked.is_upx_packed:
            raise RuntimeError('{} 解压后仍有 UPX 压缩标记，停止识别。'.format(path.name))
        unpacked.was_upx = True
        return unpacked


def inspect_client(directory, upx=None):
    executable = load_image(directory / 'XtItClient.exe', upx)
    user = load_image(directory / 'User.dll', upx)
    utils = load_image(directory / 'utils.dll', upx)
    return {'client_version': executable.version, 'targets_identified': True,
            'unpacked_modules': [image.name for image in (executable, user, utils) if image.was_upx],
            'hooks': [find_login(user), find_runtime(utils)]}
