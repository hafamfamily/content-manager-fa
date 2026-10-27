#!/usr/bin/env python3
"""make_card.py - a branded Persian image card (1080x1350) rendered by Chrome/Edge headless.

  python make_card.py <brand> <out.png> --title "..." [--body "..."] [--quote "..."] [--tag "..."]

Uses brands/<brand>/brand.json (colors, name, handle) and an optional logo at
brands/<brand>/logo.png|jpg. Persian shaping is done by the browser, so text is always correct.
"""

import argparse
import base64
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cmlib import paths  # noqa: E402

FONT_DIRS = [os.path.join(os.path.dirname(HERE), "assets", "fonts")]
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            shutil.which("chromium") or "", shutil.which("google-chrome") or ""]


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def font_face(name, file, weight):
    for d in FONT_DIRS:
        p = os.path.join(d, file)
        if os.path.isfile(p):
            return f"@font-face{{font-family:{name};src:url(data:font/ttf;base64,{b64(p)});font-weight:{weight}}}"
    return ""


def build(brand, title, body, quote, tag):
    bdir = paths.brand_dir(brand)
    with open(os.path.join(bdir, "brand.json"), encoding="utf-8-sig") as f:
        b = json.load(f)
    logo = next((os.path.join(bdir, n) for n in ("logo.png", "logo.jpg") if os.path.isfile(os.path.join(bdir, n))), None)
    logo_html = f'<img class="logo" src="data:image/jpeg;base64,{b64(logo)}">' if logo else ""
    e = html.escape
    p, a = b.get("primary", "#A3141E"), b.get("accent", "#1A1A1A")
    fonts = font_face("V", "Vazirmatn-Black.ttf", 900) + font_face("V", "Vazirmatn-Bold.ttf", 700) + \
        font_face("V", "Vazirmatn-Regular.ttf", 400)
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>
{fonts}
*{{margin:0;box-sizing:border-box}}
body{{width:1080px;height:1350px;font-family:V,Tahoma,sans-serif;background:#F6F1EA;color:{a};
 display:flex;flex-direction:column;padding:90px 84px 70px;position:relative;overflow:hidden}}
.band{{position:absolute;top:0;right:0;left:0;height:22px;background:{p}}}
.tag{{align-self:flex-start;background:{p};color:#fff;font-weight:700;font-size:34px;padding:12px 30px;border-radius:999px}}
h1{{font-weight:900;font-size:78px;line-height:1.35;margin-top:56px}}
.body{{font-weight:400;font-size:40px;line-height:1.7;margin-top:40px;color:#3a3a3a}}
.quote{{margin-top:48px;border-right:12px solid {p};background:#fff;padding:36px 40px;font-weight:700;font-size:44px;line-height:1.6;border-radius:18px}}
.foot{{margin-top:auto;display:flex;align-items:center;gap:26px;font-weight:700;font-size:34px}}
.logo{{width:96px;height:96px;border-radius:22px;object-fit:cover}}
.handle{{direction:ltr;unicode-bidi:isolate;display:inline-block;color:{p}}}
</style></head><body><div class="band"></div>
{f'<div class="tag">{e(tag)}</div>' if tag else ''}
<h1>{e(title)}</h1>
{f'<div class="body">{e(body)}</div>' if body else ''}
{f'<div class="quote">{e(quote)}</div>' if quote else ''}
<div class="foot">{logo_html}<div>{e(b.get("name_fa") or b.get("name", ""))}<br><span class="handle">{e(b.get("handle", ""))}</span></div></div>
</body></html>"""


def render(page_html, out):
    browser = next((x for x in BROWSERS if x and os.path.isfile(x)), None)
    if not browser:
        sys.exit("no Chrome/Edge found")
    tmp = tempfile.mkdtemp(prefix="card-")
    src = os.path.join(tmp, "card.html")
    with open(src, "w", encoding="utf-8") as f:
        f.write(page_html)
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--user-data-dir={os.path.join(tmp, 'profile')}", "--window-size=1080,1350",
                    f"--screenshot={out}", "file:///" + src.replace("\\", "/")],
                   capture_output=True, timeout=120)
    shutil.rmtree(tmp, ignore_errors=True)
    if not os.path.isfile(out):
        sys.exit("render failed")
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("brand")
    ap.add_argument("out")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--quote", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    print(render(build(a.brand, a.title, a.body, a.quote, a.tag), a.out))


if __name__ == "__main__":
    main()
