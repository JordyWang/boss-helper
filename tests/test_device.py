import json
import logging
import os
import tempfile
import time
import unittest

from boss.device import app_version, record_app_version, version_values_changed


class _Device:
    def __init__(self, version_name="14.160", version_code=1416010):
        self.version_name = version_name
        self.version_code = version_code

    def app_info(self, package):
        return {
            "versionName": self.version_name,
            "versionCode": self.version_code,
        }


class DeviceVersionTest(unittest.TestCase):
    def test_version_comparison_ignores_detection_metadata(self):
        current = {
            "package": "com.example.app",
            "version_name": "14.160",
            "version_code": 1416010,
        }
        same = dict(current, detected_at="later", previous={"version_name": "old"})
        self.assertFalse(version_values_changed(current, same))
        self.assertTrue(version_values_changed(None, current))

    def test_app_version_reads_installed_metadata(self):
        info = app_version(_Device(), "com.example.app")
        self.assertEqual(info["package"], "com.example.app")
        self.assertEqual(info["version_name"], "14.160")
        self.assertEqual(info["version_code"], 1416010)

    def test_baseline_is_written_once_and_only_changes_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state", "app_version.json")
            device = _Device()
            first = record_app_version(device, "com.example.app", path, logging.getLogger("test-device"))
            self.assertEqual(first["version_name"], "14.160")
            with open(path, "r", encoding="utf-8") as fh:
                first_data = json.load(fh)
            first_mtime = os.stat(path).st_mtime_ns

            time.sleep(0.002)
            second = record_app_version(device, "com.example.app", path, logging.getLogger("test-device"))
            self.assertEqual(second, first)
            self.assertEqual(os.stat(path).st_mtime_ns, first_mtime)

            device.version_name = "14.161"
            device.version_code = 1416011
            record_app_version(device, "com.example.app", path, logging.getLogger("test-device"))
            with open(path, "r", encoding="utf-8") as fh:
                updated = json.load(fh)
            self.assertEqual(updated["version_name"], "14.161")
            self.assertEqual(updated["previous"]["version_name"], "14.160")


if __name__ == "__main__":
    unittest.main()
