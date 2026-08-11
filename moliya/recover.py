"""Shartnomalarni to'lov tarixidan tiklash.

Nima uchun kerak
════════════════
Shartnomalar reyestri hech qayerda yo'q edi — na dasturda, na jadvalda.
Lekin ДДС dagi mijoz to'lovlarining izohida o'quvchi ismi yozilgan:

    «Поступление от клиента РОП»   izoh: «Suyunova Barno»

Ya'ni shartnomalar ro'yxatini noldan yozish shart emas — to'lovlardan
tiklash mumkin. Bir o'quvchi bo'lib to'lagan bo'lsa, uning to'lovlari
bitta shartnomaga yig'iladi.

Qamrov haqida ochiq gap
═══════════════════════
To'lovlarning taxminan yarmida ism yo'q («prixod klient», «click»,
«smk depozit»). Ular tiklanmaydi — qo'lda kiritiladi yoki «To'lovlar
navbati» sahifasida mavjud shartnomaga bog'lanadi. Tizim ism o'rniga
taxmin qilmaydi.

Shartnoma narxi haqida
══════════════════════
To'lov tarixi qancha TO'LANGANINI biladi, lekin shartnoma NARXINI
bilmaydi. Shuning uchun narx maydoniga to'langan summa qo'yiladi
(«to'liq to'lagan» deb faraz qilinadi) va buxgalter uni tahrirlaydi.
Narx to'langandan katta qilinsa — farqi avtomatik qarzdorlikka tushadi.
"""
from collections import defaultdict

import matching
from database import db
from models import Cohort, Contract, DdsRow, InstallmentLine, Student

# Bir xil odamning ismi turlicha yozilgan bo'lishi mumkin
# («Ernazarov Egambergan» / «Ernazorav Egambergan») — shu chegaradan
# yuqori o'xshashlik bitta odam deb qaraladi.
SAME_PERSON = 0.88

MARK = "[to'lovlardan tiklandi]"

# ДДС maqolasidagi kurs belgisi → qidiriladigan kalit so'zlar
COURSE_KEYS = {
    "РОП": ("роп", "rop", "rahbar"),
    "СМК": ("смк", "smk", "sotuv"),
    "ТББ": ("тбб", "tbb", "твв", "tvv"),
    "TBB": ("тбб", "tbb", "твв", "tvv"),
}


def _course_tag(article):
    """«Поступление от клиента РОП» → «РОП»."""
    return (article or "").split()[-1].strip()


def candidates(include_done=False):
    """To'lovlardan tiklanadigan shartnomalar ro'yxati.

    Har element:
      name   — ekranda ko'rsatiladigan ism (eng ko'p uchragan yozilishi)
      tag    — kurs belgisi (РОП / СМК / ТББ)
      rows   — shu odamning to'lovlari
      paid   — jami to'langan
      first / last — birinchi va oxirgi to'lov sanasi
      seen   — ism nechta xil ko'rinishda yozilgan (xato belgisi)
    """
    q = DdsRow.query.filter(DdsRow.article.like("Поступление от клиента%"))
    if not include_done:
        q = q.filter(DdsRow.contract_id.is_(None))

    # Kurs bo'yicha ajratamiz: bir xil ism ikki kursda bo'lsa — ikki shartnoma
    per_course = defaultdict(list)
    for r in q.order_by(DdsRow.ddate).all():
        if matching.looks_like_name(r.purpose):
            per_course[_course_tag(r.article)].append(r)

    out = []
    for tag, rows in per_course.items():
        buckets = []                      # [(norm_kalit, [qatorlar])]
        for r in rows:
            hit = None
            for b in buckets:
                if matching.similarity(b["key"], r.purpose) >= SAME_PERSON:
                    hit = b
                    break
            if hit is None:
                buckets.append({"key": r.purpose, "rows": [r]})
            else:
                hit["rows"].append(r)

        for b in buckets:
            rs = b["rows"]
            forms = [(x.purpose or "").strip() for x in rs]
            uniq = set(forms)
            # Eng ko'p uchragan yozilish olinadi; teng bo'lsa — qisqasi.
            # (Uzunini olish xato edi: bitta qatorda ko'p ism sanalgan
            # bo'lsa, o'sha uzun qator butun guruhga nom bo'lib qolardi.)
            best = min(uniq, key=lambda f: (-forms.count(f), len(f)))
            out.append({
                "name": best,
                "tag": tag,
                "rows": rs,
                "ids": [x.id for x in rs],
                "paid": sum(x.amount or 0 for x in rs),
                "first": min(x.ddate for x in rs),
                "last": max(x.ddate for x in rs),
                "seen": len(uniq),
                "exists": _existing(b["key"]),
            })
    out.sort(key=lambda x: (-x["paid"], x["name"]))
    return out


def _existing(name):
    """Shu ismli shartnoma allaqachon bormi (takror yaratmaslik uchun)."""
    target = matching.norm_name(name)
    for c in Contract.query.all():
        if c.student and matching.norm_name(c.student.name) == target:
            return c
    return None


def cohorts_for(tag):
    """Shu kurs belgisiga mos oqimlar."""
    keys = COURSE_KEYS.get(tag.upper(), ())
    out = []
    for ch in Cohort.query.order_by(Cohort.start_date.desc()).all():
        cname = (ch.course.name if ch.course else "").lower()
        if not keys or any(k in cname for k in keys):
            out.append(ch)
    return out


def skipped():
    """Ism topilmagan mijoz to'lovlari — nechta va qancha summa."""
    rows = [r for r in DdsRow.query.filter(
        DdsRow.article.like("Поступление от клиента%"),
        DdsRow.contract_id.is_(None)).all()
        if not matching.looks_like_name(r.purpose)]
    return {"n": len(rows), "sum": sum(r.amount or 0 for r in rows)}


def create(row_ids, cohort_id, name, price=None, discount=0.0, source=""):
    """Nomzoddan haqiqiy shartnoma yasaydi va to'lovlarini bog'laydi.

    Qaytaradi: (Contract, xato_matni)
    """
    rows = DdsRow.query.filter(DdsRow.id.in_(row_ids or [])).all()
    if not rows:
        return None, "To'lov qatorlari topilmadi"
    cohort = db.session.get(Cohort, cohort_id or 0)
    if cohort is None:
        return None, "Oqim tanlanmagan"
    name = (name or "").strip()
    if not name:
        return None, "Ism bo'sh"

    paid = sum(r.amount or 0 for r in rows)
    price = paid if price is None else float(price)
    student, made = matching.find_or_create_student(name, source=source)
    if made:
        # Belgi qo'yamiz: bekor qilinganda aynan shu o'quvchilar olib
        # tashlanadi. Belgisiz bo'lsa — u qo'lda kiritilgan, tegilmaydi.
        student.note = f"{(student.note or '').strip()} {MARK}".strip()

    c = Contract(student_id=student.id, cohort_id=cohort.id,
                 price=price, discount=float(discount or 0),
                 signed_date=min(r.ddate for r in rows),
                 status="active", note=MARK)
    db.session.add(c)
    db.session.flush()

    # Grafik: narx noma'lum bo'lgani uchun bitta qator qo'yamiz. Narx
    # to'langandan katta bo'lsa, farqi shu qatorda qarz bo'lib qoladi.
    db.session.add(InstallmentLine(contract_id=c.id,
                                   due_date=c.signed_date,
                                   amount=c.net_price, paid=0.0))
    db.session.flush()

    for r in sorted(rows, key=lambda x: x.ddate):
        matching.apply(r, c, status="manual", score=1.0)
    db.session.commit()
    return c, ""


def undo_all():
    """Tiklangan shartnomalarni butunlay olib tashlaydi.

    To'lovlar avval yechiladi — aks holda ular egasiz qolardi.
    """
    made = Contract.query.filter(Contract.note.like(f"%{MARK}%")).all()
    n = len(made)
    sids = {c.student_id for c in made}
    for c in made:
        for r in DdsRow.query.filter_by(contract_id=c.id).all():
            matching.unapply(r)
        db.session.delete(c)
    db.session.flush()
    # Shu jarayonda yaratilgan o'quvchilar egasiz qolmasin. Boshqa
    # shartnomasi bo'lsa — tegilmaydi.
    for sid in sids:
        s = db.session.get(Student, sid)
        if (s and MARK in (s.note or "")
                and not Contract.query.filter_by(student_id=s.id).count()):
            db.session.delete(s)
    db.session.commit()
    return n
