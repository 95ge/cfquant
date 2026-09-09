# -*- coding: utf-8 -*-
"""Offline checks only; no QMT connection, subscription, or order is created."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import pandas as pd


SOURCE = Path(__file__).with_name("18_高级模式实机联调.py")
SPEC = importlib.util.spec_from_file_location("advanced_integration_runner", SOURCE)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class IntegrationVerdictTests(unittest.TestCase):
    def test_output_directory_preserves_existing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            RUNNER.check_output_directory(directory)
            RUNNER.check_output_directory(directory / "new")
            existing = directory / "evidence.json"
            existing.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                RUNNER.check_output_directory(directory)
            with self.assertRaises(ValueError):
                RUNNER.check_output_directory(existing)
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")

    def test_empty_data_is_not_pass(self):
        for value in (None, {}, [], {"000001.SZ": {}}, {"000001.SZ": pd.DataFrame()}):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(RUNNER.nonempty(value)[0], "UNVERIFIED")

    def test_nonempty_frame_is_observed_as_data(self):
        self.assertEqual(RUNNER.nonempty({"000001.SZ": pd.DataFrame({"close": [11.6]})})[0], "PASS")

    def test_zero_is_valid_data(self):
        self.assertEqual(RUNNER.nonempty({"volume": 0})[0], "PASS")

    def test_historical_list_is_not_semantic_pass(self):
        self.assertEqual(RUNNER.history_observation(["000001.SZ"])[0], "OBSERVED")
        self.assertEqual(RUNNER.history_observation([])[0], "UNVERIFIED")

    def test_sync_callback_is_partial(self):
        value = [{"before_return": True, "thread": "MainThread", "valid": True}]
        self.assertEqual(RUNNER.query_callback_semantics(value)[0], "PARTIAL")

    def test_different_thread_is_not_labeled_sync_mainthread(self):
        value = [{"before_return": False, "thread": "worker", "valid": True}]
        self.assertEqual(RUNNER.query_callback_semantics(value)[0], "OBSERVED")

    def test_missing_invalid_or_duplicate_callback_fails(self):
        valid = {"before_return": True, "thread": "MainThread", "valid": True}
        invalid = dict(valid, valid=False)
        for value in ([], [invalid], [valid, valid]):
            self.assertEqual(RUNNER.query_callback_semantics(value)[0], "FAIL")


if __name__ == "__main__":
    unittest.main()
