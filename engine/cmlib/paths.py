"""paths.py - where brands, the database, secrets and logs live.

Home (data, never inside the git repo):
  1. env CM_HOME
  2. ~/.content-manager-fa.json  {"home": "..."}
  3. ~/content-manager-fa
Layout under home:
  brands/<brand>/brand.md, platforms.json, queue/<item>/item.json, publish.log
  cm.db           queue + ledger (SQLite)
  .secrets/       DPAPI-encrypted vault (Windows) — never committed
  STOP            if this file exists, nothing is published
"""

import json
import os

CONF = os.path.join(os.path.expanduser("~"), ".content-manager-fa.json")


def conf():
    try:
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_conf(c):
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def home():
    return os.environ.get("CM_HOME") or conf().get("home") or os.path.join(os.path.expanduser("~"), "content-manager-fa")


def brands_dir():
    return os.path.join(home(), "brands")


def brand_dir(brand):
    return os.path.join(brands_dir(), brand)


def db_path():
    return os.path.join(home(), "cm.db")


def secrets_dir():
    return os.path.join(home(), ".secrets")


def stop_file():
    return os.path.join(home(), "STOP")


def lock_file():
    return os.path.join(home(), ".run.lock")
