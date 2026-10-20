"""Poll Tibo's public timeline and send reset announcements via WhatsApp."""
import argparse
import fcntl
import json
import html
import xml.etree.ElementTree as ET
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger('tibo-notif')


def matches(text):
    text = text.lower()
    if re.search(r"\b(?:no|not|never)\s+(?:\w+\s+){0,2}reset", text):
        return False
    explicit = (re.search(r'\bcodex\b', text) and
                re.search(r'\b(?:reset\w*|refresh\w*|replenish\w*)\b', text) and
                re.search(r'\b(?:limits?|quotas?|usage|credits?)\b', text))
    # Only used for the configured Tibo timeline; short daily announcements
    # frequently omit the product and limit names.
    tibo_daily = (re.search(r'\bday\s*\d+\s*/', text) and
                  re.search(r'\breset\b', text))
    return bool(explicit or tibo_daily)


def request(method, url, token, payload=None, *, form=False):
    data = None if payload is None else (urllib.parse.urlencode(payload).encode() if form
                                         else json.dumps(payload).encode())
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': token if form else 'Bearer ' + token,
                                          'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Don't log response bodies, URLs containing private IDs, or credentials.
        raise RuntimeError(f'API HTTP {exc.code}; check access, quota and configuration') from None
    except urllib.error.URLError:
        raise RuntimeError('API network failure; check connectivity') from None


class XClient:
    def __init__(self, token):
        self.token = token
        self.user_id = None

    def tweets(self, since):
        if self.user_id is None:
            result = request('GET', 'https://api.x.com/2/users/by/username/thsottiaux', self.token)
            self.user_id = result['data']['id']
        params = {'max_results': 100, 'exclude': 'retweets', 'tweet.fields': 'created_at,note_tweet'}
        if since:
            params['since_id'] = since
        tweets = []
        while True:
            result = request('GET', f'https://api.x.com/2/users/{self.user_id}/tweets?' +
                             urllib.parse.urlencode(params), self.token)
            tweets.extend(result.get('data', []))
            next_token = result.get('meta', {}).get('next_token')
            if not next_token:
                break
            params['pagination_token'] = next_token
        return sorted(tweets, key=lambda t: int(t['id']))


def parse_feed(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise RuntimeError('Feed DTD/entities are not supported')
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise RuntimeError('Feed is not valid RSS/Atom XML') from None
    local = lambda tag: tag.rsplit('}', 1)[-1]
    if local(root.tag) not in ('rss', 'feed', 'RDF'):
        raise RuntimeError('Response is not an RSS/Atom feed')
    tweets = {}
    for entry in root.iter():
        if local(entry.tag) not in ('item', 'entry'):
            continue
        links, texts = [], []
        for field in entry:
            name = local(field.tag)
            if name in ('link', 'guid', 'id'):
                links.append(field.get('href', '') or field.text or '')
            if name in ('title', 'description', 'summary', 'content', 'encoded'):
                texts.append(''.join(field.itertext()))
        for link in links:
            parsed = urllib.parse.urlsplit(link.strip())
            match = re.fullmatch(r'/thsottiaux/status/(\d+)/?', parsed.path, re.I)
            if parsed.scheme == 'https' and parsed.hostname in ('x.com', 'twitter.com', 'www.twitter.com', 'www.x.com') and match:
                tweet_id = match.group(1)
                text = html.unescape(re.sub(r'<[^>]+>', ' ', ' '.join(texts)))
                tweets[tweet_id] = {'id': tweet_id, 'text': text}
                break
    return sorted(tweets.values(), key=lambda tweet: int(tweet['id']))


class RSSClient:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('RSS_FEED_URL must be an HTTPS URL without embedded credentials')
        self.url = url

    def tweets(self, since):
        # Recheck every item: feeds may insert older posts late or change ordering.
        # The shared sent table deduplicates notifications across RSS and X modes.
        req = urllib.request.Request(self.url, headers={'Accept': 'application/rss+xml, application/atom+xml, application/xml'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
                    raise RuntimeError('Feed redirected away from HTTPS')
                data = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'RSS HTTP {exc.code}; check feed and network access') from None
        except urllib.error.URLError:
            raise RuntimeError('RSS network failure; check feed and network access') from None
        if len(data) > 2_000_000:
            raise RuntimeError('Feed exceeds 2 MB size limit')
        return parse_feed(data)


class WhatsApp:
    def __init__(self):
        self.token = os.environ['FONNTE_TOKEN']

    def send(self, tweet):
        payload = {
            'target': os.environ['WHATSAPP_TO'],
            'message': 'Info reset codex brader!\n'
                       'https://x.com/thsottiaux/status/' + tweet['id'],
        }
        result = request('POST', 'https://api.fonnte.com/send', self.token,
                         payload, form=True)
        if result.get('status') is not True:
            raise RuntimeError('Fonnte did not acknowledge message acceptance')


def connect(path):
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS sent (id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS processed (id TEXT PRIMARY KEY)')
    return db


def poll(db, source, sender):
    row = db.execute("SELECT value FROM state WHERE key='since'").fetchone()
    tweets = source.tweets(row[0] if row else None)
    for tweet in tweets:
        if db.execute('SELECT 1 FROM processed WHERE id=?', (tweet['id'],)).fetchone():
            continue
        text = tweet.get('note_tweet', {}).get('text', tweet.get('text', ''))
        if matches(text) and not db.execute('SELECT 1 FROM sent WHERE id=?', (tweet['id'],)).fetchone():
            sender.send(tweet)
            db.execute('INSERT INTO sent VALUES (?)', (tweet['id'],))
            LOG.info('WhatsApp accepted notification for tweet %s', tweet['id'])
        db.execute('INSERT OR IGNORE INTO processed VALUES (?)', (tweet['id'],))
        db.execute("INSERT OR REPLACE INTO state VALUES ('since', ?)", (tweet['id'],))
        db.commit()
    LOG.info('Poll completed: %s posts checked', len(tweets))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-feed', action='store_true', help='Read RSS only; no WhatsApp or state changes')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--demo', action='store_true', help='Offline smoke test; sends nothing')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.demo:
        class DemoSource:
            def tweets(self, since):
                return [{'id': '1', 'text': 'We have reset Codex usage limits!'}]
        class DemoSender:
            def send(self, tweet):
                print('DEMO: would notify about tweet', tweet['id'])
        db = connect(':memory:')
        poll(db, DemoSource(), DemoSender())
        poll(db, DemoSource(), DemoSender())
        return
    source_mode = os.getenv('SOURCE', 'rss')
    if source_mode not in ('rss', 'x'):
        parser.error('SOURCE must be rss or x')
    if args.check_feed:
        if not os.getenv('RSS_FEED_URL'):
            parser.error('Missing environment settings: RSS_FEED_URL')
        try:
            tweets = RSSClient(os.environ['RSS_FEED_URL']).tweets(None)
        except (RuntimeError, ValueError) as exc:
            parser.error(str(exc))
        print(f'Feed read: {len(tweets)} Tibo posts, '
              f'{sum(matches(t["text"]) for t in tweets)} reset candidates; no messages sent')
        if not tweets:
            parser.error('Feed contains no recognizable Tibo post links; verify feed coverage')
        return
    required = ['RSS_FEED_URL' if source_mode == 'rss' else 'X_BEARER_TOKEN',
                'FONNTE_TOKEN', 'WHATSAPP_TO']
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        parser.error('Missing environment settings: ' + ', '.join(missing))
    interval = int(os.getenv('POLL_SECONDS', '300'))
    if interval < 60:
        parser.error('POLL_SECONDS must be at least 60')
    path = Path(os.getenv('STATE_PATH', '.local/state.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another bot process is using this state file')
        db = connect(path)
        source = (RSSClient(os.environ['RSS_FEED_URL']) if source_mode == 'rss'
                  else XClient(os.environ['X_BEARER_TOKEN']))
        sender = WhatsApp()
        while True:
            try:
                poll(db, source, sender)
            except (RuntimeError, KeyError, ValueError) as exc:
                if args.once:
                    raise SystemExit(str(exc)) from None
                LOG.error('Poll failed (%s); retrying next interval', type(exc).__name__)
            if args.once:
                break
            time.sleep(interval)


if __name__ == '__main__':
    main()
