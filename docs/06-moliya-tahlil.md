# Mfaktor Moliya — Real Ma'lumotlar Tahlili (2026, 7 oy)

> Manba: Mbm_2026.xlsx (1415 tranzaksiya, 03.01–27.07.2026) + byudjet varaqlari.
> Barcha raqamlar tizimga import qilingan va tekshirilgan (kirim 7/7 oy jamlama bilan aynan mos).

## 1. Qaytarishlar tahlili (131,6 mln — kirimning 5%)

27 ta qaytarish yozuvi. Asosiy topilma: **~95 mln (72%) atigi 7 ta yirik yozuvdan** (10–20 mln lik) — bular oddiy o'quvchi emas, korporativ/guruh qaytarishlariga o'xshaydi. Eng og'ir oylar: fevral (50,0 mln!) va may (34,7 mln).

**Muammo:** izohlarda faqat "vozvrat klient" — qaysi kurs, qaysi sabab noma'lum. **Tavsiya:** bugundan boshlab har qaytarishda yo'nalish + sabab yozilsin (tizimda shartnoma sahifasidagi refund funksiyasi buni avtomatik qiladi).

## 2. Real CAC va jalb qilish dinamikasi

To'lov izohlaridagi unikal to'lovchilar bo'yicha (taxminiy metod):

| Oy | Yangi to'lovchi | Таргет xarajati | CAC |
|---|---|---|---|
| Yanvar | 62 | 66,9 mln | 1,08 mln |
| Fevral | 46 | 26,9 mln | 0,58 mln |
| Mart | 24 | 43,9 mln | 1,83 mln |
| Aprel | 25 | 44,4 mln | 1,77 mln |
| May | 7 | 65,2 mln | **9,31 mln** |
| Iyun | 10 | 48,2 mln | **4,82 mln** |
| Iyul | 4 | 44,0 mln | **10,99 mln** |

- 7 oyda: 178 unikal to'lovchi (РОП 90, СМК 69, ТББ 34), o'rtacha CAC **1,91 mln**, o'rtacha to'lovchi tushumi **13,5 mln** → **LTV/CAC = 7,1** (juda sog'lom)
- **QIZIL SIGNAL:** may–iyulda reklama xarajati o'zgarmagan (44–65 mln/oy), yangi to'lovchilar 62 → 4 taga qulagan. CAC 10 barobar oshgan. Sabab aniqlanishi shart: mavsumiymi, kreativ eskirganmi, oqim ochilmaganmi?
- Eslatma: to'lovchi = izohdagi ism; korporativ to'lovlar va yozuv xatolari aniqlikni pasaytiradi. CRM ulangs, bu raqam aniq bo'ladi.

## 3. Byudjet plan-fakt (byudjed varaqlari importi)

- Plan bajarilishi past: mart fakti reja'ning 2–68% i oralig'ida (Таргет 68%, Премия 59%, Зарплата РОП 42%, Kommunal 0%)
- Aprel: **Dividendlar plandan 195%** (39,0 vs 20,0 mln), **soliq 256%** (16,6 vs 6,5 mln) — rejadan tashqari chiqishlar
- **Ma'lumot xatosi:** "byudjed may" varag'idagi barcha sanalar mart oyiga tegishli — may plani aslida kiritilmagan
- Bir xil rejalar bir necha varaqda takrorlanadi (aprel varag'ida mart qatorlari) — endi importer buni avtomatik filtrlaydi

## 4. Kurs iqtisodiyoti (себестоимость varag'idan)

| Kurs | Narx | Plandagi o'quvchi |
|---|---|---|
| СМК (oflayn) | 3,45 mln | — |
| СМК Online | 3,0 mln | — |
| РОП | 12,0 mln | 40 |
| ТББ | 15,0 mln | 15 |

O'zgaruvchan xarajat modeli (rejada): o'qituvchi gonorari 15% (yoki 8 dars × fiks), sotuv KPI 3%+3%, marketing KPI 2%+3% — jami tushumning ~26% i o'zgaruvchan.

Fakt bilan solishtirish: РОП yo'nalishi 7 oyda 1 575,7 mln tushum (59%) — asosiy lokomotiv. ТББ va СМК birga 834 mln.

## 5. Doimiy xarajatlar (TB 2026 → tizimga yuklandi)

Oylik doimiy: **153,5 mln** (ish haqi fiksa 78,4; dividend fiksa 20; soliq 15; svet 10; obed 10; internet 5,9; CRM 5,5; bank 4; buxgalteriya arenda 2,8; boshqa 2). Ularning o'z zararsizlik modeli: oylik tushum maqsadi 600 mln (kunlik 25 mln).

Fakt: o'rtacha oylik operatsion kirim 384,7 mln — **maqsadning 64% i**.

## 6. Umumiy xulosa va navbatdagi harakatlar

1. **May–iyul jalb qilish inqirozi** — eng ustuvor masala: reklama samarasi 10x pasaygan
2. **Dividend intizomi** — operatsion foyda +225 mln, dividendlar −238 mln: kassa yildan buyon −12 mln
3. **Qaytarishlar sababi** — 131,6 mln ning tahlili uchun sabab-kodlari joriy qilinsin
4. **Perevod juftligi** — 110,5 mln farq; hamyon kesimida aniqlik uchun har perevod ikki tomonlama yozilsin
5. **May byudjeti** — Sheets'da tuzatilishi kerak (sanalar mart bo'lib kiritilgan)
6. Tizim tayyor: endi kunlik yuritishni Sheets o'rniga shu yerda (yoki parallel) olib borish mumkin — keyingi bosqichda Telegram bot + AI chek o'qish ulanadi
