"""manual.py - ready-to-post packages for platforms the owner posts by hand.

Some platforms have no official publishing API (Rubino), or posting needs the owner's own hands
(choosing a file in a browser, YouTube from an unverified project). For those the engine writes a
folder the owner can use in under a minute:

  <home>/brands/<brand>/manual/<item>/<platform>/
      01.jpg, 02.jpg ... / video.mp4     media in posting order
      متن.txt                             caption / description, plain text, no bare links
      راهنما.txt                          what to tap, in order, for this platform

The caption is rendered from the item's shared "html" (or the target's own text). Links stay as words;
their addresses are dropped, because these platforms cannot hide an address behind a word.
"""

import os
import re
import shutil

from . import formats, paths

GUIDES = {
    "rubino": [
        "اپ روبیکا را باز کن، بخش روبینو، دکمهٔ + (پست جدید).",
        "فایل‌ها را به همان ترتیب شماره انتخاب کن (چند عکس = پست چندتایی).",
        "متن «متن.txt» را کپی کن و در کپشن بچسبان.",
        "انتشار را بزن و لینک پست را به Claude بده (cm posted <item> rubino --url ...).",
    ],
    "instagram": [
        "اپ اینستاگرام، + ، پست یا ریلز.",
        "فایل‌ها را به ترتیب شماره انتخاب کن.",
        "متن «متن.txt» را در کپشن بچسبان.",
        "Share را بزن و لینک را به Claude بده.",
    ],
    "aparat": [
        "aparat.com ← بارگذاری ویدیو ← «انتخاب ویدیو» و فایل video را انتخاب کن.",
        "خط اول «متن.txt» عنوان است؛ بقیه توضیحات.",
        "برچسب‌ها (حداکثر ۵) و دسته را از «متن.txt» بردار.",
        "انتشار ویدیو را بزن و لینک را به Claude بده.",
    ],
    "youtube": [
        "studio.youtube.com ← Create ← Upload videos و فایل video را انتخاب کن.",
        "مطمئن شو کانال درست انتخاب شده (گوشهٔ بالا).",
        "عنوان و توضیحات و تگ‌ها را از «متن.txt» بردار؛ ویدیوی عمودی زیر ۳ دقیقه خودش Shorts می‌شود.",
        "Visibility: Public ← Publish، و لینک را به Claude بده.",
    ],
}
DEFAULT_GUIDE = ["فایل‌ها را به ترتیب شماره بفرست.", "متن «متن.txt» را بچسبان.", "لینک پست را به Claude بده."]
VIDEO_PLATFORMS = ("youtube", "aparat")


def _caption(item, platform):
    pl = dict((item.get("targets") or {}).get(platform) or {})
    if pl.get("text"):
        txt = pl["text"]
        if "<" in txt and ">" in txt:
            txt = formats.to_plain(txt)["text"]
        return txt
    if item.get("html"):
        return formats.to_plain(item["html"])["text"]
    return ""


def _media(item, platform):
    pl = (item.get("targets") or {}).get(platform) or {}
    return pl.get("media") or item.get("media") or []


def package(brand, item, folder, platform, home=None):
    """Write the package folder; returns its path. Safe to call again (rewrites the folder)."""
    base = os.path.join(home or paths.home(), "brands", brand, "manual", item["id"], platform)
    if os.path.isdir(base):
        shutil.rmtree(base)
    os.makedirs(base)
    for n, m in enumerate(_media(item, platform), 1):
        src = os.path.join(folder, m["path"])
        ext = os.path.splitext(src)[1].lower()
        name = "video" + ext if m.get("type") == "video" else f"{n:02d}{ext}"
        shutil.copy2(src, os.path.join(base, name))

    lines = []
    pl = (item.get("targets") or {}).get(platform) or {}
    if platform in VIDEO_PLATFORMS:
        lines += [pl.get("title") or item.get("title", ""), ""]
    lines.append(_caption(item, platform).strip())
    tags = pl.get("tags") or item.get("tags") or []
    if tags:
        if platform == "aparat":
            tags = tags[:5]
        lines += ["", "برچسب‌ها: " + "، ".join(tags)]
    if pl.get("category"):
        lines += ["دسته: " + pl["category"]]
    text = "\n".join(lines).strip() + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    with open(os.path.join(base, "متن.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    steps = GUIDES.get(platform, DEFAULT_GUIDE)
    with open(os.path.join(base, "راهنما.txt"), "w", encoding="utf-8") as f:
        f.write(f"{item.get('title', '')} — {platform}\n\n")
        f.write("\n".join(f"{i}. {s}".replace("<item>", item["id"]) for i, s in enumerate(steps, 1)) + "\n")
    return base
