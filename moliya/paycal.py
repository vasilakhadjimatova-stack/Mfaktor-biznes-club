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

import localtime

from database import db
from models import (CAL_GROUPS, InstallmentLine, PlanCell,
                    RecurringPayment, Transaction, Wallet)

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


def _in_by_day(year, month):
    """(day) -> haqiqiy kirim summasi (kassadan)."""
    rows = (Transaction.query
            .filter(Transaction.is_transfer.is_(False),
                    Transaction.activity != "tech",
                    Transaction.operation == "kirim",
                    func.extract("year", Transaction.tdate) == year,
                    func.extract("month", Transaction.tdate) == month)
            .all())
    out = defaultdict(float)
    for t in rows:
        out[t.tdate.day] += t.amount
    return out


def _cash_before(day):
    """Shu sanagacha bo'lgan haqiqiy kassa qoldig'i (hamma hamyon).

    O'tkazmalar hamyonlar orasida yuradi — umumiy qoldiqni o'zgartirmaydi,
    shuning uchun ular hisobga olinmaydi.
    """
    opening = db.session.query(func.sum(Wallet.opening)).filter_by(
        is_active=True).scalar() or 0.0
    q = (db.session.query(Transaction.operation, func.sum(Transaction.amount))
         .filter(Transaction.is_transfer.is_(False),
                 Transaction.tdate < day)
         .group_by(Transaction.operation).all())
    net = 0.0
    for op, amt in q:
        net += (amt or 0.0) if op == "kirim" else -(amt or 0.0)
    return opening + net


def _due_by_day(year, month, from_day):
    """Kutilayotgan kirim: shartnoma grafigidagi to'lanmagan qatorlar.

    Faqat kelgusi kunlar uchun — o'tgan kunlarda haqiqiy kirim allaqachon
    kassada, uni ikki marta hisoblab bo'lmaydi.
    """
    rows = (InstallmentLine.query
            .filter(func.extract("year", InstallmentLine.due_date) == year,
                    func.extract("month", InstallmentLine.due_date) == month,
                    InstallmentLine.due_date >= from_day)
            .all())
    out = defaultdict(float)
    for r in rows:
        rest = (r.amount or 0.0) - (r.paid or 0.0)
        if rest > 0.01:
            out[r.due_date.day] += rest
    return out


def _expected_out(year, month, ndays, plan_keys, from_idx):
    """Kutilayotgan chiqim: takroriy to'lovlar (ijara, oyliklar, obunalar).

    Faqat kelgusi kunlar uchun va faqat reja katagi BO'SH bo'lganda —
    buxgalter «Takrorlanuvchilardan» tugmasini bosgan bo'lsa, o'sha
    summa allaqachon rejada turadi, ikki marta hisoblanmasligi kerak.
    Bazaga hech narsa yozilmaydi: bu faqat prognoz qatlami.
    """
    per_day = [0.0] * ndays
    rows = defaultdict(list)
    for r in RecurringPayment.query.filter_by(is_active=True).all():
        day = min(max(int(r.pay_day or 1), 1), ndays)
        i = day - 1
        if i < from_idx:
            continue
        cat = (r.category or "").strip() or "Прочие расходы"
        if (cat, day) in plan_keys:          # rejaga allaqachon tushgan
            continue
        amt = r.amount or 0.0
        per_day[i] += amt
        rows[day].append({"n": r.name, "s": amt, "c": cat})
    return per_day, rows


def _expected_in_rows(year, month, from_day):
    """Kutilayotgan kirim qatorlari — kun paneli uchun (o'quvchi ismi bilan)."""
    out = defaultdict(list)
    for r in (InstallmentLine.query
              .filter(func.extract("year", InstallmentLine.due_date) == year,
                      func.extract("month", InstallmentLine.due_date) == month,
                      InstallmentLine.due_date >= from_day).all()):
        rest = (r.amount or 0.0) - (r.paid or 0.0)
        if rest <= 0.01:
            continue
        c = r.contract
        out[r.due_date.day].append({
            "n": (c.student.name if c and c.student else "O'quvchi"),
            "s": rest})
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

    # ── kalendar ustidagi tasvir uchun ──
    first_wd = date(year, month, 1).weekday()
    # katakning bo'yalish darajasi: eng og'ir kunga nisbatan (0…1)
    mx = max(day_f) or 1.0
    heat = [(v / mx) for v in day_f]

    # hafta qatorlari — kalendar to'ridagi satrlar bilan bir xil
    weeks = []
    for start in range(0, first_wd + ndays, 7):
        idx = [i for i in range(start - first_wd, start - first_wd + 7)
               if 0 <= i < ndays]
        if idx:
            weeks.append({"p": sum(day_p[i] for i in idx),
                          "f": sum(day_f[i] for i in idx),
                          "d1": idx[0] + 1, "d2": idx[-1] + 1})

    # ── kassa qoldig'i: o'tgan kunlarda haqiqiy, keyin prognoz ──
    today = localtime.today()
    tidx = today.day - 1 if (today.year == year and today.month == month) else None
    day_in = _in_by_day(year, month)
    day_in = [day_in.get(d, 0.0) for d in range(1, ndays + 1)]
    total_in = sum(day_in)

    # oy boshidagi haqiqiy qoldiq
    start_cash = _cash_before(date(year, month, 1))

    # oy o'tib ketgan bo'lsa hammasi fakt; kelajakda hammasi prognoz
    real_to = ndays - 1 if (tidx is None and date(year, month, 1) < today) else (
        tidx if tidx is not None else -1)

    # kelgusi kunlarda kutilayotgan kirim — shartnoma grafigidan
    from_day = date(year, month, min(real_to + 2, ndays)) if real_to + 1 < ndays \
        else date(year, month, ndays)
    due = _due_by_day(year, month, from_day)
    plan_in = [due.get(d, 0.0) if (d - 1) > real_to else 0.0
               for d in range(1, ndays + 1)]
    exp_out, exp_out_rows = _expected_out(year, month, ndays, set(plan.keys()),
                                          real_to + 1)
    exp_in_rows = _expected_in_rows(year, month, from_day)

    bal, run = [], start_cash
    for i in range(ndays):
        if i <= real_to:                       # o'tgan kun — haqiqiy harakat
            run += day_in[i] - day_f[i]
        else:                                  # kelgusi kun — kutilgani
            run += plan_in[i] - day_p[i] - exp_out[i]
        bal.append(run)

    lo, hi = min(0.0, min(bal)), max(0.0, max(bal))
    span = (hi - lo) or 1.0

    def by(v):
        return 150 - (v - lo) / span * 135

    def bpts(a, b):
        if b - a < 1:
            return ""
        return " ".join("%.1f,%.1f" % (i / (ndays - 1) * 600, by(bal[i]))
                        for i in range(a, b + 1))

    neg = [i for i in range(ndays) if bal[i] < 0]
    mn = min(range(ndays), key=lambda i: bal[i])

    return {
        "days": days, "groups": groups,
        "day_p": day_p, "day_f": day_f, "heat": heat, "weeks": weeks,
        "day_in": day_in, "plan_in": plan_in, "total_in": total_in,
        "exp_out": exp_out, "exp_out_rows": dict(exp_out_rows),
        "exp_in_rows": dict(exp_in_rows),
        "exp_out_total": sum(exp_out),
        "exp_in_total": sum(plan_in),
        "total_p": total_p, "total_f": total_f,
        "total_diff": total_f - total_p,
        "total_pct": (total_f / total_p * 100) if total_p > 0 else None,
        # qoldiq chizig'i: bugungacha to'liq, keyin uzuq (prognoz)
        "bal": bal, "start_cash": start_cash,
        "bal_real_pts": bpts(0, real_to) if real_to >= 1 else "",
        "bal_fc_pts": bpts(max(real_to, 0), ndays - 1) if real_to < ndays - 1 else "",
        "bal_zero_y": by(0.0),
        "bal_end": bal[-1],
        "bal_min": bal[mn], "bal_min_day": mn + 1,
        "gap_day": (neg[0] + 1) if neg else None,
        "today_cash": bal[tidx] if tidx is not None else None,
        "real_to": real_to,
        "today_x": (tidx / (ndays - 1) * 600) if tidx is not None else None,
        "ndays": ndays,
    }


def year_data(year):
    """Yillik hisobot: statya × 12 oy + guruh va yil bo'yicha xulosalar.

    Jadval uchun xom raqamlardan tashqari sahifada ko'rsatiladigan
    ko'rsatkichlar ham shu yerda hisoblanadi: guruhning yildagi ulushi,
    eng qimmat oy, faktli oylar soni va o'rtacha oylik xarajat. Shunda
    andoza faqat chizadi — hisob-kitob bir joyda turadi.
    """
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
        groups.append({
            "name": gname, "rows": rows,
            "p": [sum(r["p"][i] for r in rows) for i in range(12)],
            "f": [sum(r["f"][i] for r in rows) for i in range(12)],
            "tp": sum(r["tp"] for r in rows),
            "tf": sum(r["tf"] for r in rows),
        })

    month_p = [sum(r["p"][i] for r in all_rows) for i in range(12)]
    month_f = [sum(r["f"][i] for r in all_rows) for i in range(12)]
    total_p, total_f = sum(month_p), sum(month_f)

    # guruhning yildagi ulushi — qayerga ko'p ketayotganini ko'rsatadi
    for g in groups:
        g["share"] = (g["tf"] / total_f * 100) if total_f else 0.0
        g["rows"].sort(key=lambda r: r["tf"], reverse=True)
    groups_by_size = sorted(groups, key=lambda g: g["tf"], reverse=True)

    live = [i for i in range(12) if month_f[i]]
    peak = max(range(12), key=lambda i: month_f[i]) if live else None
    return {
        "groups": groups, "top_groups": groups_by_size[:4],
        "month_p": month_p, "month_f": month_f,
        "total_p": total_p, "total_f": total_f,
        "diff": total_f - total_p,
        "pct": (total_f / total_p * 100) if total_p else None,
        "max_month": max(max(month_f), max(month_p)) or 1,
        "live_months": len(live),
        "avg_month": (total_f / len(live)) if live else 0.0,
        "peak_month": peak,
        "peak_sum": month_f[peak] if peak is not None else 0.0,
        "has_plan": total_p > 0,
    }


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
