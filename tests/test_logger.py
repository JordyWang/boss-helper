import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from boss.artifacts import RunArtifacts
from boss.logger import close_logger, setup_logger


class LoggerTest(unittest.TestCase):
    def test_log_is_written_to_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = RunArtifacts.create(tmp)
            logger_name = "test-run-logger"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                logger = setup_logger(logger_name, artifacts)
                logger.info("hello run")
                close_logger(logger_name)
            self.assertIn("hello run", Path(artifacts.log_path).read_text(encoding="utf-8"))
            self.assertFalse(Path(tmp, ".run.lock").exists())


if __name__ == "__main__":
    unittest.main()
