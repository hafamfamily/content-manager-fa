"""tests/test_formats.py - the one-source, every-platform renderer.  python tests/test_formats.py"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from cmlib import formats  # noqa: E402

H = ('<b>💡 نکته</b> و <i>کج</i> و <u>زیر</u>\n<blockquote>نقل</blockquote>\n'
     '📸 <a href="https://instagram.com/anar_tech_ir">اینستاگرام انار</a>')
ok = 0


def check(name, cond):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + name)
    ok += bool(cond)
    return cond


tg = formats.render("telegram", H)
check("telegram keeps HTML", tg == {"text": H, "parse_mode": "HTML"})

bl = formats.render("bale", H)
check("bale: *bold*, [link](url), italic dropped",
      bl["text"].startswith("*💡 نکته*") and "[اینستاگرام انار](https://instagram.com/anar_tech_ir)" in bl["text"]
      and "<" not in bl["text"] and "کج" in bl["text"])

rb = formats.render("rubika", H)
types = [p["type"] for p in rb["metadata"]["meta_data_parts"]]
check("rubika: Bold/Underline/Link only", types == ["Bold", "Underline", "Link"])
text = rb["text"]
link = rb["metadata"]["meta_data_parts"][-1]
u16 = text.encode("utf-16-le")
seg = u16[link["from_index"] * 2:(link["from_index"] + link["length"]) * 2].decode("utf-16-le")
check("rubika: UTF-16 offsets point at the link words (emoji counts as 2)", seg == "اینستاگرام انار")
bold = rb["metadata"]["meta_data_parts"][0]
check("rubika: bold covers emoji + word", u16[:bold["length"] * 2].decode("utf-16-le") == "💡 نکته")

ei = formats.render("eitaa", H)
check("eitaa: plain text, no URL", "<" not in ei["text"] and "instagram.com" not in ei["text"] and "اینستاگرام انار" in ei["text"])

check("bare address detected", formats.bare_links("ببین t.me/anar_tech_ir") == ["t.me/anar_tech_ir"])
check("linked word is fine", formats.bare_links('<a href="https://t.me/x">تلگرام</a>') == [])
print(f"\n{ok} از 8 تست قالب قبول شد.")
sys.exit(0 if ok == 8 else 1)
