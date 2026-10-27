"""Platform registry. A platform without a connector here is treated as manual:
the engine prepares a ready-to-post package and the owner posts it by hand."""

from .base import Connector, Permanent, Transient  # noqa: F401
from .botapi import Bale, Telegram
from .eitaa import Eitaa
from .rubika import Rubika

REGISTRY = {c.name: c for c in (Telegram(), Bale(), Eitaa(), Rubika())}

# Every platform the system knows about, in display order, with its Persian name.
PLATFORMS = {
    "instagram": "اینستاگرام", "youtube": "یوتیوب", "aparat": "آپارات", "telegram": "تلگرام",
    "bale": "بله", "eitaa": "ایتا", "rubika": "روبیکا", "rubino": "روبینو",
}


def get(name):
    return REGISTRY.get(name)
