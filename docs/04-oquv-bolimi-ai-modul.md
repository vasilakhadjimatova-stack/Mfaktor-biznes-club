# O'quv Bo'limi — ERP Moduli va AI Integratsiyasi (Takliflar va Arxitektura)

> Kontekst: Mfaktor ERP'ning moliya qismi deyarli tayyor. Navbat — **o'quv bo'limi**ni
> AI bilan maksimal avtomatlashtirilgan, professional darajaga olib chiqish.
> Ushbu hujjat: nima qurish kerak, qanday ketma-ketlikda, va bozor yetakchilari
> nima qilgani asosida qaysi yechimlar bizga eng katta natija beradi.

---

## 1. Bozor manzarasi: top markazlar nima qilgan

### 1.1. Global yetakchilar (batafsil: docs/02-dunyo-tajribasi.md)

| Loyiha | Asosiy AI yechimi | Bizga saboq |
|---|---|---|
| Khan Academy (Khanmigo) | Sokratik AI-tutor: javob aytmaydi, yo'naltiradi; o'qituvchiga dars-reja/baholash avtomatikasi | AI-mentor spikerning "birinchi qatlam" yordamchisi |
| Coursera | AI-baholash, kurs-builder, avtomatik tarjima/subtitr, adaptiv tavsiyalar | 1 ta yozilgan kursdan ko'p format yasash |
| Duolingo | Har foydalanuvchiga mos mashq (Birdbrain), rol-play suhbatlar, retention avtomatikasi | Sotuv ko'nikmasi = til kabi: mashq simulyatori kerak |
| Section School | AI-professor (ProfAI), kohort kurslar, korporativ obuna | B2B obuna modeli + AI-first pozitsiya |

2026 holatiga kelib bu yechimlar eksperiment emas, **bazaviy standart**ga aylandi:
ta'lim muassasalarining 65%+ qismi adaptiv o'qitish, AI-tutor, avtomatik baholash
yoki dropout-bashorat qo'llaydi. Dropout-bashorat modellari o'quvchi tashlab
ketishini 70–80% aniqlikda haftalar oldin ko'ra oladi va erta aralashuv bilan
dropout'ni 40% gacha kamaytirgan keyslar bor.

### 1.2. Mintaqa va O'zbekiston

| Markaz | Nima qilgan | Holat |
|---|---|---|
| Najot Ta'lim | O'zining LMS platformasi (nws.najottalim.uz): davomat, vazifa, ball tizimi | Kuchli LMS, lekin chuqur AI qatlami ko'rinmaydi |
| PDP Academy | online.pdp.uz — onlayn/oflayn aralash format, PDP Junior LMS | Platforma bor, AI-mentor/simulyator yo'q |
| Skyeng / Yandex Practicum (CIS) | O'z platformasi, avtotekshiruv + mentor modeli, nutq tahlili | Bizga eng yaqin ishlaydigan namuna |
| data365 (UZ) | O'quv markazlarga tayyor CRM/LMS avtomatlashtirish sotadi | Raqobat emas — bozor yetilganining belgisi |

**Xulosa:** O'zbekiston bozorida LMS bor markazlar bor, lekin **AI-mentor +
rol-play simulyator + dropout-bashorat** to'plamini birortasi qilmagan.
Mfaktor birinchi bo'lsa — bu marketingda ham mahsulotda ham kuchli pozitsiya.

---

## 2. Modul arxitekturasi: 2 qatlam

**Tamoyil:** avval mustahkam operatsion baza (AI'siz ham ishlaydigan LMS-yadro),
uning ustiga AI qatlami. AI'ni xom jarayon ustiga qursak — xaosni tezlashtiramiz, xolos.

### 2.1. Qatlam A — Operatsion yadro (LMS-core)

ERP ichida `education` moduli:

1. **Kurs katalogi** — kurs, modul, dars, material (video/PDF/skript), narx paketi
2. **Oqim/guruh (kohorta)** — jadval, xona/onlayn, spiker biriktirish, sig'im
3. **O'quvchi profili** — CRM lead'dan avtomatik konvertatsiya; shartnoma, holat
   (o'qiyapti / akademik ta'til / bitirgan / tashlagan)
4. **To'lov integratsiyasi** — moliya moduli bilan ko'prik: bo'lib to'lash grafigi,
   qarzdorlik → avtomatik eslatma, to'lov holati o'quvchi kartochkasida
5. **Davomat** — qo'lda + Hikvision yuz-tanish integratsiyasi (impulse-erp'da tayyor
   `core/hikvision.py`, `core/att_sync.py` bor — qayta ishlatiladi)
6. **Vazifa va baholash** — uy vazifasi topshirish, ball, reyting
7. **Sertifikat va bitiruv** — avtomatik generatsiya (PDF), QR bilan tekshiriladigan
8. **Alumni registri** — bitiruvchi ishga joylashuvi, upsell tarixi

### 2.2. Qatlam B — AI qatlami (10 yechim, prioritet tartibida)

| # | Yechim | Nima qiladi | Nega muhim |
|---|---|---|---|
| 1 | **AI-mentor** | Kurs materiallari asosida o'qitilgan chatbot (Telegram + web): 24/7 savol-javob, imtihonga tayyorlash | Spiker yuki ↓, o'quvchi mamnunligi ↑; texnik jihatdan eng tez tayyor bo'ladigan yechim |
| 2 | **Sotuv rol-play simulyatori** | AI "qiyin mijoz" rolini o'ynaydi (e'tirozlar, narx talashish, sovuq qabul); o'quvchi yozma/ovozli sotadi; AI rubrika bo'yicha baholab, aniq feedback beradi; guruh reytingi | **Flagman differensiator** — bozorda hech kimda yo'q; Mfaktor mahsuli aynan sotuv bo'lgani uchun ideal mos |
| 3 | **Avtomatik baholash** | Uy vazifalari va sotuv skriptlarini AI rubrika bo'yicha tekshiradi, spiker faqat tasdiqlaydi/istisnolarni ko'radi | Tekshiruv vaqti ~90% ↓, feedback bir kunda emas — bir daqiqada |
| 4 | **Dropout-alarm (risk skoring)** | Davomat + vazifa topshirish + to'lov + AI-mentor faolligi → har o'quvchiga risk ball; xavf oshsa admin/kuratorga signal + avtomatik shaxsiy re-engagement xabari | Har saqlab qolingan o'quvchi = to'g'ridan-to'g'ri daromad; sohada dropout −40% gacha keyslar |
| 5 | **Test-bank generatori** | Dars videosi transkriptidan avtomatik test/kviz; adaptiv qayta-mashq (xato qilgan mavzudan ko'proq savol) | Kontent jamoasisiz to'liq baholash tizimi |
| 6 | **Kontent-konveyer (o'quv)** | Dars yozuvi → transkript → konspekt/darslik → test → marketing uchun short-lavhalar | 1 dars = 10+ material; onlayn kurs poydevori |
| 7 | **Spiker co-pilot** | Guruh bo'yicha haftalik AI hisobot: qaysi mavzu tushunilmagan (test xatolari, AI-mentor savollari tahlili), kimga e'tibor kerak | Spiker darsga "ko'zi ochiq" kiradi |
| 8 | **Admin avtomatika** | Shartnoma/sertifikat generatsiyasi, jadval to'qnashuv nazorati, dars eslatmalari (Telegram), guruh to'ldirilishi signallari | Admin jamoa vaqti −50% |
| 9 | **Feedback-tahlil** | Har dars so'ngida 30-soniyalik mikro-so'rov → AI tematik tahlil (NPS, shikoyat klasterlari) → haftalik xulosalar | Sifat muammosi 1 haftada emas, 1 kunda ko'rinadi |
| 10 | **Direktor dashboardi + AI tahlilchi** | O'quv KPI'lari (to'ldirilish, davomat, NPS, dropout, LTV) + mavjud `ask_ai` ga o'quv tool'lari qo'shiladi: "qaysi guruhda dropout xavfi eng yuqori?" deb so'rash mumkin | Moliya AI-yordamchisi bilan bitta tajriba — direktor bitta chatda hammasini so'raydi |

---

## 3. Texnik yechim (mavjud stack ustida)

Yangi texnologiya kerak emas — impulse-erp'dagi tayyor bloklar qayta ishlatiladi:

| Tayyor blok | O'quv modulida ishlatilishi |
|---|---|
| `core/ai_assistant.py` (Claude API, tool-use loop, prompt caching, suhbat xotirasi) | AI-mentor, rol-play, baholash — hammasi shu pattern'da; system prompt + kurs materiallari caching bilan |
| `core/telegram_bot.py` | O'quvchi interfeysi: AI-mentor, eslatmalar, vazifa topshirish |
| `core/hikvision.py`, `core/att_sync.py`, `modules/attendance` | Davomat → dropout-signal manbasi |
| `modules/crm` + lead pipeline | Lead → o'quvchi konvertatsiyasi |
| Moliya moduli | To'lov grafigi, qarzdorlik ↔ o'quvchi holati |
| `core/kpi_engine.py`, dashboard | O'quv KPI'lari |
| `core/feedback.py`, `core/retention.py` | Feedback-tahlil va re-engagement asosi |

**AI-mentor uchun RAG (soddadan boshlaymiz):** dastlab har kurs materiallari
(transkript + konspekt) bitta katta cache'lanadigan kontekst sifatida beriladi
(prompt caching bilan arzon). Material 200k tokendan oshsa — bosqichma-bosqich
qidiruvli RAG (bo'lim-tanlash tool'i) qo'shiladi. Vektor-baza bilan boshlash shart emas.

**Rol-play simulyatori dizayni:**
- Ssenariylar bazasi: mijoz personasi (sohasi, byudjeti, kayfiyati) + qiyinlik darajasi
- Suhbat rejimi: AI faqat mijoz rolida (system prompt bilan qattiq cheklangan)
- Yakunda ikkinchi AI-chaqiruv "baholovchi" sifatida: rubrika (aloqa o'rnatish,
  ehtiyoj aniqlash, e'tirozga ishlov, yopish) bo'yicha 1–10 ball + aniq maslahatlar
- Ballar reytingga tushadi → gamifikatsiya, guruh ichida musobaqa
- Kelajakda: ovozli rejim (telefon-suhbat simulyatsiyasi)

---

## 4. Bosqichma-bosqich reja

### Sprint 1 (1–2 hafta): LMS-yadro skeleti
- [ ] `models/education.py`: Course, Module, Lesson, Cohort, Enrollment, Attendance, Assignment, Submission, Certificate
- [ ] `modules/education`: kurs/guruh/o'quvchi CRUD, jadval ko'rinishi
- [ ] CRM lead → Enrollment konvertatsiya oqimi
- [ ] Moliya ko'prigi: to'lov grafigi va qarzdorlik o'quvchi kartochkasida

### Sprint 2 (2–3 hafta): birinchi AI g'alabalari
- [ ] AI-mentor MVP (bitta kurs materiallari bilan, Telegram orqali, pilot guruhda)
- [ ] Avtomatik vazifa baholash (rubrika + spiker tasdig'i)
- [ ] Test-bank generatori (transkriptdan)

### Sprint 3 (3–4 hafta): differensiator va retention
- [ ] Rol-play simulyator MVP (yozma rejim, 5 ta ssenariy, baholash rubrikasi, reyting)
- [ ] Dropout-risk skoring + avtomatik re-engagement
- [ ] Davomat integratsiyasi (Hikvision yoki qo'lda) → risk signalga ulash

### Sprint 4 (4–6 hafta): masshtab va boshqaruv
- [ ] Kontent-konveyer oqimi (dars yozuvi → materiallar to'plami)
- [ ] Spiker co-pilot haftalik hisobotlari
- [ ] Direktor dashboardi + `ask_ai` ga o'quv tool'lari
- [ ] Sertifikat avtomatikasi (PDF + QR tekshiruv)

---

## 5. KPI (o'quv moduli)

| Ko'rsatkich | Maqsad (6 oy) |
|---|---|
| Vazifa feedback vaqti | < 5 daqiqa (hozir: kunlar) |
| Kursni tugatish foizi | +15 foiz punkt |
| Spiker/kurator tekshiruv soatlari | −70% |
| O'quvchi savollariga javob (AI-mentor) | 24/7, < 1 daqiqa |
| Har o'quvchi rol-play mashqlari soni | ≥ 10 ta/kurs |
| NPS | o'lchov yo'lga qo'yiladi, keyin +10 |
| Admin qo'l mehnati (hujjat/eslatma) | −50% |

## 6. Tamoyillar (docs/03 dan davom)

1. **Spiker brendi — markazda.** AI baholaydi, lekin "yakuniy so'z" va jonli
   kontakt spikerniki. AI-mentor "spiker nomidan" emas, alohida yordamchi sifatida gapiradi.
2. **O'zbek tili sifati** — har yechim avval o'zbekcha pilot-testdan o'tadi.
3. **Bitta AI tajriba** — moliya, o'quv, sotuv bo'yicha savollar bitta assistentda
   (tool'lar qo'shiladi, alohida botlar ko'paytirilmaydi).
4. **Pilot → o'lchov → masshtab** — har yechim 1 guruhda sinovdan o'tadi, KPI
   yaxshilanmasa 1 oyda to'xtatiladi.
