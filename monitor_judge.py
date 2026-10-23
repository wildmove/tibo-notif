"""10-minute X -> Gemini -> Fonnte monitor. Use --dry-run to disable sends."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import traceback
import os
import re
from pathlib import Path
import sqlite3
import time
from scrape_x import scrape
from llm_judge import Judge


LOG = logging.getLogger('monitor')


def log(message, **kwargs):
    LOG.info('%s', message)


def heartbeat():
    path = Path('.local/monitor-judge.heartbeat')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(str(time.time()))
    temporary.replace(path)


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


def deliver(db, sender):
    db.execute('CREATE TABLE IF NOT EXISTS notified (id TEXT PRIMARY KEY)')
    if sender is None:
        return
    for ident, text, raw in db.execute('SELECT id,text,verdict FROM queue WHERE verdict IS NOT NULL').fetchall():
        verdict = json.loads(raw)
        if verdict.get('verdict') != 'reset':
            continue
        if db.execute('SELECT 1 FROM notified WHERE id=?', (ident,)).fetchone():
            continue
        sender.send({'id': ident, 'text': text})
        db.execute('INSERT INTO notified VALUES (?)', (ident,))
        db.commit()
        log(f'Fonnte accepted reset notification for {ident}', flush=True)


def cycle(db, judge, fetch=scrape, sender=None):
    posts = fetch()
    enqueue(db, posts)
    pending = None
    for row in db.execute('SELECT id,text FROM queue WHERE verdict IS NULL ORDER BY LENGTH(id),id').fetchall():
        if mentions_reset(row[1]):
            pending = row
            break
        db.execute('UPDATE queue SET verdict=? WHERE id=?',
                   (json.dumps({'status': 'skipped', 'reason': 'No reset mention; LLM not called'}), row[0]))
        log(f'Post {row[0]} skipped: no reset mention; no Gemini request', flush=True)
    db.commit()
    if pending:
        result = judge.evaluate({'id': pending[0], 'text': pending[1]})
        db.execute('UPDATE queue SET verdict=? WHERE id=?', (json.dumps(result), pending[0]))
        db.commit()
        log(json.dumps({'mode': 'live' if sender else 'no-whatsapp', 'post_id': pending[0], 'text': pending[1],
                          'judgment': result}, ensure_ascii=False), flush=True)
    else:
        log('No new posts to judge; no Gemini request', flush=True)
    deliver(db, sender)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loop', action='store_true', help='Poll every 600 seconds; default one cycle')
    parser.add_argument('--dry-run', action='store_true', help='Judge posts but never send Fonnte')
    args = parser.parse_args()
    Path('.local').mkdir(exist_ok=True)
    handler = RotatingFileHandler('.local/monitor-judge.log', maxBytes=5_000_000, backupCount=3)
    formatter = logging.Formatter('%(asctime)s UTC %(levelname)s %(message)s')
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    with open('.local/monitor-judge.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another monitor is running')
        db = sqlite3.connect('.local/monitor-judge.sqlite3')
        sender = None
        if not args.dry_run:
            if not os.getenv('FONNTE_TOKEN') or not os.getenv('WHATSAPP_TO'):
                parser.error('Missing FONNTE_TOKEN or WHATSAPP_TO')
            from bot import WhatsApp
            sender = WhatsApp()
            db.execute('CREATE TABLE IF NOT EXISTS notified (id TEXT PRIMARY KEY)')
            # Carry over IDs accepted by the previous RSS sender, avoiding resends.
            legacy = Path(os.getenv('STATE_PATH', '.local/state.sqlite3'))
            if legacy.exists():
                with sqlite3.connect('file:' + str(legacy.resolve()) + '?mode=ro', uri=True) as previous:
                    for row in previous.execute('SELECT id FROM sent'):
                        db.execute('INSERT OR IGNORE INTO notified VALUES (?)', row)
                db.commit()
        try:
            judge = Judge()
        except RuntimeError as exc:
            parser.error(str(exc))
        LOG.info('Monitor started pid=%s interval=600 dry_run=%s', os.getpid(), args.dry_run)
        heartbeat()
        while True:
            started = time.monotonic()
            try:
                judge.run_calls = 0
                # Retry already-judged notifications without another Gemini call.
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='queue'").fetchone():
                    deliver(db, sender)
                cycle(db, judge, sender=sender)
            except (RuntimeError, TimeoutError, OSError, ValueError, sqlite3.Error) as exc:
                db.rollback()
                LOG.error('Cycle failed: %s; retry next cycle', type(exc).__name__)
                if not args.loop:
                    return 1
            except Exception as exc:
                db.rollback()
                # Record stack locations, never exception values or local variables.
                frames = ' > '.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                                    for f in traceback.extract_tb(exc.__traceback__))
                LOG.error('Unexpected error %s at %s', type(exc).__name__, frames)
                raise SystemExit(1) from None
            heartbeat()
            LOG.info('Cycle completed in %.1fs; next poll in 600s', time.monotonic() - started)
            if not args.loop:
                return 0
            time.sleep(600)


if __name__ == '__main__':
    raise SystemExit(main())
