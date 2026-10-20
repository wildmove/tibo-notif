import unittest
from unittest.mock import Mock, patch
import bot


class BotTests(unittest.TestCase):
    def test_detection(self):
        self.assertTrue(bot.matches('We reset Codex usage limits today'))
        self.assertTrue(bot.matches('Codex credits have been replenished'))
        for text in ['Codex is great', 'ChatGPT limits reset', 'Codex limits were not reset']:
            self.assertFalse(bot.matches(text))

    def test_tibo_daily_reset(self):
        self.assertTrue(bot.matches("Day 15/ Nevermind, we're still cooking... and reset. Enjoy."))
        self.assertTrue(bot.matches('Day 8/ Reset'))
        self.assertTrue(bot.matches('Day 13/ Le limit reset'))
        self.assertFalse(bot.matches('People are asking me for resets on the street'))
        self.assertFalse(bot.matches('Day 16/ No reset today'))

    def test_duplicate_and_restart(self):
        db = bot.connect(':memory:')
        source, sender = Mock(), Mock()
        source.tweets.return_value = [{'id': '2', 'text': 'Codex limits reset'}]
        bot.poll(db, source, sender)
        bot.poll(db, source, sender)
        self.assertEqual(sender.send.call_count, 1)
        source.tweets.assert_called_with('2')

    def test_failed_send_keeps_cursor(self):
        db = bot.connect(':memory:')
        source, sender = Mock(), Mock()
        source.tweets.return_value = [{'id': '2', 'text': 'Codex limits reset'}]
        sender.send.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            bot.poll(db, source, sender)
        self.assertIsNone(db.execute('SELECT * FROM state').fetchone())
        sender.send.side_effect = None
        bot.poll(db, source, sender)
        self.assertEqual(sender.send.call_count, 2)

    def test_pagination(self):
        with patch('bot.request', side_effect=[{'data': {'id': '42'}},
                   {'data': [{'id': '3'}], 'meta': {'next_token': 'next'}},
                   {'data': [{'id': '2'}]}]) as req:
            self.assertEqual([t['id'] for t in bot.XClient('fake').tweets('1')], ['2', '3'])
            self.assertIn('pagination_token=next', req.call_args.args[1])

    def test_fonnte_send(self):
        settings = {'FONNTE_TOKEN': 'fake', 'WHATSAPP_TO': '628123456789'}
        with patch.dict('os.environ', settings), patch('bot.request', return_value={'status': True}) as req:
            bot.WhatsApp().send({'id': '7'})
            self.assertEqual(req.call_args.args[:3],
                             ('POST', 'https://api.fonnte.com/send', 'fake'))
            self.assertEqual(req.call_args.args[3]['target'], '628123456789')
            self.assertEqual(req.call_args.args[3]['message'],
                             'Info reset codex brader!\nhttps://x.com/thsottiaux/status/7')
            self.assertTrue(req.call_args.kwargs['form'])

    def test_fonnte_rejection(self):
        with patch.dict('os.environ', {'FONNTE_TOKEN': 'fake', 'WHATSAPP_TO': '123'}), \
                patch('bot.request', return_value={'status': False}):
            with self.assertRaises(RuntimeError):
                bot.WhatsApp().send({'id': '7'})

    def test_fonnte_wire_format(self):
        response = Mock()
        response.read.return_value = b'{"status":true}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('bot.urllib.request.urlopen', return_value=response) as urlopen:
            bot.request('POST', 'https://api.fonnte.com/send', 'fake',
                        {'target': '123', 'message': 'hello & world'}, form=True)
            req = urlopen.call_args.args[0]
            self.assertEqual(req.get_header('Authorization'), 'fake')
            self.assertEqual(bot.urllib.parse.parse_qs(req.data.decode()),
                             {'target': ['123'], 'message': ['hello & world']})


class RSSTests(unittest.TestCase):
    def test_rss_filters_author_sorts_and_decodes(self):
        feed = b'''<rss><channel>
        <item><link>https://x.com/thsottiaux/status/20</link><description>&lt;b&gt;Codex limits reset&lt;/b&gt;</description></item>
        <item><link>https://twitter.com/thsottiaux/status/10</link><title>hello</title></item>
        <item><link>https://x.com/other/status/30</link><title>Codex limits reset</title></item>
        </channel></rss>'''
        tweets = bot.parse_feed(feed)
        self.assertEqual([t['id'] for t in tweets], ['10', '20'])
        self.assertTrue(bot.matches(tweets[1]['text']))

    def test_atom(self):
        feed = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <link href="https://x.com/thsottiaux/status/7"/><content>Codex limits reset</content>
        </entry></feed>'''
        self.assertEqual(bot.parse_feed(feed)[0]['id'], '7')

    def test_invalid_feed(self):
        for data in [b'<html/>', b'broken', b'<!DOCTYPE rss><rss/>']:
            with self.assertRaises(RuntimeError):
                bot.parse_feed(data)

    def test_late_item_and_duplicates(self):
        db = bot.connect(':memory:')
        source, sender = Mock(), Mock()
        source.tweets.return_value = [{'id': '20', 'text': 'Codex limits reset'}]
        bot.poll(db, source, sender)
        source.tweets.return_value = [{'id': '10', 'text': 'Codex limits reset'},
                                      {'id': '20', 'text': 'Codex limits reset'}]
        bot.poll(db, source, sender)
        self.assertEqual(sender.send.call_count, 2)

    def test_https_required(self):
        with self.assertRaises(ValueError):
            bot.RSSClient('http://example.com/feed')

    def test_rss_fetch(self):
        response = Mock()
        response.geturl.return_value = 'https://rss.app/feeds/example.xml'
        response.read.return_value = b'<rss><channel><item><link>https://x.com/thsottiaux/status/7</link><title>Codex limits reset</title></item></channel></rss>'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('bot.urllib.request.urlopen', return_value=response):
            self.assertEqual(bot.RSSClient('https://rss.app/feeds/example.xml').tweets('8')[0]['id'], '7')


if __name__ == '__main__':
    unittest.main()
