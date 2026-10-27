"""runner.py - queue operations and the publishing loop.

Safety rules enforced here (not in the skills, so no prompt can skip them):
  1. Only items with status 'approved' and a non-empty approved_by are published.
  2. Approval is bound to a hash of item.json + its files; any change after approval voids it.
  3. A target already 'published' is never sent again (no duplicate posts).
  4. If <home>/STOP exists, nothing is published.
  5. Only one run at a time (lock file).
  6. News past its expires_at (or older than news_max_age_hours) is not published late.
"""

import datetime as dt
import json
import os
import re
import shutil
import time

from . import brand as brands
from . import connectors, paths, store, vault

MAX_ATTEMPTS = 3
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


class QueueError(Exception):
    pass


# ---------- adding and checking ----------

def validate(brand, folder, item=None):
    item = item or store.load_item(folder)
    errs = []
    if not ID_RE.match(str(item.get("id") or "")):
        errs.append("item.json: id must be English letters/digits/-_. (e.g. 2026-10-28-gemini-news)")
    if not item.get("title"):
        errs.append("item.json: title is missing")
    tg = item.get("targets") or {}
    if not tg:
        errs.append("item.json: no targets (which platforms?)")
    for t in ("scheduled_at", "expires_at"):
        if item.get(t):
            try:
                store.parse_time(item[t])
            except ValueError:
                errs.append(f"item.json: {t} is not a valid time (use 2026-10-28T09:30)")
    cfg = brands.config(brand).get("platforms") or {}
    for p, payload in tg.items():
        pc = cfg.get(p)
        if p not in connectors.PLATFORMS:
            errs.append(f"unknown platform {p}")
        elif not pc or not pc.get("enabled"):
            errs.append(f"{p}: not enabled for brand {brand} (platforms.json)")
        elif pc.get("method") == "api":
            conn = connectors.get(p)
            if not conn:
                errs.append(f"{p}: no automatic connector yet; set method to manual")
            else:
                errs += conn.validate(payload, folder, pc)
    return errs


def add(brand, src_folder):
    brands.config(brand)  # exists?
    src = os.path.abspath(src_folder)
    item = store.load_item(src)
    errs = validate(brand, src, item)
    if errs:
        raise QueueError("\n".join(errs))
    qdir = os.path.join(paths.brand_dir(brand), "queue", item["id"])
    if os.path.abspath(qdir) != src:
        if os.path.exists(qdir):
            raise QueueError(f"an item with id {item['id']} already exists in the queue")
        shutil.copytree(src, qdir)
    with store.connect() as c:
        if store.get_item(c, item["id"]):
            raise QueueError(f"item {item['id']} is already registered")
        store.add_item(c, brand, qdir, item)
    return item["id"]


def preview(item_id):
    with store.connect() as c:
        it = store.get_item(c, item_id)
        if not it:
            raise QueueError(f"no item {item_id}")
        tg = store.targets(c, item_id)
    item = store.load_item(it["folder"])
    lines = [f"■ {it['title']}  [{it['id']}]",
             f"  وضعیت: {it['status']} · زمان انتشار: {it['scheduled_at'] or 'بلافاصله پس از تأیید'}"
             + (f" · انقضا: {it['expires_at']}" if it["expires_at"] else "")]
    for t in tg:
        pl = item["targets"][t["platform"]]
        media = ", ".join(f"{m['type']}:{m['path']}" for m in pl.get("media") or []) or "بدون فایل"
        lines.append(f"\n── {connectors.PLATFORMS.get(t['platform'], t['platform'])} ({t['status']}) · {media}")
        lines.append(pl.get("text") or "(بدون متن)")
    return "\n".join(lines)


def list_items(brand=None, status=None):
    q, a = "SELECT * FROM items WHERE 1=1", []
    if brand:
        q += " AND brand=?"
        a.append(brand)
    if status:
        q += " AND status=?"
        a.append(status)
    with store.connect() as c:
        rows = c.execute(q + " ORDER BY COALESCE(scheduled_at, created_at)", a).fetchall()
        return [(r, store.targets(c, r["id"])) for r in rows]


# ---------- owner decisions ----------

def approve(item_id, approved_by):
    approved_by = (approved_by or "").strip()
    if not approved_by:
        raise QueueError("approval needs the owner's exact words (--by)")
    with store.connect() as c:
        it = store.get_item(c, item_id)
        if not it:
            raise QueueError(f"no item {item_id}")
        if it["status"] != "draft":
            raise QueueError(f"item is {it['status']}, only drafts can be approved")
        errs = validate(it["brand"], it["folder"])
        if errs:
            raise QueueError("cannot approve, checks failed:\n" + "\n".join(errs))
        store.set_status(c, item_id, "approved", content_hash=store.file_hash(it["folder"]),
                         approved_by=approved_by, approved_at=store.iso(store.now()))
        store.event(c, it["brand"], item_id, None, "info", f"approved by owner: {approved_by!r}")


def reject(item_id, note):
    _close(item_id, "rejected", note, allowed={"draft"})


def cancel(item_id, note):
    _close(item_id, "cancelled", note, allowed={"draft", "approved"})


def _close(item_id, status, note, allowed):
    with store.connect() as c:
        it = store.get_item(c, item_id)
        if not it:
            raise QueueError(f"no item {item_id}")
        if it["status"] not in allowed:
            raise QueueError(f"item is {it['status']}; cannot set {status}")
        store.set_status(c, item_id, status, note=note)
        store.event(c, it["brand"], item_id, None, "info", f"{status}: {note or ''}")


# ---------- the publishing loop ----------

class Lock:
    def __init__(self, stale_minutes=60):
        self.p = paths.lock_file()
        self.stale = stale_minutes * 60

    def __enter__(self):
        os.makedirs(paths.home(), exist_ok=True)
        if os.path.exists(self.p) and time.time() - os.path.getmtime(self.p) > self.stale:
            os.remove(self.p)
        try:
            fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise QueueError("another run is in progress")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.p)
        except OSError:
            pass


def stopped():
    return os.path.exists(paths.stop_file())


def _expired(it, cfg):
    t = store.now()
    if it["expires_at"] and store.parse_time(it["expires_at"]) < t:
        return True
    max_age = cfg.get("news_max_age_hours")
    if it["kind"] == "news" and max_age and it["scheduled_at"]:
        return store.parse_time(it["scheduled_at"]) + dt.timedelta(hours=max_age) < t
    return False


def run(dry_run=False, only_item=None, out=print):
    """Publish everything due. Returns a summary dict (also written to the log)."""
    summary = {"published": [], "failed": [], "manual": [], "skipped": [], "stopped": False}
    if stopped():
        summary["stopped"] = True
        out("STOP فعال است؛ هیچ چیزی منتشر نشد. (cm resume)")
        return summary
    with Lock():
        with store.connect() as c:
            rows = [store.get_item(c, only_item)] if only_item else store.due(c)
            rows = [r for r in rows if r and r["status"] == "approved"]
            last_send = {}
            for it in rows:
                if stopped():
                    summary["stopped"] = True
                    break
                bid, iid = it["brand"], it["id"]
                cfg = brands.config(bid)
                if not it["approved_by"]:
                    summary["skipped"].append((iid, "no approval record"))
                    continue
                if _expired(it, cfg):
                    store.set_status(c, iid, "expired")
                    store.event(c, bid, iid, None, "warn", "expired before it could be published; not sent late")
                    summary["skipped"].append((iid, "expired"))
                    continue
                if store.file_hash(it["folder"]) != it["content_hash"]:
                    store.set_status(c, iid, "draft", approved_by=None, approved_at=None, content_hash=None)
                    store.event(c, bid, iid, None, "error", "content changed after approval; back to draft, needs new approval")
                    summary["skipped"].append((iid, "changed after approval"))
                    continue
                item = store.load_item(it["folder"])
                for t in store.targets(c, iid):
                    p = t["platform"]
                    if t["status"] != "pending":
                        continue
                    pc = (cfg.get("platforms") or {}).get(p) or {}
                    conn = connectors.get(p)
                    if pc.get("method") != "api" or not conn:
                        c.execute("UPDATE targets SET status='manual' WHERE item_id=? AND platform=?", (iid, p))
                        store.event(c, bid, iid, p, "info", "manual platform: package ready for the owner to post")
                        summary["manual"].append((iid, p))
                        continue
                    if dry_run:
                        out(f"[dry-run] would publish {iid} -> {p}")
                        continue
                    gap = conn.min_gap_seconds - (time.time() - last_send.get(p, 0))
                    if gap > 0:
                        time.sleep(gap)
                    try:
                        res = conn.publish(item["targets"][p], it["folder"], pc, lambda n: vault.get(bid, n))
                        last_send[p] = time.time()
                        c.execute("""UPDATE targets SET status='published', attempts=attempts+1, remote_id=?, url=?,
                                     published_at=?, last_error=NULL WHERE item_id=? AND platform=?""",
                                  (res.get("remote_id"), res.get("url"), store.iso(store.now()), iid, p))
                        store.event(c, bid, iid, p, "info", f"published {res.get('url') or res.get('remote_id')}")
                        summary["published"].append((iid, p, res.get("url")))
                    except connectors.Transient as e:
                        msg = vault.redact(str(e), bid)
                        att = t["attempts"] + 1
                        st = "failed" if att >= MAX_ATTEMPTS else "pending"
                        c.execute("UPDATE targets SET status=?, attempts=?, last_error=? WHERE item_id=? AND platform=?",
                                  (st, att, msg, iid, p))
                        store.event(c, bid, iid, p, "warn" if st == "pending" else "error", f"attempt {att}: {msg}")
                        (summary["failed"] if st == "failed" else summary["skipped"]).append((iid, p, msg))
                    except (connectors.Permanent, vault.VaultError, KeyError, OSError) as e:
                        msg = vault.redact(f"{type(e).__name__}: {e}", bid)
                        c.execute("UPDATE targets SET status='failed', attempts=attempts+1, last_error=? WHERE item_id=? AND platform=?",
                                  (msg, iid, p))
                        store.event(c, bid, iid, p, "error", msg)
                        summary["failed"].append((iid, p, msg))
                    c.commit()
                if not dry_run:
                    _finish(c, it)
    return summary


def _finish(c, it):
    st = [t["status"] for t in store.targets(c, it["id"])]
    if any(s == "pending" for s in st):
        return
    if all(s == "published" for s in st):
        new = "published"
    elif all(s in ("published", "manual") for s in st):
        new = "awaiting_manual"   # automatic part done; owner still has to post the manual platforms
    elif any(s == "published" for s in st):
        new = "partial"
    else:
        new = "failed"
    store.set_status(c, it["id"], new)
    store.event(c, it["brand"], it["id"], None, "info" if new == "published" else "error", f"item {new}")


def retry(item_id, platform=None):
    """Owner fixed the problem: put failed targets back to pending (does not touch published ones)."""
    with store.connect() as c:
        it = store.get_item(c, item_id)
        if not it:
            raise QueueError(f"no item {item_id}")
        q = "UPDATE targets SET status='pending', attempts=0 WHERE item_id=? AND status='failed'"
        a = [item_id]
        if platform:
            q += " AND platform=?"
            a.append(platform)
        n = c.execute(q, a).rowcount
        if n and it["status"] in ("failed", "partial"):
            store.set_status(c, item_id, "approved")
        store.event(c, it["brand"], item_id, platform, "info", f"retry requested for {n} target(s)")
        return n


def mark_posted(item_id, platform, url):
    """Owner posted a manual platform by hand."""
    with store.connect() as c:
        it = store.get_item(c, item_id)
        if not it:
            raise QueueError(f"no item {item_id}")
        n = c.execute("""UPDATE targets SET status='published', url=?, published_at=? WHERE item_id=? AND platform=?
                         AND status IN ('manual','pending')""", (url, store.iso(store.now()), item_id, platform)).rowcount
        if not n:
            raise QueueError("that target is not waiting for a manual post")
        store.event(c, it["brand"], item_id, platform, "info", f"posted by owner {url or ''}")
        _finish(c, store.get_item(c, item_id))


def report(brand=None, days=1):
    since = store.iso(store.now() - dt.timedelta(days=days))
    with store.connect() as c:
        q = "SELECT * FROM events WHERE ts>=?" + (" AND brand=?" if brand else "") + " ORDER BY ts"
        return c.execute(q, (since, brand) if brand else (since,)).fetchall()


def export_json(item_id):
    with store.connect() as c:
        it = store.get_item(c, item_id)
        return json.dumps({"item": dict(it), "targets": [dict(t) for t in store.targets(c, item_id)]},
                          ensure_ascii=False, indent=2) if it else None
