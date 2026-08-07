# Mfaktor Moliya — Internetga joylash (Railway)

5–7 daqiqalik jarayon. Natija: `https://mfaktor-moliya.up.railway.app` kabi doimiy URL, HTTPS bilan (PWA o'rnatish ham ishlaydi).

## 1. Railway hisobi

[railway.app](https://railway.app) → **Login with GitHub** (repoga ulanish uchun GitHub hisobingiz bilan kiring — `vasilakhadjimatova-stack`).

## 2. Loyiha yaratish

1. **New Project** → **Deploy from GitHub repo**
2. `vasilakhadjimatova-stack/Mfaktor-biznes-club` repoyisini tanlang
   (birinchi marta: "Configure GitHub App" orqali repoga ruxsat berasiz)
3. **Settings** bo'limida:
   - **Branch:** `claude/mfaktor-ai-automation-y3l0uk` (yoki main'ga merge qilingandan keyin `main`)
   - **Root Directory:** `moliya` ← MUHIM (dastur shu papkada)

## 3. Ma'lumotlar bazasi

Loyiha ichida: **+ New** → **Database** → **PostgreSQL**.
Railway `DATABASE_URL` o'zgaruvchisini avtomatik ulaydi — dastur uni o'zi taniydi.

## 4. Muhit o'zgaruvchilari

Servis → **Variables**:

| Nomi | Qiymati |
|---|---|
| `SECRET_KEY` | istalgan uzun tasodifiy satr (masalan 40 belgili) |
| `APP_PIN` | 6 xonali kirish kodi, masalan `582917` — jamoa shu kod bilan kiradi |

`APP_PIN` o'rnatilgach butun dastur qulflanadi: har kim avval chiroyli
PIN sahifasida kodni teradi (5 marta xato — 1 daqiqa blok), sessiya
30 kun eslab qolinadi, chap panelda «Chiqish» tugmasi bor.
Kodni almashtirish: Variables'da qiymatni o'zgartiring — Railway o'zi
qayta deploy qiladi, eski sessiyalar ham bekor bo'lishini istasangiz
`SECRET_KEY`ni ham yangilang.

## 5. Domen

Servis → **Settings** → **Networking** → **Generate Domain**.
Taklif: `mfaktor-moliya` → URL: `https://mfaktor-moliya.up.railway.app`

## 6. Real ma'lumotlarni yuklash

Deploy ko'tarilgach, bir martalik import (lokal kompyuterdan):

```bash
git clone https://github.com/vasilakhadjimatova-stack/Mfaktor-biznes-club.git
cd Mfaktor-biznes-club/moliya
pip install -r requirements.txt
# Railway'dagi PostgreSQL'ga ulanib import qilamiz:
# (DATABASE_URL ni Railway -> Postgres -> Connect bo'limidan oling)
set DATABASE_URL=postgresql://...     # Windows (PowerShell: $env:DATABASE_URL="...")
python import_ddsdata.py Mbm_2026.xlsx   # «ДДС данные» 1:1 (1415 qator)
python import_dds.py Mbm_2026.xlsx       # hamyon boshlang'ich qoldiqlari
python import_extra.py Mbm_2026.xlsx     # kurslar/oqimlar (bo'lsa)
```

So'ng saytda (yoki xuddi shu terminalda) bir marta qayta qurishni
ishga tushiring — ДДС qatorlari kassaga bog'lanadi va to'lovlar
shartnomalarga taqqoslanadi:

```bash
python -c "from app import create_app; import ddsflow, matching
app = create_app()
with app.app_context():
    print(ddsflow.rebuild_all()); print(matching.run_all())"
```

Shu bilan sayt real 2026 ma'lumotlari bilan ishlaydi.

## Yangilanishlar

Har `git push` (tanlangan branchga) Railway'da avtomatik qayta deploy qiladi.

## Eslatmalar

- Kirish himoyasi tayyor: `APP_PIN` o'rnatilsa 6 xonali kod so'raladi
  (yuqoridagi 4-bo'lim). Kodsiz deploy qilmang — moliyaviy ma'lumot
  ochiq internetga chiqib qoladi.
- Narx: Railway'ning Hobby rejasi ($5/oy) bu hajmdagi dastur uchun yetarli.
- Tekshirish: deploy'dan keyin `https://.../healthz` → `{"ok": true}`
  qaytarsa servis tirik.
