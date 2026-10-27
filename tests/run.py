#!/usr/bin/env python3
"""tests/run.py - engine tests against a local mock of the Telegram/Bale bot API.

No network, no real tokens. Run:  python tests/run.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

TMP = tempfile.mkdtemp(prefix="cmtest-")
os.environ["CM_HOME"] = TMP
os.environ["CM_VAULT_PLAINTEXT"] = "1"

CALLS = []
MODE = {"fail": None, "count": 0}
TOKEN = "123456:SECRET-TOKEN-VALUE-abcdefghijklmnop"


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        parts = self.path.strip("/").split("/")
        svc, method = parts[0], parts[-1]
        CALLS.append((svc, method, body))
        if MODE["fail"] == "500":
            return self._send(500, {"ok": False, "description": "Internal"})
        if MODE["fail"] == "400":
            return self._send(400, {"ok": False, "description": f"Bad Request: chat not found {TOKEN}"})
        MODE["count"] += 1
        mid = 100 + MODE["count"]
        if method == "sendMediaGroup":
            return self._send(200, {"ok": True, "result": [{"message_id": mid}, {"message_id": mid + 1}]})
        if method == "getMe":
            return self._send(200, {"ok": True, "result": {"id": 9, "username": "test_bot"}})
        if method == "getChat":
            return self._send(200, {"ok": True, "result": {"title": "Test", "type": "channel"}})
        if method == "getChatMember":
            return self._send(200, {"ok": True, "result": {"status": "administrator"}})
        return self._send(200, {"ok": True, "result": {"message_id": mid}})

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


srv = HTTPServer(("127.0.0.1", 0), Mock)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
os.environ["CM_TELEGRAM_BASE"] = f"http://127.0.0.1:{port}/tg/bot{{token}}/"
os.environ["CM_BALE_BASE"] = f"http://127.0.0.1:{port}/bale/bot{{token}}/"

from cmlib import brand, connectors, paths, runner, store, vault  # noqa: E402

connectors.REGISTRY["telegram"].min_gap_seconds = 0
connectors.REGISTRY["bale"].min_gap_seconds = 0

PASSED, FAILED = [], []


def test(name):
    def deco(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"  ✓ {name}")
        except Exception as e:  # noqa: BLE001
            FAILED.append(name)
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return fn
    return deco


def make_item(iid, text="سلام دنیا", media=None, targets=("telegram", "bale"), **extra):
    d = os.path.join(TMP, "drafts", iid)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    for m in media or []:
        with open(os.path.join(d, m["path"]), "wb") as f:
            f.write(b"\xff\xd8fakejpeg" + iid.encode())
    item = {"id": iid, "title": "آزمایش " + iid, "kind": extra.pop("kind", "post"),
            "targets": {t: {"text": text, "media": media or []} for t in targets}, **extra}
    with open(os.path.join(d, "item.json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False)
    return d


def status(iid):
    with store.connect() as c:
        return store.get_item(c, iid)["status"], {t["platform"]: t["status"] for t in store.targets(c, iid)}


def silent(*a, **k):
    pass


@test("brand from template + platform config")
def _():
    brand.create("demo")
    p = os.path.join(paths.brand_dir("demo"), "platforms.json")
    cfg = json.load(open(p, encoding="utf-8"))
    cfg["platforms"]["telegram"].update(enabled=True, chat_id="@demo_ch")
    cfg["platforms"]["bale"].update(enabled=True, chat_id="@demo_ch")
    cfg["platforms"]["rubino"].update(enabled=True)
    json.dump(cfg, open(p, "w", encoding="utf-8"))
    assert brand.list_brands() == ["demo"]
    try:
        brand.create("Bad Name")
        raise AssertionError("bad slug accepted")
    except brand.BrandError:
        pass


@test("vault stores, lists names only, redacts")
def _():
    vault.put("demo", "telegram_token", TOKEN)
    vault.put("demo", "bale_token", TOKEN)
    assert vault.get("demo", "telegram_token") == TOKEN
    assert vault.names("demo") == ["bale_token", "telegram_token"]
    assert TOKEN not in vault.redact(f"error at /bot{TOKEN}/x", "demo")


@test("invalid package is refused (caption too long, missing file, disabled platform)")
def _():
    d = make_item("bad1", text="x" * 1100, media=[{"type": "photo", "path": "files/a.jpg"}])
    os.remove(os.path.join(d, "files", "a.jpg"))
    try:
        runner.add("demo", d)
        raise AssertionError("accepted")
    except runner.QueueError as e:
        assert "1100" in str(e) and "missing file" in str(e)
    d = make_item("bad2", targets=("telegram", "eitaa"))
    try:
        runner.add("demo", d)
        raise AssertionError("accepted")
    except runner.QueueError as e:
        assert "eitaa: not enabled" in str(e)


@test("draft is never published; approval needs owner's words")
def _():
    runner.add("demo", make_item("p1"))
    s = runner.run(out=silent)
    assert not s["published"] and status("p1")[0] == "draft"
    try:
        runner.approve("p1", "  ")
        raise AssertionError("empty approval accepted")
    except runner.QueueError:
        pass


@test("change after approval voids it")
def _():
    runner.approve("p1", "بله منتشر کن")
    f = os.path.join(paths.brand_dir("demo"), "queue", "p1", "item.json")
    it = json.load(open(f, encoding="utf-8"))
    it["targets"]["telegram"]["text"] = "متن عوض شد"
    json.dump(it, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    s = runner.run(out=silent)
    assert not s["published"] and status("p1")[0] == "draft"


@test("approved item publishes to both platforms exactly once")
def _():
    CALLS.clear()
    runner.approve("p1", "بله")
    s = runner.run(out=silent)
    assert len(s["published"]) == 2, s
    assert status("p1") == ("published", {"bale": "published", "telegram": "published"})
    n = len(CALLS)
    runner.run(out=silent)
    assert len(CALLS) == n, "published again!"
    with store.connect() as c:
        urls = {t["platform"]: t["url"] for t in store.targets(c, "p1")}
    assert urls["telegram"].startswith("https://t.me/demo_ch/") and urls["bale"] is None


@test("album uses sendMediaGroup with caption on first item")
def _():
    CALLS.clear()
    media = [{"type": "photo", "path": "files/1.jpg"}, {"type": "photo", "path": "files/2.jpg"}]
    runner.add("demo", make_item("alb", media=media, targets=("telegram",)))
    runner.approve("alb", "بله")
    runner.run(out=silent)
    svc, method, body = CALLS[-1]
    assert method == "sendMediaGroup" and b"attach://f0" in body and "سلام".encode() in body
    assert status("alb")[0] == "published"


@test("STOP switch blocks publishing")
def _():
    runner.add("demo", make_item("s1", targets=("telegram",)))
    runner.approve("s1", "بله")
    open(paths.stop_file(), "w").close()
    s = runner.run(out=silent)
    assert s["stopped"] and status("s1")[0] == "approved"
    os.remove(paths.stop_file())


@test("transient errors retry up to 3 times, then fail; retry() requeues")
def _():
    MODE["fail"] = "500"
    for _ in range(3):
        runner.run(out=silent)
    assert status("s1") == ("failed", {"telegram": "failed"}), status("s1")
    MODE["fail"] = None
    assert runner.retry("s1") == 1
    runner.run(out=silent)
    assert status("s1")[0] == "published"


@test("permanent error fails at once and never leaks the token")
def _():
    runner.add("demo", make_item("e1", targets=("telegram",)))
    runner.approve("e1", "بله")
    MODE["fail"] = "400"
    s = runner.run(out=silent)
    MODE["fail"] = None
    assert status("e1")[0] == "failed"
    msg = s["failed"][0][2]
    assert "chat not found" in msg and TOKEN not in msg
    log = open(os.path.join(paths.brand_dir("demo"), "publish.log"), encoding="utf-8").read()
    assert TOKEN not in log


@test("expired news is not published late")
def _():
    runner.add("demo", make_item("n1", targets=("telegram",), kind="news",
                                 scheduled_at="2020-01-01T09:00", expires_at="2020-01-01T12:00"))
    runner.approve("n1", "بله")
    CALLS.clear()
    runner.run(out=silent)
    assert status("n1")[0] == "expired" and not CALLS


@test("scheduled in the future waits")
def _():
    runner.add("demo", make_item("f1", targets=("telegram",), scheduled_at="2099-01-01T09:00"))
    runner.approve("f1", "بله")
    runner.run(out=silent)
    assert status("f1")[0] == "approved"
    runner.cancel("f1", "test")
    assert status("f1")[0] == "cancelled"


@test("manual platform waits for the owner, then completes")
def _():
    runner.add("demo", make_item("m1", targets=("telegram", "rubino")))
    runner.approve("m1", "بله")
    runner.run(out=silent)
    assert status("m1") == ("awaiting_manual", {"rubino": "manual", "telegram": "published"})
    runner.mark_posted("m1", "rubino", "https://rubika.ir/x")
    assert status("m1")[0] == "published"


@test("platform check reports bot admin status")
def _():
    info = connectors.get("telegram").check(brand.platform_cfg("demo", "telegram"), lambda n: vault.get("demo", n))
    assert info["bot"] == "@test_bot" and info["bot_status"] == "administrator"


@test("only one run at a time")
def _():
    with runner.Lock():
        try:
            runner.run(out=silent)
            raise AssertionError("second run allowed")
        except runner.QueueError:
            pass


@test("awake window")
def _():
    import datetime as dt
    from cmlib import awake
    t = dt.datetime(2026, 1, 1, 13, 0)
    assert awake.in_window("06:00", "15:00", t) and not awake.in_window("14:00", "15:00", t)
    assert awake.in_window("22:00", "02:00", dt.datetime(2026, 1, 1, 23, 0))
    assert awake.in_window("00:00", "00:00", dt.datetime(2026, 1, 1, 3, 0))  # all day


srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(PASSED)} از {len(PASSED) + len(FAILED)} تست قبول شد.")
sys.exit(1 if FAILED else 0)
