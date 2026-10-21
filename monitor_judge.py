"""Experimental 10-minute X -> Gemini monitor. Never sends WhatsApp."""
import argparse
import fcntl
import json
import re
from pathlib import Path
import sqlite3
import time
from scrape_x import scrape
from llm_judge import Judge


def mentions_reset(text):
    return bool(re.search(r'\bresets?\b', text, re.IGNORECASE))


def enqueue(db, posts):
    db.execute('CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, text TEXT NOT NULL, verdict TEXT)')
    row = db.execute('SELECT value FROM cursor WHERE id=1').fetchone()
    ordered = sorted(posts, key=lambda p: int(p['id']))
    # First run judges latest only, avoiding a paid historical backfill.
    selected = ([ordered[-1]] if ordered else []) if row is None else [
        p for p in ordered if int(p['id']) > int(row[0])]
    for post in selected:
        db.execute('INSERT OR IGNORE INTO queue(id,text) VALUES (?,?)', (post['id'], post['text']))
    if ordered:
        newest = max(int(ordered[-1]['id']), int(row[0]) if row else 0)
        db.execute('INSERT OR REPLACE INTO cursor VALUES (1,?)', (str(newest),))
    db.commit()


def cycle(db, judge, fetch=scrape):
    posts = fetch()
    enqueue(db, posts)
    pending = None
    for row in db.execute('SELECT id,text FROM queue WHERE verdict IS NULL ORDER BY LENGTH(id),id').fetchall():
        if mentions_reset(row[1]):
            pending = row
            break
        db.execute('UPDATE queue SET verdict=? WHERE id=?',
                   (json.dumps({'status': 'skipped', 'reason': 'No reset mention; LLM not called'}), row[0]))
        print(f'Post {row[0]} skipped: no reset mention; no Gemini request', flush=True)
    db.commit()
    if pending:
        result = judge.evaluate({'id': pending[0], 'text': pending[1]})
        db.execute('UPDATE queue SET verdict=? WHERE id=?', (json.dumps(result), pending[0]))
        db.commit()
        print(json.dumps({'mode': 'no-whatsapp', 'post_id': pending[0], 'text': pending[1],
                          'judgment': result}, ensure_ascii=False), flush=True)
    else:
        print('No new posts to judge; no Gemini request', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loop', action='store_true', help='Poll every 600 seconds; default one cycle')
    args = parser.parse_args()
    Path('.local').mkdir(exist_ok=True)
    with open('.local/monitor-judge.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another experimental monitor is running')
        db = sqlite3.connect('.local/monitor-judge.sqlite3')
        try:
            judge = Judge()
        except RuntimeError as exc:
            parser.error(str(exc))
        while True:
            try:
                judge.run_calls = 0
                cycle(db, judge)
            except RuntimeError as exc:
                print(str(exc), flush=True)
                if not args.loop:
                    return 1
            if not args.loop:
                return 0
            time.sleep(600)


if __name__ == '__main__':
    raise SystemExit(main())
