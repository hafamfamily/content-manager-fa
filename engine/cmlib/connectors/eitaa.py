"""eitaa.py - Eitaa channels through the official EitaaYar web service (eitaayar.ir).

Token: EitaaYar panel -> API. The token belongs to the owner's EitaaYar account, and the
channel must be registered in that panel (Channels). chat_id = the numeric channel id
shown in the panel's channel list.

platforms.json:
  "eitaa": {"enabled": true, "method": "api", "chat_id": "8718781", "username": "anar_tech_ir",
            "secret": "eitaayar_token"}
payload: {"text": "...", "media": [{"type": "photo"|"video"|"document", "path": "..."}]}  (0 or 1 media)
EitaaYar has no albums and no formatting API: send plain text (no HTML/Markdown markers).
"""

import os

from .base import Connector, Permanent
from .http import post_json_api

TEXT_MAX = 4096
FILE_MAX = 50 * 1024 * 1024


class Eitaa(Connector):
    name = "eitaa"

    def base(self, token):
        return (os.environ.get("CM_EITAA_BASE") or "https://eitaayar.ir/api/{token}/").format(token=token)

    def validate(self, payload, folder, cfg):
        errs = []
        if not cfg.get("chat_id"):
            errs.append("eitaa: chat_id (numeric id from the EitaaYar panel) is not set")
        text = payload.get("text") or ""
        media = payload.get("media") or []
        if not text and not media:
            errs.append("eitaa: empty post")
        if len(text) > TEXT_MAX:
            errs.append(f"eitaa: text is {len(text)} chars; limit {TEXT_MAX}")
        if len(media) > 1:
            errs.append("eitaa: EitaaYar sends one file per post; split the album into separate items")
        if "<b>" in text or "</" in text:
            errs.append("eitaa: text contains HTML tags; Eitaa posts are plain text")
        for m in media:
            p = os.path.join(folder, m.get("path") or "")
            if not os.path.isfile(p):
                errs.append(f"eitaa: missing file {m.get('path')}")
            elif os.path.getsize(p) > FILE_MAX:
                errs.append(f"eitaa: {m.get('path')} is over 50 MB")
        return errs

    def publish(self, payload, folder, cfg, secret):
        base = self.base(secret(cfg.get("secret") or "eitaayar_token"))
        fields = {"chat_id": str(cfg["chat_id"]),
                  "notification_disable": "1" if payload.get("disable_notification") else None}
        media = payload.get("media") or []
        if media:
            r = post_json_api(base + "sendFile", {**fields, "caption": payload.get("text") or None},
                              {"file": os.path.join(folder, media[0]["path"])})
        else:
            r = post_json_api(base + "sendMessage", {**fields, "text": payload["text"]})
        res = r.get("result") or {}
        mid = res.get("message_id") if isinstance(res, dict) else None
        if mid is None:
            raise Permanent("EitaaYar accepted the request but returned no message id")
        user = cfg.get("username")
        return {"remote_id": str(mid), "url": f"https://eitaa.com/{user}/{mid}" if user else None}

    def check(self, cfg, secret):
        me = post_json_api(self.base(secret(cfg.get("secret") or "eitaayar_token")) + "getMe")["result"]
        return {"account": "@" + str(me.get("username")), "chat_id": cfg.get("chat_id"),
                "note": "EitaaYar cannot report admin status; the channel must be listed in the panel"}
