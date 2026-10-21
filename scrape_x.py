"""Read-only experiment. No WhatsApp imports, credentials, sends or bot state writes."""
import argparse
import json
import html
from html.parser import HTMLParser
import urllib.request
import urllib.error
import os
import re
import sys
from urllib.parse import urlsplit


def extract_posts(articles):
    posts = {}
    for article in articles:
        # Author is the first profile link in the tweet article; ignore reposts
        # by other authors and don't use the nested quoted tweet's timestamp.
        if article.get('author', '').lower() != '/thsottiaux':
            continue
        for href in article.get('links', []):
            parsed = urlsplit(href)
            if parsed.netloc and parsed.hostname not in ('x.com', 'www.x.com'):
                continue
            match = re.fullmatch(r'/thsottiaux/status/(\d+)', parsed.path, re.I)
            if match and article.get('text', '').strip():
                ident = match.group(1)
                posts[ident] = {'id': ident, 'text': article['text'],
                                'url': f'https://x.com/thsottiaux/status/{ident}'}
                break
    return sorted(posts.values(), key=lambda post: int(post['id']), reverse=True)


class ScriptData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.inside = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.scripts.append(data)


def extract_html(document):
    parser = ScriptData()
    parser.feed(document)
    posts = {}

    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            if value.get('__typename') == 'Tweet':
                user = value.get('core', {}).get('user_results', {}).get('result', {})
                author = user.get('core', {}).get('screen_name', user.get('legacy', {}).get('screen_name', ''))
                ident = value.get('rest_id', '')
                note = value.get('note_tweet', {}).get('note_tweet_results', {}).get('result', {})
                text = note.get('text') or value.get('details', {}).get('full_text') or value.get('legacy', {}).get('full_text')
                # Do not treat nested quotes/reposts as independently authored posts.
                if author.lower() == 'thsottiaux' and ident.isdigit() and text:
                    if value.get('note_tweet', {}).get('is_expandable') and not note.get('text'):
                        return
                    posts[ident] = {'id': ident, 'text': html.unescape(text),
                                    'url': f'https://x.com/thsottiaux/status/{ident}'}
                return
            for key, child in value.items():
                if key not in ('quoted_tweet_results', 'nested_quoted_tweet_results', 'retweeted_status_result'):
                    walk(child)

    for script in parser.scripts:
        # Decode embedded JSON string literals only. Never execute page JavaScript.
        for match in re.finditer(r'value:("(?:\\.|[^"\\])*")', script):
            try:
                payload = json.loads(json.loads(match.group(1)))
            except (ValueError, TypeError):
                continue
            walk(payload)
    return sorted(posts.values(), key=lambda post: int(post['id']), reverse=True)


def scrape():
    try:
        with urllib.request.urlopen('https://x.com/thsottiaux', timeout=30) as response:
            data = response.read(4_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'X public page HTTP {exc.code}; no posts verified') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('X public page unavailable; check network and TLS trust') from None
    if len(data) > 4_000_000:
        raise RuntimeError('X public page exceeds size limit')
    posts = extract_html(data.decode('utf-8', errors='replace'))
    if not posts:
        raise RuntimeError('No public Tibo posts found; page schema or access may have changed')
    return posts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', help='Read local article JSON instead of accessing X')
    parser.add_argument('--judge', action='store_true', help='Judge every extracted full text with LLM; never sends WhatsApp')
    args = parser.parse_args()
    try:
        if args.fixture:
            with open(args.fixture) as file:
                posts = extract_posts(json.load(file))
        else:
            posts = scrape()
        if args.judge:
            from pathlib import Path
            from llm_judge import Judge
            Path('.local').mkdir(exist_ok=True)
            judge = Judge()
            for post in posts:
                post['judgment'] = judge.evaluate(post)
        print(json.dumps({'mode': 'read-only', 'posts': posts}, ensure_ascii=False, indent=2))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
