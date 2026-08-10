# Mfaktor Moliya — ta'lim biznesi uchun moliya dasturi

Impulse Moliya andozasi asosida, jahon ta'lim-moliya standartlari bilan boyitilgan tizim.

## Nima qila oladi

**Kassa qatlami (pul harakati / DDS)** — Impulse andozasi:
- Hamyonlar (kassa, bank, Payme, Click) va qoldiqlar
- Kirim/chiqim/transfer, statya va kontragent kesimida
- Oylik DDS hisoboti

**Hisoblash qatlami (accrual) — ta'lim standarti:**
- O'quv shartnomasi + avtomatik bo'lib to'lash grafigi (1–6 qism)
- To'lov FIFO bo'yicha grafik qatorlariga taqsimlanadi
- **Revenue recognition (IFRS 15 tamoyili):** daromad kurs davomiga chiziqli taqsimlanadi — "olingan pul" ≠ "topilgan pul"
- Deferred revenue (majburiyat) va debitorka alohida ko'rinadi
- Pul qaytarish (1 haftalik kafolat) hisobi

**Unit-ekonomika (EdTech standarti):**
- CAC — umumiy va marketing kanali kesimida
- LTV, LTV/CAC (sog'lom nisbat ≥ 3), ARPU/o'rtacha chek
- Oqim (kohorta) kesimida: to'ldirilish %, tushum, to'g'ridan-to'g'ri xarajat, marja
- BEP — zararsizlik: oyiga nechta o'quvchi kerak

**Nazorat:**
- Qarzdorlik aging (1–7 / 8–30 / 30+ kun)
- Yaqin 14 kunda kutilayotgan to'lovlar
- Byudjet plan-fakt, takrorlanuvchi to'lovlar

## Ishga tushirish

```bash
pip install -r requirements.txt
python seed.py     # birinchi marta — demo ma'lumot
python app.py      # http://localhost:5060
```

Bulutga (Railway): `DATABASE_URL` (PostgreSQL) va `SECRET_KEY` env o'rnatiladi, `Procfile` tayyor.

## Texnologiya

Python + Flask + SQLAlchemy, Jinja2, SQLite→PostgreSQL — Impulse ERP bilan bir xil stack, keyinchalik birlashtirish oson.

## Keyingi bosqichlar (roadmap bilan bog'liq)

1. Telegram bot: kirim-chiqim kiritish + chek rasmini AI bilan o'qish (Impulse Moliya botidan andoza)
2. Qarzdorlarga avtomatik SMS/Telegram eslatma (Impulse `sms.py` + `reminders.py`)
3. AI-tahlilchi: "Bu oy CAC nega oshdi?" — Claude tool-use bilan (Impulse `ai_assistant.py`)
4. Payme/Click webhook — to'lovlar avtomatik tushadi
