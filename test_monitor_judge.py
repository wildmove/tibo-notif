import sqlite3
import unittest
from unittest.mock import Mock
from monitor_judge import cycle


class MonitorTests(unittest.TestCase):
    def test_latest_first_no_repeated_call_then_new_full_text(self):
        db = sqlite3.connect(':memory:')
        judge = Mock()
        judge.evaluate.return_value = {'verdict': 'uncertain', 'reason': 'test', 'evidence': ''}
        fetch = Mock(return_value=[{'id': '1', 'text': 'old'}, {'id': '2', 'text': 'latest full text'}])
        cycle(db, judge, fetch)
        judge.evaluate.assert_called_once_with({'id': '2', 'text': 'latest full text'})
        cycle(db, judge, fetch)
        self.assertEqual(judge.evaluate.call_count, 1)
        fetch.return_value += [{'id': '3', 'text': 'new full text'}]
        cycle(db, judge, fetch)
        judge.evaluate.assert_called_with({'id': '3', 'text': 'new full text'})

    def test_failed_judgment_remains_pending(self):
        db = sqlite3.connect(':memory:')
        judge = Mock()
        judge.evaluate.side_effect = RuntimeError('budget reached')
        with self.assertRaises(RuntimeError):
            cycle(db, judge, lambda: [{'id': '1', 'text': 'post'}])
        self.assertIsNone(db.execute('SELECT verdict FROM queue').fetchone()[0])
