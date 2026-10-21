import sqlite3
import unittest
from unittest.mock import Mock
from monitor_judge import cycle, mentions_reset


class MonitorTests(unittest.TestCase):
    def test_latest_first_no_repeated_call_then_new_full_text(self):
        db = sqlite3.connect(':memory:')
        judge = Mock()
        judge.evaluate.return_value = {'verdict': 'uncertain', 'reason': 'test', 'evidence': ''}
        fetch = Mock(return_value=[{'id': '1', 'text': 'old'}, {'id': '2', 'text': 'latest full reset text'}])
        cycle(db, judge, fetch)
        judge.evaluate.assert_called_once_with({'id': '2', 'text': 'latest full reset text'})
        cycle(db, judge, fetch)
        self.assertEqual(judge.evaluate.call_count, 1)
        fetch.return_value += [{'id': '3', 'text': 'new full reset text'}]
        cycle(db, judge, fetch)
        judge.evaluate.assert_called_with({'id': '3', 'text': 'new full reset text'})

    def test_failed_judgment_remains_pending(self):
        db = sqlite3.connect(':memory:')
        judge = Mock()
        judge.evaluate.side_effect = RuntimeError('budget reached')
        with self.assertRaises(RuntimeError):
            cycle(db, judge, lambda: [{'id': '1', 'text': 'reset post'}])
        self.assertIsNone(db.execute('SELECT verdict FROM queue').fetchone()[0])


    def test_filter_skips_without_api_and_advances_to_candidate(self):
        db = sqlite3.connect(':memory:')
        judge = Mock()
        judge.evaluate.return_value = {'verdict': 'not_reset', 'reason': 'just discussion', 'evidence': 'resets'}
        cycle(db, judge, lambda: [{'id': '1', 'text': 'Hello world'}])
        judge.evaluate.assert_not_called()
        cycle(db, judge, lambda: [{'id': '2', 'text': 'New feature'},
                                  {'id': '3', 'text': 'People keep asking for resets'}])
        judge.evaluate.assert_called_once_with({'id': '3', 'text': 'People keep asking for resets'})
        self.assertIn('skipped', db.execute("SELECT verdict FROM queue WHERE id='2'").fetchone()[0])

    def test_reset_filter_is_not_a_verdict(self):
        for text in ['RESET!', 'No reset today', 'asking for resets', 'and reset. Enjoy.']:
            self.assertTrue(mentions_reset(text))
        for text in ['preset', 'hello', 'resetting']:
            self.assertFalse(mentions_reset(text))
