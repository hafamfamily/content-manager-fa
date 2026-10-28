"""brand.py - one folder per brand; nothing brand-specific lives in the code.

brands/<brand>/
  brand.md         who we are: topic, audience, voice, red lines (read by the Claude skills)
  brand.json       visual identity: handle, colors, fonts, digits
  platforms.json   connections and rules for the engine (no secrets here):
    {"timezone": "Asia/Tehran",
     "awake": {"from": "06:00", "to": "15:00"},
     "news_max_age_hours": 24,
     "platforms": {"telegram": {"enabled": true, "method": "api", "chat_id": "@x", "secret": "telegram_token"},
                   "rubino":   {"enabled": true, "method": "manual"}}}
  queue/<item-id>/item.json + files
"""

import json
import os
import re
import shutil

from . import paths

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "brands", "example")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


class BrandError(Exception):
    pass


def list_brands():
    d = paths.brands_dir()
    if not os.path.isdir(d):
        return []
    return sorted(b for b in os.listdir(d) if os.path.isfile(os.path.join(d, b, "platforms.json")))


def create(slug):
    if not SLUG.match(slug):
        raise BrandError("brand name: lowercase English letters, digits and '-' only (e.g. my-brand)")
    dst = paths.brand_dir(slug)
    if os.path.exists(dst):
        raise BrandError(f"brand {slug} already exists: {dst}")
    shutil.copytree(TEMPLATE, dst)
    os.makedirs(os.path.join(dst, "queue"), exist_ok=True)
    return dst


def config(slug):
    p = os.path.join(paths.brand_dir(slug), "platforms.json")
    if not os.path.isfile(p):
        raise BrandError(f"brand {slug} not found (no {p})")
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def platform_cfg(slug, platform):
    return (config(slug).get("platforms") or {}).get(platform)
