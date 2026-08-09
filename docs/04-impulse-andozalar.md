# Impulse Loyihalaridan Olinadigan Andozalar (Texnik Audit)

> Ushbu hujjat `impulse-erp` va `impulse-moliya-web` loyihalarining texnik auditi asosida tayyorlandi. Maqsad: Mfaktor uchun noldan qurmasdan, **isbotlangan, ishlab turgan modullardan andoza olish** — vaqt va xarajatni 2–3 barobar tejash.

## 1. Impulse ekotizimi — nima qurilgan?

### 1.1. Impulse ERP (asosiy tizim)
- **Texnologiya:** Python + Flask + SQLAlchemy, Jinja2 + HTMX (SPA emas — sodda va tez), SQLite → PostgreSQL (Railway deploy)
- **Falsafa:** har bir amal (bron, to'lov, qarz) avtomatik ravishda kerakli bo'limga vazifa/signal bo'lib o'tadi — hech narsa qo'lda ikki marta yozilmaydi
- **20 ta modul:** CRM, sotuv, moliya, HR, KPI, ombor, tadbirlar, davomat, Instagram-analitika, telefoniya va h.k.

### 1.2. Impulse Moliya (alohida moliya ERP + Telegram bot)
- Telegram bot orqali kirim-chiqim kiritish (hamyonlar, statyalar, kontragentlar)
- **AI Vision:** chek/to'lov skrinshoti rasmini yuborsangiz — Claude summa, karta, sana, komissiyani o'zi o'qib, tranzaksiya tayyorlaydi
- Byudjet, qarzdorlar, dividend, BEP (zararsizlik nuqtasi), takrorlanuvchi to'lovlar
- Yangi veb-qatlam: Next.js (erp_web)

## 2. Mfaktor uchun tayyor andozalar xaritasi

Quyidagi jadval — Impulse'da **allaqachon yozilgan va ishlayotgan** kod Mfaktor'ning qaysi ehtiyojini yopishi:

| # | Impulse moduli | Nima qiladi | Mfaktor'da qo'llanishi |
|---|---|---|---|
| 1 | `core/ai_assistant.py` | Claude API + tool-use agent loop: DB'dan ma'lumot olib, o'zbek tilida biznes savol-javob ("Bu oy qancha kirim?", "Nimani optimallashtiraylik?"). Suhbat xotirasi, prompt caching | **Boshqaruv AI-tahlilchisi:** "Bu oy nechta lead keldi, konversiya qancha?" — rahbariyat Telegram'da so'raydi, AI CRM'dan javob beradi |
| 2 | `models/crm.py` | Lead voronkasi (bosqichlar, yo'qotish sabablari ro'yxati, manbalar), Mijoz-360 (umrbod qiymat, segment, churn-xavf) | **Kurs sotuvi voronkasi:** Yangi lead → Konsultatsiya → To'lov kutilmoqda → O'quvchi / Yo'qotildi. Yo'qotish sabablari analitikasi |
| 3 | `core/retention.py` | Kunlik avto-nazorat: esdan chiqqan lead, sovigan lead, uxlab qolgan mijoz → mas'ulga avto-vazifa | **Lead va o'quvchi retention:** javobsiz qolgan lead sotuvchiga eslatiladi; darsga kelmay qo'ygan o'quvchi → dropout-alarm |
| 4 | `core/briefing.py` | Ertalabki direktor brifingi: kecha kassa, oylik foyda, bugungi tadbirlar + AI xulosa — avtomatik Telegram'ga | **Kunlik boshqaruv brifingi:** kecha nechta lead, nechta to'lov, bugungi darslar/efirlar + AI tavsiya |
| 5 | `core/telegram_bot.py` | Rahbar botga oddiy tilda yozadi ("Salohiddin ertaga finplan tayyorlasin") → bot xodimni topib vazifa yaratadi | **Ichki vazifa boshqaruvi:** Mfaktor jamoasi uchun xuddi shu bot — o'zgartirishsiz deyarli |
| 6 | Moliya bot AI Vision | Chek rasmi → Claude JSON'ga o'qiydi (summa/karta/sana) → tranzaksiya | **To'lov tasdiqlash:** o'quvchi to'lov chekini yuboradi → avtomatik o'qilib, CRM'da "to'landi" belgilanadi |
| 7 | `core/kpi_engine.py` | KPI avtomatik hisoblanadi (odam kiritmaydi): leaderboard, bo'lim ko'rsatkichlari, bonus taqsimoti | **Sotuv jamoasi KPI:** lead/konversiya/tushum bo'yicha avtomatik leaderboard va bonus hisobi |
| 8 | `core/sms.py` (Eskiz.uz) | Avtomatik SMS, xato bardoshli (SMS ishlamasa asosiy oqim buzilmaydi) | **Follow-up ketma-ketliklari:** to'lov eslatmasi, dars eslatmasi, yangi oqim e'loni |
| 9 | `core/instagram_sync.py` | Instagram Graph API: post/insights statistikasi + raqobatchi kuzatuvi | **Marketing analitika:** @mfaktor kanallari + raqobatchi maktablar dinamikasi bir dashboardda |
| 10 | `core/reminders.py` | Qarz kechikkan / shartnoma tugayapti / zaxira kam → avto-vazifa, takrorlanmaslik kaliti bilan | **Bo'lib to'lash nazorati:** to'lov kechiksa avtomatik eslatma o'quvchiga + vazifa sotuv bo'limiga |
| 11 | `core/finance_bridge.py` | Sotuv → buxgalteriya ko'prigi: bron kutilayotgan kirim yaratadi, buxgalter 1 tugma bilan tasdiqlaydi | **Kurs to'lovlari oqimi:** sotuv bo'limi va moliya orasida qo'lda ko'chirish yo'qoladi |
| 12 | Auth (6 xonali kod) + rol/bo'lim tizimi | Sodda kirish, granular ruxsatlar, shaxsiy sozlamalar | Mfaktor ichki tizimi uchun tayyor poydevor |

## 3. Arxitektura tavsiyasi

Impulse tajribasidan olingan asosiy saboqlar:

1. **Monolit + modullar** — mikroservis emas: bitta Flask app, `modules/` ichida blueprint'lar. Kichik jamoa uchun eng tez rivojlanadigan yo'l.
2. **HTMX, SPA emas** — frontend murakkabligisiz jonli interfeys. Mfaktor ichki tizimi uchun ham shu yetadi; ommaviy sayt/LMS alohida (Next.js andozasi `erp_web`da bor).
3. **Kommunikatsiya yadrosi** (Event → Notification → Task) — har bir modul voqea yozadi, yadro kerakli odamga yetkazadi. Mfaktor'da ham birinchi bo'lib shu yadro quriladi.
4. **AI xato bardoshligi** — AI/SMS/integratsiya ishlamay qolsa asosiy jarayon buzilmaydi (jim no-op + log). Ishlab turgan biznes uchun majburiy tamoyil.
5. **Toshkent vaqti bilan izchillik** (`core/timeutils.py`) — hisobotlar UTC tufayli noto'g'ri oyga tushib qolmasligi uchun.
6. **ONBOARDING.md amaliyoti** — har loyihada "5 daqiqada tushunish" hujjati; sessiya/dasturchi almashsa ish to'xtamaydi.

## 4. Mfaktor tizimining taklif etilgan tarkibi

```
mfaktor-platform/
├── app.py, config.py, database.py      # Impulse app-factory andozasi
├── models/
│   ├── user.py                          # rol/bo'lim (Impulse'dan)
│   ├── communication.py                 # Event/Notification/Task yadrosi (Impulse'dan)
│   ├── crm.py                           # Lead voronkasi — kurs sotuviga moslanadi
│   ├── student.py                       # YANGI: O'quvchi, Guruh/Oqim, Davomat
│   ├── course.py                        # YANGI: Kurs, Modul, Dars, Vazifa
│   └── payment.py                       # To'lov, bo'lib to'lash grafigi (moliya andozasi)
├── core/
│   ├── ai_assistant.py                  # Impulse'dan — tool'lar Mfaktor DB'ga moslanadi
│   ├── ai_sales_bot.py                  # YANGI: 24/7 lead-konsultant (roadmap 1-bosqich)
│   ├── ai_mentor.py                     # YANGI: kurs materiallari asosida AI-mentor (3-bosqich)
│   ├── retention.py, reminders.py       # Impulse'dan — dropout/to'lov nazoratiga moslanadi
│   ├── briefing.py, kpi_engine.py       # Impulse'dan
│   ├── sms.py, telegram_bot.py          # Impulse'dan
│   └── vision_pay.py                    # Moliya botidan — chek o'qish
└── modules/                             # dashboard, crm, students, courses, finance, kpi...
```

## 5. Nimani Impulse'dan olMAYmiz

- **Zal ijarasi/ombor/tozalash modullari** — Mfaktor biznesiga tegishli emas
- **Moliya ERP'ning murakkab hamyonlar tizimi** — boshida shart emas; to'lovlar CRM ichida yuritiladi, kerak bo'lganda Moliya ERP alohida ulanadi (finance_bridge andozasi bilan)
- **Hikvision/davomat kameralari** — faqat oflayn filialda davomat kerak bo'lsa keyinroq

## 6. Keyingi qadam

`docs/03-ai-strategiya-roadmap.md` dagi 1-bosqich ("Tez g'alabalar") endi aniq texnik poydevorga ega:

1. **AI sotuv-konsultant bot (MVP)** — Moliya botining Telegram skeleti + `ai_assistant.py` agent-loop andozasi asosida, 1–2 haftada MVP
2. **Mini-CRM** — `models/crm.py` voronkasi kurs sotuviga moslanadi (bosqichlar: Yangi → Konsultatsiya → To'lov kutilmoqda → O'quvchi / Yo'qotildi)
3. **Kunlik brifing** — `briefing.py` andozasi: lead soni, to'lovlar, AI xulosa rahbariyat Telegram'iga
4. Ichki audit ma'lumotlari (docs/01-audit.md, 4-bo'lim) kelgach — KPI bazaviy qiymatlari o'rnatiladi
