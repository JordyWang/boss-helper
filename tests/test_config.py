import os
import tempfile
import unittest

from boss.config import ConfigError, load_config


class ConfigTest(unittest.TestCase):
    def _load(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        try:
            handle.write(text)
            handle.close()
            return load_config(handle.name)
        finally:
            try:
                os.unlink(handle.name)
            except FileNotFoundError:
                pass

    def test_string_false_is_false_and_paths_are_loaded(self):
        cfg = self._load(
            """
greeting:
  send_manual: "false"
safety:
  records_db: ""
  state_path: "tmp/state.json"
"""
        )
        self.assertFalse(cfg.greeting.send_manual)
        self.assertEqual(cfg.safety.records_db, "")
        self.assertEqual(cfg.safety.state_path, "tmp/state.json")

    def test_invalid_section_is_reported(self):
        with self.assertRaises(ConfigError):
            self._load("limits: nope\n")

    def test_invalid_yaml_is_reported(self):
        with self.assertRaises(ConfigError):
            self._load("limits: [broken\n")


if __name__ == "__main__":
    unittest.main()
