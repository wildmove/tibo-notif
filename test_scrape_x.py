import unittest
from scrape_x import extract_posts


class ExtractTests(unittest.TestCase):
    def test_author_link_and_quote_filter(self):
        rows = [
            {'author': '/thsottiaux', 'text': 'Day 15/ and reset. Enjoy.',
             'links': ['/thsottiaux/status/20', '/other/status/21']},
            {'author': '/other', 'text': 'quoted Tibo', 'links': ['/thsottiaux/status/30']},
            {'author': '/thsottiaux', 'text': '', 'links': ['/thsottiaux/status/40']},
        ]
        self.assertEqual([p['id'] for p in extract_posts(rows)], ['20'])

    def test_sort_and_dedupe(self):
        rows = [{'author': '/thsottiaux', 'text': 'reset', 'links': [f'/thsottiaux/status/{i}']}
                for i in [10, 20, 10]]
        self.assertEqual([p['id'] for p in extract_posts(rows)], ['20', '10'])

    def test_reject_other_host(self):
        self.assertEqual(extract_posts([{'author': '/thsottiaux', 'text': 'fake',
                         'links': ['https://example.com/thsottiaux/status/20']}]), [])
