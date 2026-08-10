"""Namunaviy (vaqtinchalik) shartnomalar — sahifani bo'sh ko'rmaslik uchun.

Nima uchun kerak: haqiqiy shartnomalar hali dasturga kiritilmagan, Google
Sheets'da ham ularning reyestri yo'q edi (u yerda faqat ДДС to'lovlari bor).
Shartnoma, oqim va qarzdorlik sahifalari qanday ishlashini ko'rish uchun
vaqtincha namunaviy ma'lumot qo'yiladi.

Muhim qoidalar — namunaviy ma'lumot haqiqiy pulga TEGMAYDI:
  • kassa yozuvi (Transaction) yaratilmaydi — hamyon qoldiqlari o'zgarmaydi;
  • ДДС qatorlariga tegilmaydi;
  • avtomatik moslash bu shartnomalarni ko'rmaydi (matching ularni chetlab
    o'tadi), ya'ni haqiqiy to'lov namunaviy o'quvchiga bog'lanib qolmaydi.

Hammasi «[namuna]» belgisi bilan yuritiladi va bitta tugma bilan izsiz
o'chiriladi.
"""
from datetime import date, timedelta
import random

from database import db
from models import Cohort, Contract, Course, InstallmentLine, Student

MARK = "[namuna]"

# Ataylab uydirma ismlar: haqiqiy to'lov izohlaridagi ismlar bilan
# to'qnashmasligi uchun (aks holda moslash chalkashib ketardi).
NAMES = [
    "Namuna Aliyev", "Namuna Karimova", "Namuna Toshev", "Namuna Yusupova",
    "Namuna Rahimov", "Namuna Ergasheva", "Namuna Sobirov", "Namuna Nazarova",
    "Namuna Qodirov", "Namuna Islomova", "Namuna Sattorov", "Namuna Mirzayeva",
    "Namuna Ismoilov", "Namuna Abdullayeva", "Namuna Xolmatov",
]
SOURCES = ["Instagram", "Telegram", "Tavsiya", "YouTube"]


def count_demo():
    """Nechta namunaviy shartnoma va oqim bor."""
    return {
        "contracts": Contract.query.filter(Contract.note.like(f"%{MARK}%")).count(),
        "cohorts": Cohort.query.filter(Cohort.name.like(f"%{MARK}%")).count(),
    }


def clear_demo():
    """Namunaviy ma'lumotni butunlay o'chiradi (haqiqiysiga tegmaydi)."""
    contracts = Contract.query.filter(Contract.note.like(f"%{MARK}%")).all()
    sids = {c.student_id for c in contracts}
    n = len(contracts)
    for c in contracts:
        db.session.delete(c)            # grafik qatorlari cascade bilan ketadi
    db.session.flush()
    for sid in sids:
        s = db.session.get(Student, sid)
        if s and MARK in (s.note or ""):
            db.session.delete(s)
    cohorts = Cohort.query.filter(Cohort.name.like(f"%{MARK}%")).all()
    for ch in cohorts:
        if not Contract.query.filter_by(cohort_id=ch.id).count():
            db.session.delete(ch)
    db.session.commit()
    return {"contracts": n, "cohorts": len(cohorts)}


def seed_demo(seed=7):
    """Ikkita namunaviy oqim va ularning o'quvchilarini yaratadi.

    Avval eskisini tozalaydi — ikki marta bosilsa nusxa ko'paymaydi.
    """
    clear_demo()
    rnd = random.Random(seed)
    today = date.today()

    def pick(*keys):
        for k in keys:
            c = Course.query.filter(Course.name.like(f"%{k}%")).first()
            if c:
                return c
        return Course.query.first()

    plan = [
        (pick("СМК", "SMK"), "СМК-namuna", today - timedelta(days=32),
         today + timedelta(days=28), 30, 3_450_000, 9),
        (pick("РОП", "ROP"), "РОП-namuna", today - timedelta(days=6),
         today + timedelta(days=84), 15, 12_000_000, 6),
    ]
    made = 0
    idx = 0
    for course, cname, start, end, cap, price, n in plan:
        if not course:
            continue
        ch = Cohort(course_id=course.id, name=f"{cname} {MARK}",
                    start_date=start, end_date=end, capacity=cap)
        db.session.add(ch)
        db.session.flush()
        for _ in range(n):
            st = Student(name=NAMES[idx % len(NAMES)],
                         phone=f"+998 90 000 {10 + idx:02d} {20 + idx:02d}",
                         source=rnd.choice(SOURCES), note=MARK)
            idx += 1
            db.session.add(st)
            db.session.flush()
            discount = rnd.choice([0, 0, 0, round(price * 0.1)])
            c = Contract(student_id=st.id, cohort_id=ch.id, price=price,
                         discount=discount, signed_date=start - timedelta(
                             days=rnd.randint(3, 20)),
                         note=MARK)
            db.session.add(c)
            db.session.flush()
            parts = rnd.choice([1, 2, 3])
            per = round((price - discount) / parts)
            for j in range(parts):
                due = c.signed_date + timedelta(days=30 * j)
                mode = rnd.choices(["full", "part", "late"], [.58, .17, .25])[0]
                paid = per if mode == "full" else (
                    round(per * 0.4) if mode == "part" else 0)
                if mode == "late":
                    due = today - timedelta(days=rnd.randint(4, 60))
                # DIQQAT: kassa yozuvi yaratilmaydi — bu faqat grafik ko'rinishi
                db.session.add(InstallmentLine(contract_id=c.id, due_date=due,
                                               amount=per, paid=paid))
            made += 1
    db.session.commit()
    return {"contracts": made, "cohorts": len([p for p in plan if p[0]])}
