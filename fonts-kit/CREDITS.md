# فونت‌های این مجموعه

همهٔ فونت‌ها متن‌باز (OFL / SIL Open Font License) هستند و از مخزن‌های رسمی GitHub دانلود شده‌اند.

## فونت‌های تولیدی جزوه — پوشهٔ `../fonts/`
| فونت | کاربرد | مخزن |
|---|---|---|
| Vazirmatn (Regular/Medium/SemiBold/Bold/ExtraBold) | متن فارسی جزوه | github.com/rastikerdar/vazirmatn |
| Amiri (Regular/Bold) | آیات و احادیث عربی (نسخ اعراب‌دار) | google/fonts — ofl/amiri |

## مجموعهٔ کامل — همین پوشه (`fonts-kit/`)

### فارسی (rastikerdar — github.com/rastikerdar)
- `vazirmatn/` — وزیرمتن؛ متن اصلی جزوه
- `gandom-font/` — گندم (نمایشی)
- `samim-font/` — سمیم
- `shabnam-font/` — شبنم (سبک‌های Thin تا Bold)
- `nahid-font/` — ناهید (دست‌نویس)
- `parastoo-font/` — پارستو
- `tanha-font/` — تنها
- `sahel-font/` — ساحل
- `vazir-code-font/` — وزیر کد (مونو)

### عربی و خوشنویسی (google/fonts — مجوز OFL)
- `gf/ofl/amiri/` — **امیری**؛ نسخ اعراب‌دار، بهترین برای قرآن ← در جزوه استفاده می‌شود
- `gf/ofl/scheherazadenew/` — شهزادهٔ نو (نسخ کلاسیک)
- `gf/ofl/lateef/` — لطیف (نسخ)
- `gf/ofl/arefruqaa/` — عارف رقعی (رقعه)
- `gf/ofl/reemkufi/` — ریم کوفی (کوفی)
- `gf/ofl/elmessiri/` — المصری
- `gf/ofl/markazitext/` — مارکازی
- `gf/ofl/notonaskharabic/` — نوتو نسخ عربی
- `gf/ofl/notonastaliqurdu/` — نوتو نستعلیق
- `gf/ofl/gulzar/` — گلزار (نستعلیق)

## نکتهٔ فنی (خط لولهٔ reportlab)
فونت‌هایی که با `arabic_reshaper` + `bidi` در PDF جا می‌افتند (تست‌شده):
وزیرمتن، گندم، سمیم، شبنم، ناهید، پارستو، تنها، ساحل، امیری، مارکازی، نوتو نسخ.
نستعلیق‌ها (گلزار، نوتو نستعلیق) و برخی نسخ‌های کلاسیک برای نمایش در Word/طراحی عالی‌اند
ولی در reportlab به شکل‌دهندهٔ OpenType (مثل HarfBuzz) نیاز دارند.
