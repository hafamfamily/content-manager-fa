"""formats.py - write a post once, render it correctly for every platform.

Source format: a small HTML subset (the same tags Telegram accepts):
  <b> <i> <u> <s> <code> <blockquote> <a href="...">text</a>
Links are always words with a link behind them, never a bare address in the text.

What each platform really shows (tested on the owner's channels, 1405-08-05):
  telegram  HTML: everything
  bale      Markdown: *bold*, [text](url); italic and HTML do not render -> dropped
  rubika    text + metadata (UTF-16 offsets): Bold, Underline, Strike, Link render;
            Italic and Quote do not -> dropped
  eitaa     EitaaYar API takes plain text only -> tags dropped, link text kept, URL dropped
"""

import re
from html import unescape
from html.parser import HTMLParser

INLINE = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline",
          "s": "strike", "del": "strike", "code": "code", "blockquote": "quote", "a": "link"}


class _Parser(HTMLParser):
    """Turns the HTML subset into plain text + a list of spans (kind, start, end, url) in str indexes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.pos = 0
        self.open = []
        self.spans = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.handle_data("\n")
            return
        kind = INLINE.get(tag)
        if kind:
            self.open.append((kind, self.pos, dict(attrs).get("href")))

    def handle_endtag(self, tag):
        kind = INLINE.get(tag)
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == kind:
                k, start, url = self.open.pop(i)
                if self.pos > start:
                    self.spans.append((k, start, self.pos, url))
                break

    def handle_data(self, data):
        self.text.append(data)
        self.pos += len(data)


def parse(html):
    p = _Parser()
    p.feed(html)
    p.close()
    return "".join(p.text), sorted(p.spans, key=lambda s: (s[1], -s[2]))


def _u16(s):
    return len(s.encode("utf-16-le")) // 2


def to_telegram(html):
    return {"text": html, "parse_mode": "HTML"}


def to_bale(html):
    text, spans = parse(html)
    marks = {}  # index -> list of strings to insert (opening after closing)
    for kind, a, b, url in spans:
        if kind == "bold":
            marks.setdefault(a, []).append("*")
            marks.setdefault(b, []).insert(0, "*")
        elif kind == "link" and url:
            marks.setdefault(a, []).append("[")
            marks.setdefault(b, []).insert(0, f"]({url})")
    out = []
    for i, ch in enumerate(text + "\0"):
        out.extend(marks.get(i, []))
        if ch != "\0":
            out.append(ch)
    return {"text": "".join(out), "parse_mode": "Markdown"}


RUBIKA_TYPES = {"bold": "Bold", "underline": "Underline", "strike": "Strike", "code": "Mono", "link": "Link"}


def to_rubika(html):
    text, spans = parse(html)
    parts = []
    for kind, a, b, url in spans:
        t = RUBIKA_TYPES.get(kind)
        if not t or (t == "Link" and not url):
            continue
        p = {"type": t, "from_index": _u16(text[:a]), "length": _u16(text[a:b])}
        if t == "Link":
            p["link_url"] = url
        parts.append(p)
    out = {"text": text}
    if parts:
        out["metadata"] = {"meta_data_parts": parts[:30]}
    return out


def to_plain(html):
    text, _ = parse(html)
    return {"text": text}


RENDER = {"telegram": to_telegram, "bale": to_bale, "rubika": to_rubika, "eitaa": to_plain}


def render(platform, html):
    """Return the payload fields (text, parse_mode, metadata) for one platform."""
    return RENDER.get(platform, to_plain)(html)


BARE_URL = re.compile(r"(?<![\"'=(])\bhttps?://\S+|\b(?:t\.me|instagram\.com|eitaa\.com|ble\.ir|rubika\.ir)/\S+")


def bare_links(html):
    """Addresses written as plain text (outside <a>) - the owner's rule says: link a word instead."""
    stripped = re.sub(r"<a\b[^>]*>.*?</a>", "", html, flags=re.S)
    stripped = re.sub(r"<[^>]+>", "", stripped)
    return BARE_URL.findall(unescape(stripped))
