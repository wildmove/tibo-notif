"""Read-only experiment. No WhatsApp imports, credentials, sends or bot state writes."""
import argparse
import json
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


def scrape():
    from playwright.sync_api import sync_playwright, Error
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
    kwargs = {'headless': True, 'executable_path': '/usr/bin/chromium'}
    if proxy_url:
        kwargs['proxy'] = {'server': proxy_url}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**kwargs)
        try:
            page = browser.new_page()
            response = page.goto('https://x.com/thsottiaux', wait_until='domcontentloaded', timeout=45000)
            if response and response.status >= 400:
                raise RuntimeError(f'X returned HTTP {response.status}; no posts verified')
            page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            rows = page.locator('article[data-testid="tweet"]').evaluate_all('''articles => articles.map(a => ({
                author: a.querySelector('[data-testid="User-Name"] a')?.getAttribute('href') || '',
                text: a.querySelector('[data-testid="tweetText"]')?.innerText || '',
                links: Array.from(a.querySelectorAll('a:has(time)')).map(l => l.getAttribute('href'))
            }))''')
            posts = extract_posts(rows)
            if not posts:
                raise RuntimeError('No readable Tibo posts; public timeline may require login or selectors changed')
            return posts
        except Error:
            # Avoid dumping browser diagnostics that may include proxy configuration.
            raise RuntimeError('Browser could not read public X timeline; check network policy, TLS trust, login wall or page changes') from None
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', help='Read local article JSON instead of accessing X')
    args = parser.parse_args()
    try:
        if args.fixture:
            with open(args.fixture) as file:
                posts = extract_posts(json.load(file))
        else:
            posts = scrape()
        print(json.dumps({'mode': 'read-only', 'posts': posts}, ensure_ascii=False, indent=2))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
