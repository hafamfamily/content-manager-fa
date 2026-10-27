"""http.py - small standard-library HTTP helpers shared by connectors."""

import json
import mimetypes
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .base import Permanent, Transient

UA = "content-manager-fa/0.1"


def multipart(fields, files):
    b = uuid.uuid4().hex
    body = bytearray()
    for k, v in (fields or {}).items():
        if v is None:
            continue
        if not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode() + v.encode("utf-8") + b"\r\n"
    for k, p in (files or {}).items():
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        name = os.path.basename(p)
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
        with open(p, "rb") as f:
            body += f.read()
        body += b"\r\n"
    body += f"--{b}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={b}"


def post_json_api(url, fields=None, files=None, timeout=300):
    """POST to a Telegram-style API; returns the decoded JSON; maps failures to Transient/Permanent."""
    if files:
        data, ctype = multipart(fields, files)
    else:
        data = urllib.parse.urlencode({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                                       for k, v in (fields or {}).items() if v is not None}).encode()
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, "User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            body = {"ok": False, "description": f"HTTP {code}"}
        desc = body.get("description") or f"HTTP {code}"
        if code == 429:
            ra = (body.get("parameters") or {}).get("retry_after")
            raise Transient(f"rate limited: {desc}", retry_after=ra)
        if code >= 500:
            raise Transient(f"server error {code}: {desc}")
        raise Permanent(f"HTTP {code}: {desc}")
    except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
        raise Transient(f"network: {type(e).__name__}: {getattr(e, 'reason', e)}")
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise Transient("invalid JSON from server")
    if not body.get("ok", False):
        raise Permanent(body.get("description") or "request not ok")
    return body
