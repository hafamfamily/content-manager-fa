"""store.py - the queue and the publishing ledger (SQLite, one file: <home>/cm.db).

items   one content package (a folder queue/<id>/ with item.json + files)
targets one row per platform of an item: what was sent, when, where, and errors
events  append-only history (who approved, what failed, what was published)

Item status:  draft -> approved -> published | partial | failed | expired
              draft -> rejected ; any not-yet-published -> cancelled
Target status: pending -> published | failed (permanent) ; transient errors stay pending
"""

import datetime as dt
import hashlib
import json
import os
import sqlite3

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, brand TEXT NOT NULL, title TEXT, kind TEXT, folder TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', scheduled_at TEXT, expires_at TEXT,
  content_hash TEXT, approved_by TEXT, approved_at TEXT, note TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS targets(
  item_id TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, remote_id TEXT, url TEXT,
  published_at TEXT, PRIMARY KEY(item_id, platform));
CREATE TABLE IF NOT EXISTS events(
  ts TEXT NOT NULL, brand TEXT, item_id TEXT, platform TEXT, level TEXT, msg TEXT);
CREATE INDEX IF NOT EXISTS ix_items_due ON items(status, scheduled_at);
"""

FINAL = {"published", "partial", "failed", "expired", "rejected", "cancelled"}


def now():
    return dt.datetime.now().replace(microsecond=0)


def iso(t):
    return t.isoformat(timespec="minutes") if t else None


def parse_time(s):
    if not s:
        return None
    t = dt.datetime.fromisoformat(str(s).strip().replace(" ", "T"))
    return t.replace(tzinfo=None) if t.tzinfo is None else t.astimezone().replace(tzinfo=None)


def connect():
    os.makedirs(paths.home(), exist_ok=True)
    c = sqlite3.connect(paths.db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def file_hash(folder):
    """Hash of item.json and every file it references: changing anything after approval voids it."""
    h = hashlib.sha256()
    item_json = os.path.join(folder, "item.json")
    with open(item_json, "rb") as f:
        h.update(f.read())
    item = load_item(folder)
    for p in sorted(set(referenced_files(item))):
        full = os.path.join(folder, p)
        h.update(p.encode())
        with open(full, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def load_item(folder):
    with open(os.path.join(folder, "item.json"), encoding="utf-8") as f:
        return json.load(f)


def referenced_files(item):
    out = []
    for t in (item.get("targets") or {}).values():
        for m in t.get("media") or []:
            if m.get("path"):
                out.append(m["path"])
    return out


def event(c, brand, item_id, platform, level, msg):
    c.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (iso(now()), brand, item_id, platform, level, msg))
    log_dir = paths.brand_dir(brand) if brand else paths.home()
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "publish.log"), "a", encoding="utf-8") as f:
            f.write(f"{iso(now())} [{level}] {item_id or '-'} {platform or '-'}: {msg}\n")
    except OSError:
        pass


def add_item(c, brand, folder, item):
    t = iso(now())
    c.execute("""INSERT INTO items(id, brand, title, kind, folder, status, scheduled_at, expires_at, created_at, updated_at)
                 VALUES(?,?,?,?,?,'draft',?,?,?,?)""",
              (item["id"], brand, item.get("title"), item.get("kind"), os.path.abspath(folder),
               iso(parse_time(item.get("scheduled_at"))), iso(parse_time(item.get("expires_at"))), t, t))
    for p in item["targets"]:
        c.execute("INSERT INTO targets(item_id, platform) VALUES(?,?)", (item["id"], p))
    event(c, brand, item["id"], None, "info", "added to queue as draft")


def get_item(c, item_id):
    return c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


def targets(c, item_id):
    return c.execute("SELECT * FROM targets WHERE item_id=? ORDER BY platform", (item_id,)).fetchall()


def set_status(c, item_id, status, **kw):
    sets = ["status=?", "updated_at=?"]
    vals = [status, iso(now())]
    for k, v in kw.items():
        sets.append(f"{k}=?")
        vals.append(v)
    c.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", (*vals, item_id))


def due(c, at=None):
    at = iso(at or now())
    return c.execute("""SELECT * FROM items WHERE status='approved'
                        AND (scheduled_at IS NULL OR scheduled_at<=?) ORDER BY scheduled_at""", (at,)).fetchall()


def upcoming(c, within_minutes):
    lim = iso(now() + dt.timedelta(minutes=within_minutes))
    return c.execute("SELECT * FROM items WHERE status='approved' AND (scheduled_at IS NULL OR scheduled_at<=?)",
                     (lim,)).fetchall()
