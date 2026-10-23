"""Restart the monitor after crashes or missing heartbeats while this runtime lives."""
import fcntl
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

LOG = logging.getLogger('supervisor')


def stop_child(child):
    if child.poll() is not None:
        return
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def supervise(command, directory, stop=None, heartbeat_timeout=900, poll_seconds=5,
              restart_delay=5, max_starts=None):
    stop = stop or threading.Event()
    directory = Path(directory)
    heartbeat = directory / 'monitor-judge.heartbeat'
    starts = 0
    delay = restart_delay
    while not stop.is_set() and (max_starts is None or starts < max_starts):
        started = time.time()
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
        (directory / 'monitor-judge.pid').write_text(str(child.pid))
        starts += 1
        LOG.info('Started monitor pid=%s', child.pid)
        try:
            while child.poll() is None and not stop.wait(poll_seconds):
                try:
                    last = max(started, heartbeat.stat().st_mtime)
                except FileNotFoundError:
                    last = started
                if time.time() - last > heartbeat_timeout:
                    LOG.error('No heartbeat for %ss; restarting monitor pid=%s', heartbeat_timeout, child.pid)
                    stop_child(child)
                    break
        finally:
            stop_child(child)
        LOG.warning('Monitor exited pid=%s code=%s', child.pid, child.returncode)
        if stop.is_set():
            break
        if time.time() - started > 1800:
            delay = restart_delay
        LOG.info('Restart delay %ss', delay)
        if stop.wait(delay):
            break
        delay = min(delay * 2, 300)


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    directory = root / '.local'
    directory.mkdir(exist_ok=True)
    handler = RotatingFileHandler(directory / 'supervisor.log', maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s UTC %(levelname)s %(message)s'))
    handler.formatter.converter = time.gmtime
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with open(directory / 'supervisor.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Supervisor already running')
        # Refuse to compete with a monitor launched outside this supervisor.
        with open(directory / 'monitor-judge.lock', 'a') as monitor_lock:
            try:
                fcntl.flock(monitor_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit('Monitor already running; stop it before starting supervisor')
        (directory / 'supervisor.pid').write_text(str(os.getpid()))
        LOG.info('Supervisor started pid=%s; no boot auto-start is implied', os.getpid())
        supervise([sys.executable, '-u', str(root / 'monitor_judge.py'), '--loop'], directory, stop)
        LOG.info('Supervisor stopped')


if __name__ == '__main__':
    main()
