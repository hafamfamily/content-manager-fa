"""rubika.py - Rubika channels through the official Rubika Bot API v3 (botapi.rubika.ir).

Token: Rubika's official BotFather. The bot must be an admin of the channel with permission
to post. chat_id = the channel's chat id (object guid, starts with "c0"); find it with
`cm platform test` after forwarding one channel post to the bot.

platforms.json:
  "rubika": {"enabled": true, "method": "api", "chat_id": "c0...", "secret": "rubika_token"}
payload: {"text": "...", "media": [{"type": "photo"|"video"|"document", "path": "..."}]}  (0 or 1 media)
Files: requestSendFile(type) -> upload_url -> POST file -> file_id -> sendFile(file_id, text).
"""

import json
import os
import socket
import urllib.error
import urllib.request

from .base import Connector, Permanent, Transient
from .http import UA, multipart

TEXT_MAX = 4096
FILE_TYPES = {"photo": "Image", "video": "Video", "document": "File"}
TRANSIENT_STATUS = {"SERVER_ERROR", "TOO_REQUESTS", "INTERNAL_SERVER_ERROR"}


def _req(url, body=None, files=None, timeout=300):
    if files:
        data, ctype = multipart(body or {}, files)
    else:
        data, ctype = json.dumps(body or {}, ensure_ascii=False).encode("utf-8"), "application/json"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, "User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        if e.code >= 500 or e.code == 429:
            raise Transient(f"HTTP {e.code}")
        raise Permanent(f"HTTP {e.code}")
    except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
        raise Transient(f"network: {type(e).__name__}: {getattr(e, 'reason', e)}")
    try:
        r = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise Transient("invalid JSON from Rubika")
    st = r.get("status")
    if st != "OK":
        msg = f"{st}: {r.get('dev_message') or ''}".strip()
        raise (Transient if st in TRANSIENT_STATUS else Permanent)(msg)
    return r.get("data") or {}


class Rubika(Connector):
    name = "rubika"

    def base(self, token):
        return (os.environ.get("CM_RUBIKA_BASE") or "https://botapi.rubika.ir/v3/{token}/").format(token=token)

    def validate(self, payload, folder, cfg):
        errs = []
        if not cfg.get("chat_id"):
            errs.append("rubika: chat_id (channel guid) is not set")
        text = payload.get("text") or ""
        media = payload.get("media") or []
        if not text and not media:
            errs.append("rubika: empty post")
        if len(text) > TEXT_MAX:
            errs.append(f"rubika: text is {len(text)} chars; limit {TEXT_MAX}")
        if len(media) > 1:
            errs.append("rubika: one file per post; split the album into separate items")
        if "<b>" in text or "</" in text:
            errs.append("rubika: text contains HTML tags; send plain text")
        for m in media:
            if m.get("type") not in FILE_TYPES:
                errs.append(f"rubika: unknown media type {m.get('type')!r}")
            if not os.path.isfile(os.path.join(folder, m.get("path") or "")):
                errs.append(f"rubika: missing file {m.get('path')}")
        return errs

    def publish(self, payload, folder, cfg, secret):
        base = self.base(secret(cfg.get("secret") or "rubika_token"))
        chat = cfg["chat_id"]
        media = payload.get("media") or []
        text = payload.get("text") or ""
        if media:
            m = media[0]
            up = _req(base + "requestSendFile", {"type": FILE_TYPES[m["type"]]})
            url = up.get("upload_url")
            if not url:
                raise Permanent("Rubika returned no upload_url")
            fid = _req(url, files={"file": os.path.join(folder, m["path"])}).get("file_id")
            if not fid:
                raise Permanent("Rubika upload returned no file_id")
            body = {"chat_id": chat, "file_id": fid}
            if text:
                body["text"] = text
            d = _req(base + "sendFile", body)
        else:
            d = _req(base + "sendMessage", {"chat_id": chat, "text": text})
        mid = d.get("message_id")
        if mid is None:
            raise Permanent("Rubika accepted the request but returned no message id")
        return {"remote_id": str(mid), "url": None}

    def check(self, cfg, secret):
        base = self.base(secret(cfg.get("secret") or "rubika_token"))
        bot = (_req(base + "getMe").get("bot") or {})
        out = {"bot": "@" + str(bot.get("username"))}
        if cfg.get("chat_id"):
            chat = (_req(base + "getChat", {"chat_id": cfg["chat_id"]}).get("chat") or {})
            out.update({"chat": chat.get("title"), "chat_type": chat.get("chat_type")})
        upd = _req(base + "getUpdates", {"limit": 50}).get("updates") or []
        seen = set()
        for u in upd:
            msg = u.get("new_message") or {}
            fwd = msg.get("forwarded_from") or {}
            for k in ("from_chat_id", "from_sender_id"):
                if fwd.get(k):
                    seen.add(f"{fwd.get('type_from')}: {fwd[k]}")
            if u.get("chat_id"):
                seen.add(f"chat: {u['chat_id']}")
        if seen:
            out["ids_seen_in_updates"] = ", ".join(sorted(seen))
        return out
