"""botapi.py - Telegram and Bale (Bale's bot API follows Telegram's).

platforms.json entry:
  "telegram": {"enabled": true, "method": "api", "chat_id": "@channel", "secret": "telegram_token"}
  "bale":     {"enabled": true, "method": "api", "chat_id": "@channel", "secret": "bale_token"}

item.json target payload:
  {"text": "...", "parse_mode": "HTML"|"Markdown"|null,
   "media": [{"type": "photo"|"video"|"document", "path": "files/a.jpg"}],
   "disable_notification": false}
  - no media: sendMessage(text)
  - one media: sendPhoto/sendVideo/sendDocument with text as caption
  - 2..10 photos/videos: sendMediaGroup, caption on the first item
"""

import os

from .base import Connector, Permanent
from .http import post_json_api

TEXT_MAX = 4096
CAPTION_MAX = 1024
FILE_MAX = 50 * 1024 * 1024
SEND = {"photo": "sendPhoto", "video": "sendVideo", "document": "sendDocument"}


class BotApi(Connector):
    base_env = None
    base_default = None
    public_url = None   # e.g. "https://t.me/{username}/{id}"

    def base(self, token):
        return (os.environ.get(self.base_env) or self.base_default).format(token=token)

    def validate(self, payload, folder, cfg):
        errs = []
        if not cfg.get("chat_id"):
            errs.append(f"{self.name}: chat_id is not set in platforms.json")
        text = payload.get("text") or ""
        media = payload.get("media") or []
        if not text and not media:
            errs.append(f"{self.name}: empty post (no text, no media)")
        limit = CAPTION_MAX if media else TEXT_MAX
        if len(text) > limit:
            errs.append(f"{self.name}: text is {len(text)} chars; limit {'caption' if media else 'message'} = {limit}")
        if len(media) > 10:
            errs.append(f"{self.name}: at most 10 media per post (got {len(media)})")
        for m in media:
            if m.get("type") not in SEND:
                errs.append(f"{self.name}: unknown media type {m.get('type')!r}")
            p = os.path.join(folder, m.get("path") or "")
            if not os.path.isfile(p):
                errs.append(f"{self.name}: missing file {m.get('path')}")
            elif os.path.getsize(p) > FILE_MAX:
                errs.append(f"{self.name}: {m.get('path')} is over 50 MB")
        if len(media) > 1 and any(m.get("type") == "document" for m in media):
            errs.append(f"{self.name}: documents cannot be mixed in an album; send them as separate items")
        return errs

    def _url(self, cfg, msg_id):
        ch = str(cfg.get("chat_id") or "")
        if self.public_url and ch.startswith("@") and msg_id:
            return self.public_url.format(username=ch[1:], id=msg_id)
        return None

    def publish(self, payload, folder, cfg, secret):
        token = secret(cfg.get("secret") or f"{self.name}_token")
        base = self.base(token)
        chat = cfg["chat_id"]
        text = payload.get("text") or ""
        pm = payload.get("parse_mode")
        common = {"chat_id": chat, "disable_notification": "true" if payload.get("disable_notification") else None}
        media = payload.get("media") or []
        if not media:
            r = post_json_api(base + "sendMessage", {**common, "text": text, "parse_mode": pm})
            mid = r["result"].get("message_id")
        elif len(media) == 1:
            m = media[0]
            r = post_json_api(base + SEND[m["type"]], {**common, "caption": text or None, "parse_mode": pm},
                              {m["type"]: os.path.join(folder, m["path"])})
            mid = r["result"].get("message_id")
        else:
            group, files = [], {}
            for i, m in enumerate(media):
                key = f"f{i}"
                entry = {"type": m["type"], "media": f"attach://{key}"}
                if i == 0 and text:
                    entry["caption"] = text
                    if pm:
                        entry["parse_mode"] = pm
                group.append(entry)
                files[key] = os.path.join(folder, m["path"])
            r = post_json_api(base + "sendMediaGroup", {**common, "media": group}, files)
            res = r.get("result")
            mid = res[0].get("message_id") if isinstance(res, list) and res else None
        if mid is None:
            raise Permanent("server accepted the request but returned no message id")
        return {"remote_id": str(mid), "url": self._url(cfg, mid)}

    def check(self, cfg, secret):
        base = self.base(secret(cfg.get("secret") or f"{self.name}_token"))
        me = post_json_api(base + "getMe")["result"]
        out = {"bot": "@" + str(me.get("username"))}
        if cfg.get("chat_id"):
            chat = post_json_api(base + "getChat", {"chat_id": cfg["chat_id"]})["result"]
            mem = post_json_api(base + "getChatMember", {"chat_id": cfg["chat_id"], "user_id": me.get("id")})["result"]
            out.update({"chat": chat.get("title"), "chat_type": chat.get("type"), "bot_status": mem.get("status")})
        return out


class Telegram(BotApi):
    name = "telegram"
    base_env = "CM_TELEGRAM_BASE"
    base_default = "https://api.telegram.org/bot{token}/"
    public_url = "https://t.me/{username}/{id}"


class Bale(BotApi):
    name = "bale"
    base_env = "CM_BALE_BASE"
    base_default = "https://tapi.bale.ai/bot{token}/"
    public_url = None   # Bale's public post-link format is not documented; not guessed
