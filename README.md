# content-manager-fa

> **English:** Unified Persian content management across 8 platforms (Instagram, YouTube, Aparat, Telegram, Bale, Eitaa, Rubika, Rubino) for any brand: Claude handles research, drafting, branded images and quality checks with owner approval, and a standalone engine (`engine/cm.py`) publishes approved posts on schedule from the owner's own computer, without Claude. MIT licensed.

مدیریت یکپارچهٔ محتوای فارسی در ۸ سکو (تلگرام، بله، ایتا، روبیکا، روبینو، اینستاگرام، یوتیوب، آپارات)،
برای **هر برند و هر موضوع**.

- **لایهٔ هوش (Claude):** پیدا کردن تازه‌ها با منبع، سه پیشنهاد، نوشتن یک‌بارهٔ متن، تصویر برند، کنترل کیفیت،
  پرسیدن اجازه.
- **موتور اجرایی (`engine/cm.py`):** بدون Claude روی کامپیوتر صاحب برند اجرا می‌شود؛ فقط محتوای تأییدشده را
  سر ساعت منتشر می‌کند؛ تلاش مجدد، دفتر انتشار، گزارش، کلید توقف، بستهٔ آماده برای سکوهای دستی.
- **رابط بین دو لایه:** پوشهٔ بسته (`item.json` + فایل‌ها) و پایگاه SQLite.

## اسکیل‌ها
| اسکیل | کار |
|---|---|
| `cm-setup` | برند تازه، سکوها، توکن امن، آزمایش اتصال، زمان‌بند |
| `cm-create` | خط تولید روزانه: تازه‌ها با منبع ← سه پیشنهاد ← متن و تصویر ← بسته |
| `cm-publish` | پیش‌نمایش، اجازه، انتشار، بستهٔ دستی، گزارش، توقف |

## وضعیت سکوها (خلاصه؛ جزئیات در `docs/platforms.md`)
خودکار: تلگرام، بله، ایتا (متن ساده)، روبیکا (تک‌فایل). بستهٔ دستی: روبینو، آپارات؛ اینستاگرام و یوتیوب
بسته به اتصال لایهٔ Claude، وگرنه بستهٔ دستی.

## شروع سریع (ویندوز، پایتون ۳.۱۰+)
```powershell
python engine\cm.py home "E:\Claude\content"
python engine\cm.py brand new my-brand
python engine\cm.py secret set my-brand telegram_token     # مقدار در ترمینال، رمزشده با DPAPI
python engine\cm.py platform test my-brand telegram
python engine\cm.py schedule --apply
```

## دستورها
`home` · `brand new|list` · `secret set|import|list|delete` · `platform test` · `add` · `list` · `show` ·
`approve --by` · `reject` · `cancel` · `run [--dry-run] [--item]` · `retry` · `package` · `posted` ·
`stop` · `resume` · `awake` · `schedule [--apply|--remove]` · `report`

تصویر برند: `python engine\make_card.py <brand> out.png --title "..." --body "..." --tag "..."` (Chrome یا Edge).

## ایمنی
- هیچ چیز بدون تأیید صریح صاحب برند منتشر نمی‌شود؛ تأیید به هش محتوا بسته است و هر تغییری آن را باطل می‌کند.
- توکن‌ها با DPAPI ویندوز رمز می‌شوند و هرگز چاپ یا در گیت ذخیره نمی‌شوند (`.gitignore`).
- `cm stop` همه‌چیز را فوراً متوقف می‌کند.
- فقط API رسمی هر سکو؛ نه سلف‌بات و نه گرفتن رمز حساب. آدرس خام در متن پذیرفته نمی‌شود.

## تست
```bash
python tests/run.py          # موتور، بدون اینترنت و بدون توکن واقعی
python tests/test_formats.py # قالب متن هر سکو
```

## مجوز
همهٔ حقوق برای صاحب مخزن محفوظ است تا مجوز را خودش انتخاب کند. بخش‌هایی که از instagram-fa و youtube-fa
می‌آیند تحت MIT و با حفظ نام صاحبان حق‌اند؛ فونت وزیرمتن تحت SIL OFL 1.1؛ ببینید `NOTICE.md`.
