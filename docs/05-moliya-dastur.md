# Mfaktor Moliya Dasturi — Loyihalash Hujjati

> Kod: [`moliya/`](../moliya/) papkasida. Ishga tushirish: `pip install -r requirements.txt && python seed.py && python app.py` → http://localhost:5060

## G'oya

Impulse Moliya'dan ilhomlangan, lekin **ta'lim biznesining o'ziga xosligiga** qurilgan tizim. Oddiy kirim-chiqim daftari emas — ikki qatlamli moliya:

| Qatlam | Savolga javob beradi | Standart |
|---|---|---|
| **Kassa (DDS)** | "Pulimiz qayerda, qancha?" | Impulse Moliya andozasi: hamyonlar, statyalar, transferlar |
| **Hisoblash (accrual)** | "Aslida qancha topdik?" | IFRS 15 ruhida revenue recognition — daromad kurs davomiga taqsimlanadi |

Ta'lim biznesida bu farq hal qiluvchi: sentyabrda 100 mln to'lov yig'ib olish — hali 100 mln "topish" emas. Kurs tugamaguncha bir qismi **majburiyat (deferred revenue)**. Ko'p o'quv markazlari shu farqni ko'rmagani uchun "pul bor edi, birdan yo'q bo'lib qoldi" holatiga tushadi.

## Jahon standartlaridan olinganlar

1. **Revenue recognition (IFRS 15)** — shartnoma daromadi kurs davriga chiziqli tan olinadi; dashboard "olingan pul" va "topilgan pul"ni alohida ko'rsatadi
2. **Unit-ekonomika (EdTech standarti):** CAC (umumiy + kanal kesimida), LTV, LTV/CAC ≥ 3 mezoni, o'rtacha chek
3. **Kohorta hisobi** — har oqim alohida biznes-birlik: to'ldirilish (fill rate), tushum, to'g'ridan-to'g'ri xarajat (spiker + kontent), marja %
4. **BEP (zararsizlik)** — doimiy xarajat ÷ bir o'quvchi hissasi = oyiga kerakli o'quvchilar soni
5. **Qarzdorlik aging** — 1–7 / 8–30 / 30+ kun bo'yicha guruhlash (kredit nazorati standarti)
6. **Byudjet plan-fakt** — statya kesimida reja/fakt/farq
7. **Refund hisobi** — 1 haftalik pul qaytarish kafolati moliyada to'g'ri aks etadi

## Impulse'dan olingan andozalar

- Hamyon + Transaction + ochilish qoldig'i modeli (Impulse Moliya `models.py`)
- Statya lug'atlari yondashuvi (erkin matn emas — toza analitika)
- Takrorlanuvchi to'lovlar (ijara, oyliklar) → BEP'da doimiy xarajat sifatida
- Flask + SQLAlchemy + Jinja2 + SQLite→PostgreSQL stack, Railway deploy (Procfile)
- Premium dark interfeys uslubi

## Ta'limga xos yangi qismlar (Impulse'da yo'q edi)

- **Kurs → Oqim → Shartnoma → To'lov grafigi** zanjiri
- Shartnoma yaratilganda bo'lib to'lash grafigi avtomatik (1–6 qism, 30 kunlik interval)
- To'lov FIFO bo'yicha grafikning eng eski qatoriga taqsimlanadi
- O'quvchi manbasi (kanal) → CAC kanal kesimida hisoblanadi
- Tan olingan daromad har shartnoma sahifasida jonli ko'rinadi

## Keyingi bosqichlar

| # | Qadam | Andoza |
|---|---|---|
| 1 | Telegram bot: kirim-chiqim + chek rasmini AI o'qishi | Impulse Moliya `bot.py` (Claude Vision) |
| 2 | Qarzdorlarga avtomatik SMS/Telegram eslatma | Impulse `sms.py` + `reminders.py` |
| 3 | AI-tahlilchi ("Bu oy CAC nega oshdi?") | Impulse `ai_assistant.py` (tool-use) |
| 4 | Payme/Click webhook — to'lov avtomatik tushadi | yangi |
| 5 | Ertalabki moliya brifingi rahbariyatga | Impulse `briefing.py` |

## Real ma'lumotga o'tish

Demo (`seed.py`) o'rniga real ish boshlash uchun jamoadan kerak:
1. Hamyonlar ro'yxati va joriy qoldiqlar (sana bilan)
2. Faol oqimlar: nomi, davri, narxi, o'quvchilar ro'yxati va to'lov holati
3. Oylik doimiy xarajatlar (ijara, oyliklar, servislar)
4. Marketing byudjeti kanal kesimida (oxirgi 2–3 oy — CAC bazasi uchun)

---

## Real ma'lumot importi (2026-yil avgust holati)

`Mbm_2026.xlsx` (ДДС данные varag'i) dan **1415 ta real tranzaksiya** import qilindi (03.01–27.07.2026). Validatsiya: operatsion kirim 7/7 oy, operatsion chiqim 6/7 oy jamlama jadval bilan **aynan mos** (farq 0 so'm).

### Audit topilmalari

1. **Jamlama jadvalda xato:** 09.05.2026, «зарплата РОП» (spiker gonorar), 11 059 000 so'm — «ДДС данные»da bor, lekin jamlama ДДС_2026 uni may oyiga qo'shmagan. Sheets'dagi may chiqimi 11 mln kam ko'rsatilgan.
2. **Juftlanmagan perevodlar:** hamyonlar orasi o'tkazmalarda chiqim 1 358,2 mln, kirim 1 247,7 mln — 110,5 mln farq (129 ta chiqim vs 117 ta kirim yozuvi). Shu sababli hamyonlar kesimidagi qoldiqlar tranzaksiya ma'lumotidan aniq chiqmaydi; jamlamadagi qoldiq qatorlari qo'lda yuritilgan ko'rinadi.
3. **Dividendlar operatsion foydadan katta:** 7 oyda operatsion sof oqim +225,4 mln, dividendlar −237,6 mln → umumiy sof oqim −12,2 mln. Kassa yil boshidagi 145,2 mln dan 133,0 mln ga tushgan.
4. **Qaytarishlar (возврат клиенту) 131,6 mln** — kirimning ~5% i. Sabablar tahlili (qaysi kurs, qaysi bosqichda) alohida o'rganishga arziydi.

### 7 oylik asosiy raqamlar (import qilingan real ma'lumot)

| Ko'rsatkich | Summa | Ulush |
|---|---|---|
| Operatsion kirim | 2 693,0 mln | 100% |
| — РОП mijozlari | 1 575,7 mln | 59% |
| — СМК mijozlari | 421,7 mln | 16% |
| — ТББ mijozlari | 412,6 mln | 15% |
| — Мфактор tushumlari | 244,1 mln | 9% |
| Operatsion chiqim | 2 467,7 mln | 92% |
| — Зарплата МБМ | 568,5 mln | 21% |
| — Премия | 356,4 mln | 13% |
| — Таргет (reklama) | 339,3 mln | 13% |
| — Возврат клиенту | 131,6 mln | 5% |
| — Кофе-брейк | 133,6 mln | 5% |
| Operatsion sof oqim | +225,4 mln | 8,4% marja |
| Dividendlar | −237,6 mln | |
| **Umumiy sof oqim** | **−12,2 mln** | |
