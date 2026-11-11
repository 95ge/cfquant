"""Discovery regression tests with synthetic images; no QMT process is used."""
import struct
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cfquant.qmt_vm_discovery import Image, RUNTIME_SYMBOL, find_login, find_runtime, load_image, locate_upx


def sample_image(login_rva=0x1200, runtime_rva=0x1800):
    image = Image.__new__(Image)
    image.name = 'User.dll'
    image.sections = [(0x1000, 0x3000, 0x60000020), (0x4000, 0x5000, 0xc0000040)]
    image.functions = {}
    image.exports = [(RUNTIME_SYMBOL.encode('ascii'), runtime_rva, None)]
    data = bytearray(0x5000)
    # A relocation of the original wrapper with four distinct direct callees.
    body = bytes.fromhex(
        '4883ec28803d0000000000750ce800000000c6050000000001'
        'e80000000085c07517e80000000085c0750ee80000000085c07505'
        '4883c428c3b0014883c428c3')
    data[login_rva:login_rva + len(body)] = body
    image.functions[login_rva] = login_rva + len(body)
    for position in (4, 18):
        struct.pack_into('<i', data, login_rva + position + 2, 0x4100 - (login_rva + position + 7))
    for index, offset in enumerate((13, 25, 34, 43)):
        target = login_rva + 0x100 + index * 0x40
        struct.pack_into('<i', data, login_rva + offset + 1, target - (login_rva + offset + 5))
        code = (b'\xb9\x49\x50\x43\x41' if index == 1 else
                b'\xb9\x42\x4d\x53\x52' if index == 2 else b'\x31\xc0') + b'\xc3'
        data[target:target + len(code)] = code
        image.functions[target] = target + len(code)
    data[runtime_rva:runtime_rva + 32] = bytes.fromhex('4889c8') + b'\x90' * 28 + b'\xc3'
    image.functions[runtime_rva] = runtime_rva + 32
    image.data = bytes(data)
    return image


class DiscoveryTests(unittest.TestCase):
    def test_changed_addresses_and_runtime_prologue(self):
        for login_rva, runtime_rva in ((0x1200, 0x1800), (0x2100, 0x2800)):
            with self.subTest(login=login_rva, runtime=runtime_rva):
                image = sample_image(login_rva, runtime_rva)
                self.assertEqual(find_login(image)['rva'], login_rva)
                image.name = 'utils.dll'
                runtime = find_runtime(image)
                self.assertEqual(runtime['rva'], runtime_rva)
                self.assertEqual(runtime['prefix'], image.data[runtime_rva:runtime_rva + 16].hex())

    def test_duplicate_valid_login_candidates_rejected(self):
        first, second = sample_image(), sample_image(0x2100, 0x2800)
        data = bytearray(first.data)
        data[0x2100:0x2400] = second.data[0x2100:0x2400]
        first.functions.update(second.functions)
        first.data = bytes(data)
        with self.assertRaises(RuntimeError):
            find_login(first)

    def test_generic_boolean_wrapper_without_firmware_checks_rejected(self):
        image = sample_image()
        image.data = image.data.replace(b'\xb9\x49\x50\x43\x41', b'\xb9\x00\x00\x00\x00')
        with self.assertRaises(RuntimeError):
            find_login(image)

    def test_changed_initialization_flag_rejected(self):
        image = sample_image()
        data = bytearray(image.data)
        struct.pack_into('<i', data, 0x1200 + 20, 0x4200 - (0x1200 + 25))
        image.data = bytes(data)
        with self.assertRaises(RuntimeError):
            find_login(image)

    def test_match_inside_another_function_rejected(self):
        image = sample_image()
        image.functions[0x11f0] = image.functions.pop(0x1200)
        with self.assertRaises(RuntimeError):
            find_login(image)

    def test_changed_control_flow_rejected(self):
        image = sample_image()
        data = bytearray(image.data)
        data[0x1200 + 32] = 0x74
        image.data = bytes(data)
        with self.assertRaises(RuntimeError):
            find_login(image)

    def test_runtime_export_identity_and_forwarder(self):
        for exports in ([], [(b'wrong_signature', 0x1800, None)],
                        [(RUNTIME_SYMBOL.encode('ascii'), 0x1800, b'other.function')]):
            with self.subTest(exports=exports):
                image = sample_image()
                image.exports = exports
                with self.assertRaises(RuntimeError):
                    find_runtime(image)

    def test_nonexecutable_runtime_target_rejected(self):
        image = sample_image()
        image.exports = [(RUNTIME_SYMBOL.encode('ascii'), 0x4100, None)]
        image.functions[0x4100] = 0x4120
        with self.assertRaises(RuntimeError):
            find_runtime(image)


class UnpackingTests(unittest.TestCase):
    def test_plain_image_does_not_require_upx(self):
        image = SimpleNamespace(is_upx_packed=False)
        with patch('cfquant.qmt_vm_discovery.Image', return_value=image), patch('cfquant.qmt_vm_discovery.locate_upx') as tool:
            self.assertIs(load_image(Path('User.dll')), image)
            tool.assert_not_called()

    def test_only_temporary_copies_are_passed_to_upx(self):
        with tempfile.TemporaryDirectory() as scratch:
            original = Path(scratch) / 'User.dll'
            original.write_bytes(b'original packed file')
            temporary_paths = []

            def parse_image(path):
                packed = path.read_bytes() == b'original packed file'
                return SimpleNamespace(name=path.name, is_upx_packed=packed, was_upx=False)

            def unpack(command, **kwargs):
                output, source = Path(command[-2]), Path(command[-1])
                self.assertNotEqual(source, original)
                self.assertNotEqual(output, original)
                self.assertEqual(source.read_bytes(), original.read_bytes())
                self.assertEqual(source.parent.parent, output.parent.parent)
                temporary_paths.extend([source, output])
                output.write_bytes(b'unpacked image')
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch('cfquant.qmt_vm_discovery.Image', side_effect=parse_image), \
                    patch('cfquant.qmt_vm_discovery.locate_upx', return_value=Path('upx.exe')), \
                    patch('cfquant.qmt_vm_discovery.subprocess.run', side_effect=unpack):
                result = load_image(original)
            self.assertTrue(result.was_upx)
            self.assertEqual(original.read_bytes(), b'original packed file')
            self.assertTrue(all(not path.exists() for path in temporary_paths))

    def test_failed_unpack_preserves_original(self):
        with tempfile.TemporaryDirectory() as scratch:
            original = Path(scratch) / 'User.dll'
            original.write_bytes(b'original')
            with patch('cfquant.qmt_vm_discovery.Image', return_value=SimpleNamespace(is_upx_packed=True)), \
                    patch('cfquant.qmt_vm_discovery.locate_upx', return_value=Path('upx.exe')), \
                    patch('cfquant.qmt_vm_discovery.subprocess.run',
                          return_value=subprocess.CompletedProcess([], 1, '', 'unsupported input')):
                with self.assertRaisesRegex(RuntimeError, 'unsupported input'):
                    load_image(original)
            self.assertEqual(original.read_bytes(), b'original')

    def test_missing_explicit_upx_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(RuntimeError):
                locate_upx(Path(scratch) / 'missing.exe')


if __name__ == '__main__':
    unittest.main()
