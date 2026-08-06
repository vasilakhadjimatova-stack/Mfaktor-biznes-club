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
import charts
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
    bep_viz = charts.bep_chart(capacity, main["contribution_after_cac"],
                               main["fixed_alloc"], main["bep_full"])
    return {"bep_viz": bep_viz,
            "base": base, "dir": d, "share": share, "cac": cac,
            "price": price, "capacity": capacity,
            "duration_days": duration_days,
            "main": main,
            "scenarios": [
                {"name": "Asosiy reja", "sim": main},
                {"name": "Narx −10%", "sim": scen_price},
                {"name": "CAC 2 baravar", "sim": scen_cac},
            ]}


# ══════════════════════════════════════════════════════════════════
#  LAUNCH-KALKULYATOR v2 — professional zararsizlik instrumenti
# ══════════════════════════════════════════════════════════════════
# Mentor soatbay stavkalari (MBM KPI jadvalidan)
MENTOR_RATES = {"A": 200_000, "B": 150_000, "C": 100_000}

# Voronka standart konversiyalari (MBM Biznes Matematika varag'idan)
FUNNEL_DEFAULTS = {"cr_quality": 0.50, "cr_demo": 0.48, "cr_sale": 0.33}


def funnel_cac(cpl, cr_quality, cr_demo, cr_sale):
    """Lid narxidan CAC: har bosqich konversiyasi orqali."""
    conv = max(cr_quality * cr_demo * cr_sale, 1e-6)
    return {"cac": cpl / conv, "conv": conv,
            "leads_per_student": 1 / conv}


def plan_v2(price, capacity, duration_days, *,
            discount_pct=0.0, refund_pct=None, sales_pct=0.0,
            material_per_student=0.0, teacher_cost=0.0,
            extra_fixed=0.0, fixed_share=None, fixed_monthly=None,
            cac=None, cpl=None, funnel=None, target_profit=0.0,
            course_name=""):
    """To'liq launch modeli. Barcha pul qiymatlari so'mda, foizlar 0..1."""
    base = market_baseline()
    d = direction_stats(course_name, base)

    refund_pct = base["refund_rate"] if refund_pct is None else refund_pct
    fixed_monthly = (base["fixed_monthly"] if fixed_monthly is None
                     else fixed_monthly)
    fixed_share = (fixed_share if fixed_share is not None
                   else (d["rev_share"] if d["rev_share"] > 0.05 else 0.25))

    # CAC: to'g'ridan-to'g'ri yoki voronka orqali
    fn = None
    if cpl:
        fn = funnel_cac(cpl, **(funnel or FUNNEL_DEFAULTS))
        cac_val = fn["cac"]
    elif cac is not None:
        cac_val = cac
    else:
        cac_val = base["cac"]

    months = max(duration_days / 30.0, 0.5)
    net_price = price * (1 - discount_pct)

    # 1 o'quvchiga tushadigan o'zgaruvchan xarajatlar
    var_sales = net_price * sales_pct
    var_refund = net_price * refund_pct
    var_per_student = var_sales + var_refund + material_per_student + cac_val
    contribution = net_price - var_per_student
    contr_pct = contribution / net_price * 100 if net_price else 0

    # doimiy (kursga tegishli) xarajatlar
    fixed_alloc = fixed_monthly * months * fixed_share
    fixed_total = teacher_cost + extra_fixed + fixed_alloc
    direct_fixed = teacher_cost + extra_fixed          # faqat kursning o'zi

    def bep(f):
        return (f / contribution) if contribution > 0 else None

    bep_cash = bep(direct_fixed)          # kurs o'zini oqlaydi
    bep_full = bep(fixed_total)           # ofis ulushi bilan
    bep_target = bep(fixed_total + target_profit)

    def outcome(n):
        rev = net_price * n
        return {
            "n": n, "revenue": rev,
            "sales": var_sales * n, "refunds": var_refund * n,
            "materials": material_per_student * n, "marketing": cac_val * n,
            "teacher": teacher_cost, "extra": extra_fixed,
            "fixed_alloc": fixed_alloc,
            "contribution_total": contribution * n,
            "profit_direct": contribution * n - direct_fixed,
            "profit": contribution * n - fixed_total,
            "margin_pct": ((contribution * n - fixed_total) / rev * 100)
                          if rev else 0,
            "leads": (fn["leads_per_student"] * n) if fn else None,
        }

    fills = [outcome(max(1, int(round(capacity * f))))
             for f in (0.5, 0.75, 1.0)]
    at_full = fills[-1]

    # xavfsizlik zapasi: to'lgan guruhga nisbatan
    safety = ((capacity - bep_full) / capacity * 100
              if bep_full is not None and capacity else None)

    # maqsadli marja uchun minimal narx (30% marja)
    def price_for_margin(target_margin=0.30, n=None):
        n = n or capacity
        if n <= 0:
            return None
        # p*n*(1-m) = p*n*(sales+refund) + (mat+cac)*n + fixed_total
        k = sales_pct + refund_pct
        denom = n * (1 - target_margin - k)
        if denom <= 0:
            return None
        return ((material_per_student + cac_val) * n + fixed_total) / denom

    # sezuvchanlik matritsasi: narx (−20..+20%) × to'lish (40..100%)
    price_steps = [-0.2, -0.1, 0.0, 0.1, 0.2]
    fill_steps = [0.4, 0.6, 0.8, 1.0]
    matrix = []
    for ps in price_steps:
        row = []
        p2 = price * (1 + ps)
        np2 = p2 * (1 - discount_pct)
        c2 = np2 - (np2 * (sales_pct + refund_pct) + material_per_student + cac_val)
        for fs in fill_steps:
            n = max(1, int(round(capacity * fs)))
            row.append(round(c2 * n - fixed_total))
        matrix.append({"label": f"{ps*100:+.0f}%", "vals": row})

    # tornado: har omilning foydaga ta'siri (±20%)
    def profit_with(**over):
        p = over.get("price", price)
        npx = p * (1 - over.get("discount_pct", discount_pct))
        cc = over.get("cac", cac_val)
        mat = over.get("material", material_per_student)
        rf = over.get("refund", refund_pct)
        tc = over.get("teacher", teacher_cost)
        c = npx - (npx * (sales_pct + rf) + mat + cc)
        return c * capacity - (tc + extra_fixed + fixed_alloc)

    p0 = profit_with()
    drivers = []
    for label, key, val in [
        ("Narx", "price", price), ("CAC (reklama)", "cac", cac_val),
        ("O'quvchi materiallari", "material", material_per_student),
        ("Qaytarish %", "refund", refund_pct),
        ("O'qituvchi to'lovi", "teacher", teacher_cost),
    ]:
        if not val:
            continue
        hi = profit_with(**{key: val * 1.2})
        lo = profit_with(**{key: val * 0.8})
        drivers.append({"name": label, "low": round(min(hi, lo) - p0),
                        "high": round(max(hi, lo) - p0),
                        "span": round(abs(hi - lo))})
    drivers.sort(key=lambda x: -x["span"])

    # xulosa/tavsiya
    verdict = _verdict(contribution, bep_full, capacity, at_full, safety,
                       price_for_margin(), price, fn)

    return {
        "inputs": {"price": price, "net_price": net_price, "capacity": capacity,
                   "duration_days": duration_days, "months": months,
                   "discount_pct": discount_pct, "refund_pct": refund_pct,
                   "sales_pct": sales_pct, "material": material_per_student,
                   "teacher_cost": teacher_cost, "extra_fixed": extra_fixed,
                   "fixed_share": fixed_share, "fixed_monthly": fixed_monthly,
                   "cac": cac_val, "cpl": cpl, "target_profit": target_profit},
        "funnel": fn, "dir": d, "base": base,
        "var_per_student": var_per_student, "contribution": contribution,
        "contr_pct": contr_pct,
        "fixed_alloc": fixed_alloc, "direct_fixed": direct_fixed,
        "fixed_total": fixed_total,
        "bep_cash": bep_cash, "bep_full": bep_full, "bep_target": bep_target,
        "safety": safety, "fills": fills, "at_full": at_full,
        "min_price_30": price_for_margin(),
        "matrix": {"price_steps": [f"{p*100:+.0f}%" for p in price_steps],
                   "fill_steps": [f"{int(f*100)}%" for f in fill_steps],
                   "rows": matrix},
        "drivers": drivers,
        "curve": _curve(capacity, contribution, fixed_total, direct_fixed),
        "verdict": verdict,
    }


def _curve(capacity, contribution, fixed_total, direct_fixed):
    """Foyda egri chizig'i: 0 dan sig'imgacha (+20% zaxira)."""
    top = max(int(capacity * 1.2), capacity + 2)
    xs = list(range(0, top + 1))
    return {
        "x": xs,
        "profit": [round(contribution * n - fixed_total) for n in xs],
        "direct": [round(contribution * n - direct_fixed) for n in xs],
        "capacity": capacity,
    }


def _verdict(contribution, bep_full, capacity, at_full, safety,
             min_price, price, fn):
    """Ochish tavsiya etiladimi — sabablari bilan."""
    reasons = []
    if contribution <= 0:
        return {"ok": False, "level": "bad",
                "title": "Bu shartlarda kursni ochib bo'lmaydi",
                "reasons": ["Har bir o'quvchi zarar keltiradi: narxdan "
                            "xarajatlar va reklama ko'proq. Narxni oshirish "
                            "yoki CAC'ni tushirish shart."]}
    if bep_full is None or bep_full > capacity:
        reasons.append(f"Zararsizlik uchun {bep_full:.0f} o'quvchi kerak, "
                       f"lekin guruhga faqat {capacity} kishi sig'adi.")
        if min_price:
            reasons.append(f"30% marja uchun narx kamida "
                           f"{min_price:,.0f} so'm bo'lishi kerak "
                           f"(hozir {price:,.0f}).")
        return {"ok": False, "level": "bad",
                "title": "Kurs joriy shartlarda zarar keltiradi",
                "reasons": reasons}
    if safety is not None and safety < 25:
        reasons.append(f"Xavfsizlik zaxirasi atigi {safety:.0f}% — "
                       f"guruh biroz to'lmasa, kurs zararga o'tadi.")
    if at_full["margin_pct"] < 20:
        reasons.append(f"To'liq guruhda ham marja {at_full['margin_pct']:.0f}% — "
                       f"sog'lom daraja 25–35%.")
    if fn and fn["leads_per_student"] > 25:
        reasons.append(f"1 o'quvchi uchun {fn['leads_per_student']:.0f} ta lid "
                       f"kerak — voronka juda zaif, konversiyani oshirish shart.")
    if not reasons:
        return {"ok": True, "level": "good",
                "title": "Kursni ochish mumkin",
                "reasons": [
                    f"Zararsizlik {bep_full:.0f} o'quvchida — bu sig'imning "
                    f"{bep_full/capacity*100:.0f}% i.",
                    f"To'liq guruhda foyda {at_full['profit']:,.0f} so'm "
                    f"({at_full['margin_pct']:.0f}% marja).",
                    f"Xavfsizlik zaxirasi {safety:.0f}% — guruh to'lmasa ham "
                    f"chidaydi."]}
    return {"ok": True, "level": "warn",
            "title": "Ochish mumkin, lekin xavflar bor",
            "reasons": reasons}
