"""Source synchronization must stay correct with cached parsing and outputs."""

import ast
import json
from unittest.mock import patch

import pytest

from tools import sync_qmt_ast, sync_qmt_batch, sync_qmt_release


def test_parser_cache_tracks_source_and_python_grammar():
    sync_qmt_ast.parse_source.cache_clear()
    original = 'class Bridge:\n    def value(self):\n        return 1\n'
    changed = original.replace('return 1', 'return 2')
    assert sync_qmt_ast.parse_source(original) is sync_qmt_ast.parse_source(original)
    assert ast.dump(sync_qmt_ast.parse_source(changed)) != ast.dump(sync_qmt_ast.parse_source(original))
    modern = 'if (value := 1):\n    pass\n'
    sync_qmt_ast.parse_source(modern)
    with pytest.raises(SyntaxError):
        sync_qmt_ast.parse_source(modern, feature_version=(3, 6))


def test_method_replacement_uses_current_line_offsets():
    source = 'class TxTradeBridge:\n    def first(self):\n        return 1\n    def second(self):\n        return 2\n'
    result = sync_qmt_batch._replace_class_method(source, 'TxTradeBridge', 'first',
        '    def first(self):\n        value = 10\n        return value\n')
    result = sync_qmt_batch._replace_class_method(result, 'TxTradeBridge', 'second',
        '    def second(self):\n        return 20\n')
    namespace = {}
    exec(result, namespace)
    instance = namespace['TxTradeBridge']()
    assert (instance.first(), instance.second()) == (10, 20)


def test_sync_fingerprint_changes_for_inputs_and_outputs(tmp_path):
    (tmp_path / 'cfquant').mkdir()
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'qmt_scripts').mkdir()
    dependency = tmp_path / 'cfquant' / 'bridge.py'
    dependency.write_text('value = 1\n')
    tool = tmp_path / 'tools' / 'sync_qmt_batch.py'
    tool.write_text('value = 1\n')
    template = tmp_path / 'qmt_scripts' / 'CFQUANT_CTYPE_ALL_LOWLAT.py'
    template.write_text('value = 1\n')
    target = tmp_path / 'qmt_scripts' / 'CFQUANT_LITE.py'
    target.write_text('value = 1\n')
    previous = sync_qmt_release.fingerprint(tmp_path, [target])
    for path in (dependency, tool, template, target):
        path.write_text('value = 2\n')
        current = sync_qmt_release.fingerprint(tmp_path, [target])
        assert current != previous
        previous = current


def test_real_lite_outputs_match_and_cache_cannot_hide_edits(tmp_path):
    cache = tmp_path / 'sync.json'
    paths = sorted((sync_qmt_release.ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))
    before = {path: path.read_bytes() for path in paths}
    assert sync_qmt_release.synchronize(check=True, no_cache=True, cache=cache) == 0
    assert before == {path: path.read_bytes() for path in paths}
    with patch.object(sync_qmt_release.batch, 'updated_source', side_effect=AssertionError('cache miss')):
        assert sync_qmt_release.synchronize(check=True, cache=cache) == 0
        # An incorrect signature must not skip verification.
        cache.write_text(json.dumps({'fingerprint': 'outdated'}))
        with pytest.raises(AssertionError, match='cache miss'):
            sync_qmt_release.synchronize(check=True, cache=cache)


def test_check_rejects_stale_entry_without_writing(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'qmt_scripts').mkdir()
    original = next((sync_qmt_release.ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py')).read_bytes()
    target = root / 'qmt_scripts' / 'CFQUANT_LITE.py'
    target.write_bytes(original.replace(b'CORE_VERSION = "', b'CORE_VERSION = "stale-', 1))
    before = target.read_bytes()
    cache = tmp_path / 'state.json'
    assert sync_qmt_release.synchronize(check=True, root=root, cache=cache) == 1
    assert target.read_bytes() == before
    assert not cache.exists()
    assert sync_qmt_release.synchronize(root=root, cache=cache) == 0
    assert target.read_bytes() == original
