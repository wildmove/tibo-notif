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


class PublicHTMLTests(unittest.TestCase):
    def page(self, data):
        import json
        return '<script>stream({value:' + json.dumps(json.dumps(data)) + '})</script>'

    def tweet(self, ident='20', author='thsottiaux', text='Day 15/ and reset. Enjoy.'):
        return {'__typename': 'Tweet', 'rest_id': ident,
                'core': {'user_results': {'result': {'core': {'screen_name': author}}}},
                'details': {'full_text': text}}

    def test_embedded_json_author_and_quotes(self):
        from scrape_x import extract_html
        post = self.tweet()
        post['quoted_tweet_results'] = self.tweet('19')
        result = extract_html(self.page({'entries': [post, self.tweet('30', 'other')]}))
        self.assertEqual([p['id'] for p in result], ['20'])
        self.assertEqual(result[0]['text'], 'Day 15/ and reset. Enjoy.')

    def test_long_note_overrides_short_text(self):
        from scrape_x import extract_html
        post = self.tweet(text='short...')
        full = 'Long complete text &amp; more'
        post['note_tweet'] = {'is_expandable': True, 'note_tweet_results': {'result': {'text': full}}}
        self.assertEqual(extract_html(self.page(post))[0]['text'], 'Long complete text & more')
        post['note_tweet']['note_tweet_results']['result'].clear()
        self.assertEqual(extract_html(self.page(post)), [])

    def test_no_execution_or_false_empty_success(self):
        from scrape_x import extract_html
        self.assertEqual(extract_html('<html>Login</html>'), [])
        self.assertEqual(extract_html('<script>value:"not JSON"; dangerous()</script>'), [])
