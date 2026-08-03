"""
Yangi kurs/oqim LAUNCH-KALKULYATORI.

Yangi oqim ochishdan OLDIN savollar aniq javob oladi:
  • Zararsizlik: nechta o'quvchi kerak (2 xil: o'z xarajatini qoplash /
    doimiy xarajat ulushi bilan)
  • To'ldirilish darajalarida marja (50% / 75% / 100%)
  • Sezuvchanlik: narx −10%, CAC 2x bo'lsa nima bo'ladi

Bashorat HAVODAN emas — REAL tarixdan:
  • Yo'nalish o'zgaruvchan ulushi = (yo'nalish zarplatasi + premiya ulushi +
    kofe-breyk ulushi + bitiruv ulushi) / yo'nalish tushumi (import fakti)
  • Qaytarish foizi = real возврат / tushum
  • CAC = real target xarajati / yangi to'lovchilar
  • Doimiy xarajat = RecurringPayment yig'indisi (TB 2026 dan yuklangan)
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import func

from database import db
from models import (Contract, Course, RecurringPayment, Transaction,
                    DIRECTION_INCOME, DIRECTION_SALARY)

# tushumga qarab taqsimlanadigan umumiy o'zgaruvchan statyalar
SHARED_VAR_CATS = ["Премия", "Кофе-брейк", "Выпускные расходы",
                   "Комиссия банка"]
REFUND_CAT = "Возврат клиенту"


def _sum_cat(cats):
    q = (Transaction.query
         .filter(Transaction.is_transfer.is_(False),
                 Transaction.activity == "operating",
                 Transaction.category.in_(cats))
         .with_entities(func.coalesce(func.sum(Transaction.amount), 0.0)))
    return q.scalar() or 0.0


def market_baseline():
    """Butun biznes bo'yicha real bazaviy ko'rsatkichlar."""
    income_by_dir = {}
    for key, cat in DIRECTION_INCOME.items():
        if cat not in income_by_dir.values():
            income_by_dir[cat] = _sum_cat([cat])
    total_income = sum(income_by_dir.values()) or 1.0

    shared_var = _sum_cat(SHARED_VAR_CATS)
    refunds = _sum_cat([REFUND_CAT])
    refund_rate = refunds / total_income

    # CAC: target xarajati / unikal yangi to'lovchilar (taxminiy metod)
    target = _sum_cat(["Таргет (реклама)"])
    payers = set()
    for t in Transaction.query.filter(
            Transaction.category.in_(list(income_by_dir.keys()))):
        n = " ".join(sorted((t.counterparty or "").lower().split()))
        if len(n) > 4:
            payers.add(n)
    cac = target / len(payers) if payers else 0.0

    fixed_monthly = sum(r.amount for r in
                        RecurringPayment.query.filter_by(is_active=True))
    return {"income_by_dir": income_by_dir, "total_income": total_income,
            "shared_var": shared_var, "refund_rate": refund_rate,
            "cac": cac, "fixed_monthly": fixed_monthly,
            "n_payers": len(payers)}


def direction_stats(course_name, base=None):
    """Kurs yo'nalishi bo'yicha real o'zgaruvchan xarajat ulushi."""
    base = base or market_baseline()
    up = (course_name or "").upper()
    income_cat = salary_cat = None
    for key, cat in DIRECTION_INCOME.items():
        if key in up:
            income_cat = cat
            salary_cat = DIRECTION_SALARY.get(key)
            break
    if not income_cat:
        # yangi yo'nalish — umumiy o'rtacha
        rev = base["total_income"]
        salary = _sum_cat(list(set(DIRECTION_SALARY.values())))
    else:
        rev = base["income_by_dir"].get(income_cat, 0.0)
        salary = _sum_cat([salary_cat]) if salary_cat else 0.0

    rev_share = rev / base["total_income"] if base["total_income"] else 0
    shared_alloc = base["shared_var"] * rev_share
    var_ratio = (salary + shared_alloc) / rev if rev > 0 else 0.35
    return {"income_cat": income_cat or "Yangi yo'nalish",
            "revenue_hist": rev, "salary_hist": salary,
            "shared_alloc": shared_alloc,
            "var_ratio": min(var_ratio, 0.9),
            "rev_share": rev_share}


def simulate(price, capacity, duration_days, var_ratio, refund_rate,
             cac, fixed_monthly, fixed_alloc_share):
    """Bitta ssenariyni hisoblash."""
    months = max(duration_days / 30.0, 0.5)
    fixed_alloc = fixed_monthly * months * fixed_alloc_share
    contribution = price * (1 - var_ratio - refund_rate)

    def outcome(students):
        revenue = price * students
        var_cost = revenue * var_ratio
        refunds = revenue * refund_rate
        marketing = cac * students
        margin_own = revenue - var_cost - refunds - marketing
        margin_full = margin_own - fixed_alloc
        return {"students": students, "revenue": revenue,
                "var_cost": var_cost, "refunds": refunds,
                "marketing": marketing, "fixed_alloc": fixed_alloc,
                "margin_own": margin_own, "margin_full": margin_full,
                "margin_full_pct": margin_full / revenue * 100 if revenue else 0}

    # har o'quvchining CAC'dan keyingi hissasi — bu musbat bo'lmasa,
    # kurs hech qachon o'zini oqlamaydi
    contribution_after_cac = contribution - cac
    bep_full = (fixed_alloc / contribution_after_cac
                if contribution_after_cac > 0 else None)

    fills = [outcome(max(int(round(capacity * f)), 1))
             for f in (0.5, 0.75, 1.0)]
    return {"contribution": contribution,
            "contribution_after_cac": contribution_after_cac,
            "fixed_alloc": fixed_alloc, "months": months,
            "bep_full": bep_full, "fills": fills, "outcome": outcome}


def launch_plan(course_name, price, capacity, duration_days,
                fixed_alloc_share=None, cac=None):
    """To'liq launch tahlili: baza + yo'nalish + ssenariylar + sezuvchanlik."""
    base = market_baseline()
    d = direction_stats(course_name, base)
    # doimiy xarajat ulushi: yo'nalishning tarixiy tushumdagi ulushi
    # (yangi yo'nalishga standart 25%)
    share = (fixed_alloc_share if fixed_alloc_share is not None
             else (d["rev_share"] if d["rev_share"] > 0.05 else 0.25))
    cac = cac if cac is not None else base["cac"]
    args = dict(price=price, capacity=capacity, duration_days=duration_days,
                var_ratio=d["var_ratio"], refund_rate=base["refund_rate"],
                cac=cac, fixed_monthly=base["fixed_monthly"],
                fixed_alloc_share=share)
    main = simulate(**args)
    # sezuvchanlik ssenariylari
    scen_price = simulate(**{**args, "price": price * 0.9})
    scen_cac = simulate(**{**args, "cac": cac * 2})

    def bep_str(s):
        return s["bep_full"]
    return {"base": base, "dir": d, "share": share, "cac": cac,
            "price": price, "capacity": capacity,
            "duration_days": duration_days,
            "main": main,
            "scenarios": [
                {"name": "Asosiy reja", "sim": main},
                {"name": "Narx −10%", "sim": scen_price},
                {"name": "CAC 2 baravar", "sim": scen_cac},
            ]}
