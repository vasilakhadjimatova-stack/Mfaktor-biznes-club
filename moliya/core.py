"""
Hisob-kitob dvigateli — Mfaktor Moliya'ning "aqlli" qismi.

Jahon ta'lim-moliya standartlari shu yerda:
  • DDS (pul oqimi) — kassa usuli, hamyonlar kesimida
  • Revenue recognition — shartnoma daromadi kurs davomiga chiziqli
    taqsimlanadi (IFRS 15 ruhida): olingan avans = majburiyat
    (deferred revenue), o'tilgan davr = tan olingan daromad
  • Unit-ekonomika: CAC (kanal kesimida), ARPU, LTV, gross margin
  • BEP — zararsizlik: oyiga nechta o'quvchi kerak
  • Qarzdorlik aging — muddati o'tgan bo'lib to'lashlar
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

from database import db
from models import (Budget, Cohort, Contract, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction, Wallet)


# ══════════════════════════════════════════════════════════════════
#  KASSA QATLAMI — DDS / hamyon qoldiqlari
# ══════════════════════════════════════════════════════════════════
def wallet_balances():
    """Har hamyon: ochilish + kirim − chiqim ± transferlar."""
    wallets = Wallet.query.filter_by(is_active=True).order_by(Wallet.sort).all()
    delta = defaultdict(float)
    for t in Transaction.query.all():
        if t.is_transfer:
            delta[t.wallet_code] -= t.amount
            delta[t.transfer_to_wallet] += t.amount
        elif t.operation == "kirim":
            delta[t.wallet_code] += t.amount
        else:
            delta[t.wallet_code] -= t.amount
    rows = [{"wallet": w, "balance": w.opening + delta[w.code]} for w in wallets]
    return rows, sum(r["balance"] for r in rows)


def month_cashflow(year, month):
    """Oylik DDS: statya kesimida kirim/chiqim (transferlar hisobga olinmaydi)."""
    q = (Transaction.query
         .filter(Transaction.is_transfer.is_(False))
         .filter(func.extract("year", Transaction.tdate) == year)
         .filter(func.extract("month", Transaction.tdate) == month))
    inc, exp = defaultdict(float), defaultdict(float)
    for t in q:
        (inc if t.operation == "kirim" else exp)[t.category or "Boshqa"] += t.amount
    return {
        "income": dict(sorted(inc.items(), key=lambda x: -x[1])),
        "expense": dict(sorted(exp.items(), key=lambda x: -x[1])),
        "income_total": sum(inc.values()),
        "expense_total": sum(exp.values()),
        "net": sum(inc.values()) - sum(exp.values()),
    }


# ══════════════════════════════════════════════════════════════════
#  HISOBLASH QATLAMI — revenue recognition
# ══════════════════════════════════════════════════════════════════
def contract_recognized(contract, as_of=None):
    """Shartnoma bo'yicha shu sanagacha TAN OLINGAN daromad.

    Chiziqli usul: net narx × (o'tgan kunlar / kurs davomiyligi).
    Qaytarilgan shartnomada faqat qaytarilmagan qismi tan olinadi.
    """
    as_of = as_of or date.today()
    c = contract.cohort
    if contract.status == "cancelled":
        return 0.0
    base = contract.net_price - contract.refund_amount
    if base <= 0:
        return 0.0
    if as_of <= c.start_date:
        return 0.0
    if as_of >= c.end_date or contract.status == "completed":
        return base
    frac = (as_of - c.start_date).days / c.duration_days()
    return base * min(max(frac, 0.0), 1.0)


def accrual_summary(as_of=None):
    """Butun portfel: tan olingan daromad, deferred revenue, debitorka."""
    as_of = as_of or date.today()
    recognized = deferred = receivable = booked = 0.0
    for c in Contract.query.filter(Contract.status != "cancelled").all():
        rec = contract_recognized(c, as_of)
        paid = c.paid_total()
        base = c.net_price - c.refund_amount
        booked += base
        recognized += rec
        # to'langan, lekin hali "topilmagan" qism — majburiyat
        deferred += max(paid - rec, 0.0)
        # tan olingan, lekin hali to'lanmagan qism — debitorka
        receivable += max(min(rec, base) - paid, 0.0)
    return {"booked": booked, "recognized": recognized,
            "deferred": deferred, "receivable": receivable}


# ══════════════════════════════════════════════════════════════════
#  QARZDORLIK NAZORATI — aging
# ══════════════════════════════════════════════════════════════════
def overdue_lines(today=None):
    """Muddati o'tgan grafik qatorlari, aging bilan."""
    today = today or date.today()
    rows = []
    q = (InstallmentLine.query.join(Contract)
         .filter(Contract.status == "active")
         .filter(InstallmentLine.due_date < today).all())
    for line in q:
        rest = line.amount - line.paid
        if rest <= 0.01:
            continue
        days = (today - line.due_date).days
        bucket = ("1–7 kun" if days <= 7 else
                  "8–30 kun" if days <= 30 else "30+ kun")
        rows.append({"line": line, "contract": line.contract,
                     "rest": rest, "days": days, "bucket": bucket})
    rows.sort(key=lambda r: -r["days"])
    return rows


def upcoming_lines(days=7, today=None):
    """Yaqin N kunda to'lanishi kerak bo'lgan grafik qatorlari."""
    today = today or date.today()
    till = today + timedelta(days=days)
    q = (InstallmentLine.query.join(Contract)
         .filter(Contract.status == "active")
         .filter(InstallmentLine.due_date >= today,
                 InstallmentLine.due_date <= till)
         .order_by(InstallmentLine.due_date).all())
    return [{"line": l, "contract": l.contract, "rest": l.amount - l.paid}
            for l in q if l.amount - l.paid > 0.01]


# ══════════════════════════════════════════════════════════════════
#  UNIT-EKONOMIKA — CAC / ARPU / LTV / marja / fill rate
# ══════════════════════════════════════════════════════════════════
def marketing_spend_by_channel(year=None, month=None):
    q = Transaction.query.filter(Transaction.category == "Marketing/Reklama",
                                 Transaction.is_transfer.is_(False))
    if year:
        q = q.filter(func.extract("year", Transaction.tdate) == year)
    if month:
        q = q.filter(func.extract("month", Transaction.tdate) == month)
    out = defaultdict(float)
    for t in q:
        out[t.channel or "Boshqa"] += t.amount
    return dict(out)


def unit_economics(year, month):
    """Oylik unit-ekonomika: CAC (umumiy va kanal kesimida), ARPU, LTV."""
    spend = marketing_spend_by_channel(year, month)
    total_spend = sum(spend.values())
    # shu oyda imzolangan shartnomalar = yangi o'quvchilar
    new_contracts = (Contract.query
                     .filter(func.extract("year", Contract.signed_date) == year)
                     .filter(func.extract("month", Contract.signed_date) == month)
                     .filter(Contract.status != "cancelled").all())
    n_new = len(new_contracts)
    avg_check = (sum(c.net_price for c in new_contracts) / n_new) if n_new else 0.0
    cac = (total_spend / n_new) if n_new else 0.0
    # kanal kesimida CAC: o'quvchi manbasi bo'yicha
    by_src = defaultdict(int)
    for c in new_contracts:
        by_src[c.student.source or "Boshqa"] += 1
    cac_by_channel = {ch: {"spend": sp, "students": by_src.get(ch, 0),
                           "cac": sp / by_src[ch] if by_src.get(ch) else None}
                      for ch, sp in spend.items()}
    # LTV (sodda): o'quvchining barcha shartnomalari o'rtacha summasi
    ltv_val = ltv()
    return {"marketing_spend": total_spend, "new_students": n_new,
            "avg_check": avg_check, "cac": cac,
            "cac_by_channel": cac_by_channel, "ltv": ltv_val,
            "ltv_cac": (ltv_val / cac) if cac else None}


def ltv():
    """O'quvchi umrbod qiymati: jami net tushum ÷ o'quvchilar soni."""
    contracts = Contract.query.filter(Contract.status != "cancelled").all()
    if not contracts:
        return 0.0
    students = {c.student_id for c in contracts}
    total = sum(c.net_price - c.refund_amount for c in contracts)
    return total / len(students)


def cohort_report():
    """Har oqim: to'ldirilish, tushum, spiker/kontent xarajati, marja."""
    rows = []
    for ch in Cohort.query.order_by(Cohort.start_date.desc()).all():
        contracts = [c for c in ch.__dict__.get("_contracts", [])] or \
                    Contract.query.filter_by(cohort_id=ch.id).all()
        active = [c for c in contracts if c.status != "cancelled"]
        revenue = sum(c.net_price - c.refund_amount for c in active)
        paid = sum(c.paid_total() for c in active)
        # oqimga bog'liq to'g'ridan-to'g'ri xarajat: shu davrga tushgan
        # spiker gonorari + kontent (sodda taqsimot — davr bo'yicha)
        direct = (Transaction.query
                  .filter(Transaction.is_transfer.is_(False),
                          Transaction.operation == "chiqim",
                          Transaction.category.in_(
                              ["Spiker gonorari", "Kontent ishlab chiqarish"]),
                          Transaction.tdate >= ch.start_date,
                          Transaction.tdate <= ch.end_date)
                  .with_entities(func.coalesce(func.sum(Transaction.amount), 0.0))
                  .scalar())
        margin = revenue - direct
        rows.append({
            "cohort": ch, "students": len(active),
            "fill_rate": len(active) / ch.capacity * 100 if ch.capacity else 0,
            "revenue": revenue, "paid": paid, "direct_cost": direct,
            "margin": margin,
            "margin_pct": margin / revenue * 100 if revenue else 0,
            "refunds": sum(c.refund_amount for c in contracts),
        })
    return rows


# ══════════════════════════════════════════════════════════════════
#  BEP — zararsizlik nuqtasi
# ══════════════════════════════════════════════════════════════════
def break_even(year, month):
    """Oyiga nechta o'quvchi kerak: doimiy xarajat ÷ (o'rtacha chek marjasi)."""
    cf = month_cashflow(year, month)
    fixed_cats = ["Ish haqi (admin)", "Ijara", "Texnik platforma/IT",
                  "Xo'jalik xarajatlari"]
    fixed = sum(cf["expense"].get(c, 0.0) for c in fixed_cats)
    # takrorlanuvchi to'lovlar rejasi ham doimiy hisoblanadi (fakt bo'lmasa)
    rec = sum(r.amount for r in RecurringPayment.query.filter_by(is_active=True))
    fixed = max(fixed, rec)
    ue = unit_economics(year, month)
    avg = ue["avg_check"]
    # o'zgaruvchan ulush: spiker gonorari + komissiya taxminan tushumga nisbatan
    var_cats = ["Spiker gonorari", "Bank/to'lov komissiyasi",
                "Kontent ishlab chiqarish"]
    var = sum(cf["expense"].get(c, 0.0) for c in var_cats)
    inc = cf["income_total"]
    var_ratio = var / inc if inc else 0.3
    contribution = avg * (1 - var_ratio)
    need = (fixed / contribution) if contribution > 0 else None
    return {"fixed": fixed, "avg_check": avg, "var_ratio": var_ratio,
            "contribution": contribution, "students_needed": need}


# ══════════════════════════════════════════════════════════════════
#  BUDGET plan-fakt
# ══════════════════════════════════════════════════════════════════
def budget_planfact(year, month):
    cf = month_cashflow(year, month)
    plans = Budget.query.filter_by(year=year, month=month).all()
    rows = []
    for p in plans:
        fact = (cf["income"] if p.btype == "income" else cf["expense"]).get(p.category, 0.0)
        rows.append({"plan": p, "fact": fact,
                     "pct": fact / p.planned * 100 if p.planned else None,
                     "diff": fact - p.planned})
    rows.sort(key=lambda r: (r["plan"].btype, -abs(r["diff"])))
    return rows


# ══════════════════════════════════════════════════════════════════
#  DASHBOARD jamlamasi
# ══════════════════════════════════════════════════════════════════
def dashboard_data(today=None):
    today = today or date.today()
    y, m = today.year, today.month
    balances, total_balance = wallet_balances()
    cf = month_cashflow(y, m)
    acc = accrual_summary(today)
    over = overdue_lines(today)
    up = upcoming_lines(7, today)
    ue = unit_economics(y, m)
    return {
        "today": today, "balances": balances, "total_balance": total_balance,
        "cashflow": cf, "accrual": acc,
        "overdue": over, "overdue_total": sum(r["rest"] for r in over),
        "upcoming": up, "upcoming_total": sum(r["rest"] for r in up),
        "ue": ue,
        "active_contracts": Contract.query.filter_by(status="active").count(),
        "students": Student.query.count(),
    }
