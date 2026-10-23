import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from supervise import supervise


class SupervisorTests(unittest.TestCase):
    def test_actual_crashed_child_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            count = Path(directory) / 'starts'
            code = f"from pathlib import Path; p=Path({str(count)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); raise SystemExit(1)"
            supervise([sys.executable, '-c', code], directory, poll_seconds=.01,
                      restart_delay=.01, max_starts=2)
            self.assertEqual(count.read_text(), 'xx')

    def test_actual_stalled_child_is_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            supervise([sys.executable, '-c', 'import time; time.sleep(60)'], directory,
                      heartbeat_timeout=.1, poll_seconds=.02, restart_delay=.01, max_starts=1)
            pid = int((Path(directory) / 'monitor-judge.pid').read_text())
            self.assertFalse(Path(f'/proc/{pid}').exists())
