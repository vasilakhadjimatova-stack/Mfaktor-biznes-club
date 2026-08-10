"""To'lov taqvimi (платежный календарь) — Sheets'dagi
«Ежедневный календарь расходов» va «Годовая таблица» ning dastur ichidagi
ko'rinishi.

Farqlar (ataylab):
  • qatorlar — kassa ishlatadigan statyalarning o'zi, shuning uchun FAKT
    ustuni qo'lda ko'chirilmaydi: kassaga tushgan har bir chiqim o'zi
    kerakli katakka yig'iladi;
  • formulalar dastur ichida — Sheets'dagi kabi #REF! bo'lib sinmaydi;
  • reja katagi bosilganda joyida tahrirlanadi, jami va og'ishlar darhol
    qayta hisoblanadi.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date

from sqlalchemy import func

from database import db
from models import CAL_GROUPS, PlanCell, RecurringPayment, Transaction

WD = ["Du", "Se", "Cho", "Pa", "Ju", "Sha", "Ya"]


def _fact_by_day(year, month):
    """(category, day) -> haqiqiy chiqim summasi (kassadan)."""
    rows = (Transaction.query
            .filter(Transaction.is_transfer.is_(False),
                    Transaction.activity != "tech",
                    Transaction.operation == "chiqim",
                    func.extract("year", Transaction.tdate) == year,
                    func.extract("month", Transaction.tdate) == month)
            .all())
    out = defaultdict(float)
    for t in rows:
        out[(t.category or "Прочие расходы", t.tdate.day)] += t.amount
    return out


def _fact_by_month(year):
    """(category, month) -> haqiqiy chiqim summasi."""
    rows = (Transaction.query
            .filter(Transaction.is_transfer.is_(False),
                    Transaction.activity != "tech",
                    Transaction.operation == "chiqim",
                    func.extract("year", Transaction.tdate) == year)
            .all())
    out = defaultdict(float)
    for t in rows:
        out[(t.category or "Прочие расходы", t.tdate.month)] += t.amount
    return out


def month_data(year, month):
    """Oylik taqvim: guruh → statya → kunlik reja/fakt + jami/og'ish."""
    ndays = monthrange(year, month)[1]
    days = [{"d": d, "wd": WD[date(year, month, d).weekday()],
             "we": date(year, month, d).weekday() >= 5}
            for d in range(1, ndays + 1)]

    plan = {(c.category, c.day): (c.amount or 0.0)
            for c in PlanCell.query.filter_by(year=year, month=month).all()}
    fact = _fact_by_day(year, month)

    def cat_row(cat):
        p = [plan.get((cat, d), 0.0) for d in range(1, ndays + 1)]
        f = [fact.get((cat, d), 0.0) for d in range(1, ndays + 1)]
        tp, tf = sum(p), sum(f)
        return {"cat": cat, "p": p, "f": f, "tp": tp, "tf": tf,
                "diff": tf - tp,
                "pct": (tf / tp * 100) if tp > 0 else None}

    groups, all_rows = [], []
    for gname, cats in CAL_GROUPS:
        rows = [cat_row(c) for c in cats]
        all_rows += rows
        groups.append({
            "name": gname, "rows": rows,
            "tp": sum(r["tp"] for r in rows),
            "tf": sum(r["tf"] for r in rows),
        })

    day_p = [sum(r["p"][i] for r in all_rows) for i in range(ndays)]
    day_f = [sum(r["f"][i] for r in all_rows) for i in range(ndays)]
    total_p, total_f = sum(day_p), sum(day_f)
    return {
        "days": days, "groups": groups,
        "day_p": day_p, "day_f": day_f,
        "total_p": total_p, "total_f": total_f,
        "total_diff": total_f - total_p,
        "total_pct": (total_f / total_p * 100) if total_p > 0 else None,
    }


def year_data(year):
    """Yillik jadval: statya × 12 oy (reja/fakt/og'ish %)."""
    plan = defaultdict(float)
    for c in PlanCell.query.filter_by(year=year).all():
        plan[(c.category, c.month)] += c.amount or 0.0
    fact = _fact_by_month(year)

    groups, all_rows = [], []
    for gname, cats in CAL_GROUPS:
        rows = []
        for cat in cats:
            p = [plan.get((cat, m), 0.0) for m in range(1, 13)]
            f = [fact.get((cat, m), 0.0) for m in range(1, 13)]
            rows.append({"cat": cat, "p": p, "f": f,
                         "tp": sum(p), "tf": sum(f)})
        all_rows += rows
        groups.append({"name": gname, "rows": rows,
                       "tp": sum(r["tp"] for r in rows),
                       "tf": sum(r["tf"] for r in rows)})

    month_p = [sum(r["p"][i] for r in all_rows) for i in range(12)]
    month_f = [sum(r["f"][i] for r in all_rows) for i in range(12)]
    return {"groups": groups, "month_p": month_p, "month_f": month_f,
            "total_p": sum(month_p), "total_f": sum(month_f)}


def set_cell(year, month, day, category, amount):
    """Reja katagini yozish/yangilash; 0 — o'chirish. Yangi jami'larni beradi."""
    cell = PlanCell.query.filter_by(year=year, month=month, day=day,
                                    category=category).first()
    if amount and amount > 0:
        if cell is None:
            cell = PlanCell(year=year, month=month, day=day,
                            category=category)
            db.session.add(cell)
        cell.amount = amount
    elif cell is not None:
        db.session.delete(cell)
    db.session.commit()

    ndays = monthrange(year, month)[1]
    plan = {(c.category, c.day): (c.amount or 0.0)
            for c in PlanCell.query.filter_by(year=year, month=month).all()}
    fact = _fact_by_day(year, month)
    row_p = sum(plan.get((category, d), 0.0) for d in range(1, ndays + 1))
    row_f = sum(fact.get((category, d), 0.0) for d in range(1, ndays + 1))
    day_p = sum(v for (c, d), v in plan.items() if d == day)
    total_p = sum(plan.values())
    total_f = sum(fact.values())
    return {"row_p": row_p, "row_f": row_f, "row_diff": row_f - row_p,
            "row_pct": (row_f / row_p * 100) if row_p > 0 else None,
            "day_p": day_p, "total_p": total_p,
            "total_diff": total_f - total_p}


def fill_from_recurring(year, month):
    """Rejani takrorlanuvchi to'lovlardan to'ldiradi.

    Faqat BO'SH kataklarga yozadi — ikki marta bosilsa summa ikkilanmaydi,
    buxgalter qo'lda kiritganlari ham o'zgarmaydi.
    """
    ndays = monthrange(year, month)[1]
    want = defaultdict(float)
    for r in RecurringPayment.query.filter_by(is_active=True).all():
        cat = (r.category or "").strip() or "Прочие расходы"
        day = min(max(int(r.pay_day or 1), 1), ndays)
        want[(cat, day)] += r.amount or 0.0
    have = {(c.category, c.day)
            for c in PlanCell.query.filter_by(year=year, month=month).all()}
    made = skipped = 0
    for (cat, day), amt in want.items():
        if (cat, day) in have:
            skipped += 1
            continue
        db.session.add(PlanCell(year=year, month=month, day=day,
                                category=cat, amount=amt))
        made += 1
    db.session.commit()
    return {"made": made, "skipped": skipped}


def copy_from_prev(year, month):
    """O'tgan oy rejasini shu oyga ko'chiradi (bo'sh kataklarga)."""
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    ndays = monthrange(year, month)[1]
    have = {(c.category, c.day)
            for c in PlanCell.query.filter_by(year=year, month=month).all()}
    made = skipped = 0
    for c in PlanCell.query.filter_by(year=py, month=pm).all():
        day = min(c.day, ndays)
        if (c.category, day) in have:
            skipped += 1
            continue
        db.session.add(PlanCell(year=year, month=month, day=day,
                                category=c.category, amount=c.amount))
        have.add((c.category, day))
        made += 1
    db.session.commit()
    return {"made": made, "skipped": skipped, "py": py, "pm": pm}


def clear_month(year, month):
    n = PlanCell.query.filter_by(year=year, month=month).delete()
    db.session.commit()
    return n
