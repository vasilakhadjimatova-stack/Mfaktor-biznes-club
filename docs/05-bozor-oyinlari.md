# Ayni Damda O'zbekiston Bozorida Nima Qilish Kerak — Konkret "O'yinlar"

> Sana: 2026-yil avgust. Bu hujjat strategiyadan (docs/03) bir qadam chuqurroq:
> hozirgi bozor holatidan kelib chiqib, **ayni shu oylarda** boshlanadigan aniq
> harakatlar. Har bir "o'yin" uchun: nega aynan hozir, qanday qilinadi, qanday pul qiladi.

---

## 1. Bozor holati — raqamlar va faktlar

1. **Sotuvchi kadrlar taqchilligi — bizning yonilg'imiz.** HH.uz bo'yicha faqat
   Toshkentda sotuv bo'limi vakansiyalari ~2100+ dona; sotuv menejeri oyligi
   $500–600 dan $2000–3000 gacha. Ya'ni "kurs → aniq ish → aniq oylik" zanjiri
   real va kuchli sotiladi. Marketing/menejmentda esa har o'ringa 3+ nomzod —
   raqobat u yerda, sotuvda emas.
2. **Sotuv kurslari raqobati texnologiyasiz.** Bozorda o'nlab taklif bor
   (Shark Sales School, Space Academy, Alpha "Samarali Sotuv", sotuvkursi.uz,
   agregatorlar kursi24.uz/darslinker) — lekin barchasi "spiker + dars" formatida.
   Hech birida platforma, simulyator, AI yo'q. Raqobat faqat brend va narx ustida.
3. **IT-ta'limda LMS standart, biznes-ta'limda yo'q.** Najot Ta'lim va PDP o'z
   platformalarini qurib bozor me'yorini ko'tardi — lekin faqat IT segmentida.
   Biznes-ta'lim segmentida "Najot darajasidagi tizim" hali hech kimda yo'q.
   **Bo'sh pozitsiya: "texnologik biznes-maktab".**
4. **AI kurslari bumi — lekin faqat dasturchilar uchun.** Najot (SI asoslari,
   prompt-engineering, no-code), IT Step, Sensorika, Mohirdev — hammasi
   IT-mutaxassis tayyorlaydi. Davlat ham AI-ta'lim platformasi ochdi (talab
   signali). **"Direktor/tadbirkor uchun AI" — deyarli bo'sh nicha**, va bu
   auditoriya aynan Mfaktorning mavjud auditoriyasi.
5. **Korporativ o'qitish talabi o'smoqda.** Payme, Beeline, Texnomart, AKFA,
   banklar o'z sotuv jamoalarini tashqi provayderlarda o'qittirmoqda —
   korporativ byudjetlar ochilgan.
6. **Auditoriya AI'ga tayyor.** Talabalar orasida AI foydalanish 57% (2025);
   AI'li mahsulot "qo'rqitmaydi", aksincha sotadi.

---

## 2. Yetti o'yin (prioritet tartibida)

### O'yin 1 — "Ishga tayyor sotuvchi" konveyeri (kurs → ish → B2B daromad)

**Mantiq:** 2100+ ochiq vakansiya bor bozorda eng qimmat mahsulot kurs emas —
**tekshirilgan tayyor kadr**. Bizda esa uni "tekshirish" vositasi paydo bo'lyapti:
rol-play simulyator ballari + AI-baholangan skriptlar + davomat/intizom tarixi.

**Qanday qilinadi (ERP ichida):**
- Bitiruvchi profili = "Sotuvchi pasporti": simulyator reytingi, kuchli/zaif
  tomonlar AI xulosasi, real rol-play yozuvlari (portfolio)
- Ish beruvchilar kabineti: kompaniya kirib, tayyor nomzodlarni ko'radi
- Daromad: ishga joylashtirish haqi (fee) yoki kompaniyalar uchun obuna

**Nega hozir:** buni hech kim qilmagan; "bitiruvchilarimiz shunchaki sertifikat
emas, o'lchangan ko'nikma bilan chiqadi" — marketingda ham o'ldiradigan dalil.

### O'yin 2 — Rol-play simulyatorni ochiq lead-magnitga aylantirish

**Mantiq:** simulyator faqat ichki o'quv quroli emas — **viral marketing quroli**.

**Qanday:** Telegram'da ochiq "Sotuv IQ" bot: har kim 5 daqiqalik rol-play
o'ynaydi (AI qiyin mijoz), yakunda ball + taqsimot ("siz sotuvchilarning top
18%'idasiz") + ulashiladigan kartochka. Natija past bo'lsa — "kursda buni
o'rgatamiz" CTA. Har bir o'yin = kvalifikatsiya qilingan lead CRMda (bot allaqachon
qanday sotishini ko'rsatdi!).

**Nega hozir:** arzon (mavjud `ai_assistant.py` pattern'i), 2–3 haftada tayyor,
va kursni sotishdan oldin bozorga "bizda AI bor" pozitsiyasini e'lon qiladi.

### O'yin 3 — "Tadbirkorlar uchun AI" kursini kechiktirmasdan chiqarish

**Mantiq:** derazasi ochiq nicha — IT-AI kurslar to'lib ketdi, biznes-AI bo'sh.
Mfaktor auditoriyasi (tadbirkorlar, direktorlar, sotuv rahbarlari) ayni shu
mahsulotni kutayapti va bu auditoriyaga kirish kanallari (YouTube, klub,
tadbirlar) allaqachon bizda.

**Kuchli tomon — o'z keysimiz:** "Biz o'z maktabimizni AI-ERP bilan boshqaramiz"
— kursning o'zi ishlab turgan isbot. Moliya moduli, AI-yordamchi, avtomatlashtirish
— dars materiali sifatida ko'rsatiladi. Bozorda hech kim "mana o'zimizniki" deb
ko'rsata olmaydi.

**Format:** 4–6 haftalik kohorta, amaliy ("o'z biznesingizga 3 ta AI jarayon
joriy qilasiz"), premium narx. Keyin korporativ versiyasi (O'yin 4 ga ulanadi).

### O'yin 4 — Korporativ B2B: "Sotuv bo'limingizni AI bilan o'qitamiz" (obuna)

**Mantiq:** kompaniyalar allaqachon sotuvchilarini o'qittiradi — lekin bir
martalik trening sotib oladi. Biz **doimiy obuna** sotamiz: xodimlar oyiga N ta
rol-play mashq qiladi, AI baholaydi, direktor oylik hisobot oladi ("jamoangiz
e'tirozlarga ishlovda 23% o'sdi").

**Qanday:** o'quv modulining multi-tenant versiyasi — har kompaniya o'z
kabinetiga ega. Trening bir marta sotiladi, obuna har oy to'lanadi (MRR).
Mavjud B2B mijozlar bazasidan boshlanadi (Vebinar/Tashrif/Xodim o'qitish
xizmatlarini olganlar).

**Nega hozir:** Section School modeli aynan shu (kohorta → korporativ obuna);
O'zbekistonda bu modelni hali hech kim qurmagan.

### O'yin 5 — Onlayn + regionlar (AI tufayli endi iqtisodiy mantiqli)

**Mantiq:** sifatli biznes-ta'lim Toshkentda qulflangan; regionlarda talab bor,
lekin spikerni Urganchga olib borish qimmat. AI-mentor + yozilgan kontent +
haftalik jonli efir formati bilan onlayn versiya marjinal xarajatsiz masshtablanadi.
Najot/PDP regionlarga filial bilan chiqdi (qimmat yo'l) — biz platforma bilan
chiqamiz (arzon yo'l). Narx Toshkent oflaynidan 2–3x past bo'lsa ham marja yuqori.

### O'yin 6 — Alumni-tarmoq monetizatsiyasi

**Mantiq:** 1500+ bitiruvchi — uxlab yotgan aktiv. ERP'da alumni moduli:
karyera kuzatuvi (qayerda ishlayapti, AI yordamida yangilanadi), klub obunasi,
upsell (ROP kursi, AI kursi), referal dastur ("do'stingni olib kel").
Bitiruvchining karyera o'sishi = bizning eng arzon marketingimiz (ijtimoiy isbot
kontenti avtomatik yig'iladi).

### O'yin 7 — Ma'lumot xandaqi (data moat): o'zbekcha sotuv korpusi

**Mantiq:** har rol-play suhbati, har baholangan skript, har AI-mentor savoli —
**o'zbek tilidagi sotuv muloqoti korpusi**ga tushadi. 1–2 yilda bu to'plam:
(a) simulyatorni raqobatchilar takrorlay olmaydigan darajada realistik qiladi,
(b) "O'zbekistonda sotuv qanday qilinadi" bo'yicha yagona ma'lumot bazasiga
aylanadi (hisobotlar, benchmark — alohida mahsulot). Bugun qilinadigan ish:
boshidanoq har suhbatni strukturali saqlash va o'quvchidan rozilik olish
(shartnomaga band qo'shish).

---

## 3. Nima QILMASLIK kerak (anti-o'yinlar)

1. **Umumiy LMS sotishga urinmaslik** — data365 kabi integratorlar bor, bu
   bizning o'yin emas; bizning mahsulot — kontent + AI + brend birligi.
2. **IT-kurslar bozoriga kirmaslik** — Najot/PDP u yerda 7 yillik ustunlikka ega;
   bizning ustunlik biznes-auditoriyada.
3. **Narx urushiga tushmaslik** — AI-yechimlar narxni tushirish uchun emas,
   qiymatni (va narxni) oshirish uchun ishlatiladi: "oddiy kurs emas — simulyator,
   AI-mentor va ish bilan bog'langan tizim".
4. **Hammasini birdan qurmaslik** — har o'yin pilotdan o'tadi (docs/04 tamoyillari).

## 4. 90 kunlik ketma-ketlik

| Muddat | Nima | Bog'liq o'yin |
|---|---|---|
| 1–30 kun | O'quv moduli yadrosi (Sprint 1) + ochiq "Sotuv IQ" bot MVP | O'yin 2 |
| 31–60 kun | AI-mentor pilot guruhda + "Tadbirkorlar uchun AI" kursi dasturi va pre-sale (mavjud auditoriyaga) | O'yin 3 |
| 61–90 kun | Rol-play simulyator to'liq versiya ichki kursda + birinchi 2–3 korporativ pilot (mavjud B2B mijozlardan) + "Sotuvchi pasporti" dizayni | O'yin 1, 4 |

Har bosqichda ma'lumot yig'ish standarti yo'lga qo'yiladi (O'yin 7 — moat).

## 5. Daromad modellari xaritasi

| Manba | Model | Muddat |
|---|---|---|
| Asosiy kurslar (sotuv/ROP) | B2C, AI bilan qiymat va narx ↑ | hozir bor |
| "Tadbirkorlar uchun AI" | B2C premium kohorta | 60 kun |
| Korporativ AI-trening | B2B obuna (MRR) | 90 kun |
| Ishga joylashtirish | B2B fee / ish beruvchi obunasi | 4–6 oy |
| Onlayn/region versiya | B2C past narx × katta hajm | 6 oy+ |
| Alumni klub + upsell | Obuna + takroriy sotuv | 6 oy+ |
| Ma'lumot/benchmark mahsulotlari | B2B hisobotlar | 12 oy+ |
