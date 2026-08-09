# Mfaktor Biznes Club — AI Integratsiya Loyihasi

Ushbu repozitoriy **Mfaktor biznes maktabi**ga sun'iy intellekt (AI) texnologiyalarini har bir ish jarayoniga bosqichma-bosqich joriy qilish loyihasining markaziy bazasi hisoblanadi.

## Loyiha maqsadi

Mfaktor o'quv-ta'lim loyihasining barcha jarayonlariga — marketing, sotuv, o'qitish, operatsiya va tahlil — AI yechimlarini qo'shgan holda:

1. Ishlarni maksimal darajada **avtomatlashtirish**
2. Xarajatlarni kamaytirib, **foydani oshirish**
3. O'quvchilar tajribasini dunyo standartlari darajasiga olib chiqish
4. Dunyodagi top ta'lim loyihalari tajribasidan ilhomlanib, **o'zimizning muhitga moslashtirish**

## Hujjatlar tarkibi

| Hujjat | Tavsif |
|---|---|
| [docs/01-audit.md](docs/01-audit.md) | Mfaktor biznes maktabining hozirgi holati bo'yicha to'liq audit |
| [docs/02-dunyo-tajribasi.md](docs/02-dunyo-tajribasi.md) | Dunyodagi yetakchi ta'lim loyihalarining AI tajribalari (benchmark) |
| [docs/03-ai-strategiya-roadmap.md](docs/03-ai-strategiya-roadmap.md) | AI integratsiya strategiyasi va bosqichma-bosqich yo'l xaritasi |
| [docs/04-oquv-bolimi-ai-modul.md](docs/04-oquv-bolimi-ai-modul.md) | O'quv bo'limi ERP moduli: arxitektura, AI yechimlari va sprint rejasi |
| [docs/05-bozor-oyinlari.md](docs/05-bozor-oyinlari.md) | O'zbekiston bozori tahlili va ayni damda qilinadigan konkret "o'yinlar" (90 kunlik reja) |

## Mfaktor ERP (erp/)

Mfaktor biznes maktabining o'z ERP dasturi — `erp/` papkasida (Flask + SQLAlchemy).
1-bosqich: **O'quv bo'limi** — kurslar, guruhlar, davomat, uy vazifalari,
AI baholash, dropout risk-nazorat, QR-tekshiruvli sertifikatlar.

```bash
cd erp
pip install -r requirements.txt
python seed.py     # birinchi marta: admin + namunaviy kurslar
python app.py      # → http://localhost:5070
```

Kirish kodlari (seed): `100001` — Direktor (admin), `200001` — O'quv bo'limi rahbari.
AI baholash uchun `ANTHROPIC_API_KEY` muhit o'zgaruvchisi sozlanadi (ixtiyoriy —
sozlanmasa modul to'liq qo'lda rejimda ishlaydi).

## Ish tartibi

Har bir yo'nalish bo'yicha ish shu repozitoriyda alohida papka/hujjat sifatida yuritiladi, qarorlar va natijalar hujjatlashtiriladi.
