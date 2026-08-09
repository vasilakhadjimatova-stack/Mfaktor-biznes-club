"""KPI moduli — MBM_KPI_Full_Version_2026 jadvali asosida.

Har lavozim uchun oylik KPI kartasi: ko'rsatkichlar (Reja/Fakt/Vazn),
umumiy ball, bonus shkalasi va oylik hisobi (GARANT + BONUS).
Sotuv fakti va yangi o'quvchilar soni moliyadan avtomatik olinadi.
"""
from models import db, KpiCard, KpiItem
import core

# Excel'dagi 4 lavozim andozasi
TEMPLATES = [
    {
        "role_key": "rop", "role_name": "Sotuv bo'limi rahbari (РОП)",
        "garant": 7_000_000, "bonus_mode": "pct",
        "items": [
            {"name": "Sotuv rejasi", "plan_value": 810_000_000, "unit": "so'm",
             "weight": 0.6, "auto_key": "sales_month"},
            {"name": "Yangi o'quvchilar soni", "plan_value": 80, "unit": "ta",
             "weight": 0.2, "auto_key": "new_students"},
            {"name": "Haftalik reja bajarilishi", "plan_value": 100, "unit": "%",
             "plan_label": "kechikish 2 haftadan oshmasin", "weight": 0.1},
            {"name": "Sotuv konversiyasi (CR)", "plan_value": 10, "unit": "%",
             "weight": 0.1},
        ],
    },
    {
        "role_key": "marketolog", "role_name": "Marketolog",
        "garant": 5_500_000, "bonus_mode": "pct",
        "items": [
            {"name": "Umumiy lidlar soni", "plan_value": 2133, "unit": "ta",
             "weight": 0.2},
            {"name": "Sifatli lidlar soni", "plan_value": 1600, "unit": "ta",
             "weight": 0.6},
            {"name": "Lid narxi (CPL)", "plan_value": 3, "unit": "$",
             "weight": 0.1, "inverse": True},
            {"name": "Haftalik reja bajarilishi", "plan_value": 100, "unit": "%",
             "plan_label": "kechikish 2 haftadan oshmasin", "weight": 0.1},
        ],
    },
    {
        "role_key": "kurator", "role_name": "O'quv bo'limi kuratori",
        "garant": 3_000_000, "bonus_mode": "fixed",
        "items": [
            {"name": "Darsga qatnashish", "plan_value": 87.5, "unit": "%",
             "plan_label": "85–90%", "weight": 0.2},
            {"name": "Ketib qolish (churn)", "plan_value": 10, "unit": "%",
             "plan_label": "<10%", "weight": 0.15, "inverse": True},
            {"name": "Vazifalarni topshirish", "plan_value": 70, "unit": "%",
             "plan_label": "70% dan yuqori", "weight": 0.3},
            {"name": "Servis sifati (o'quvchilar bahosi)", "plan_value": 5,
             "unit": "ball", "weight": 0.2},
            {"name": "Tashabbuskorlik", "plan_value": 5, "unit": "ball",
             "weight": 0.15},
        ],
    },
    {
        "role_key": "hr", "role_name": "HR menejer",
        "garant": 3_000_000, "bonus_mode": "fixed",
        "items": [
            {"name": "Vakansiyani yopish tezligi", "plan_value": 10, "unit": "kun",
             "plan_label": "1–10 ish kuni", "weight": 0.2, "inverse": True},
            {"name": "Yangi xodimlar 2 oydan ko'p qolishi", "plan_value": 100,
             "unit": "%", "weight": 0.15},
            {"name": "Reglamentlar ishlab chiqilishi", "plan_value": 100,
             "unit": "%", "weight": 0.3},
            {"name": "Inspeksiya (checklist) bajarilishi", "plan_value": 100,
             "unit": "%", "weight": 0.2},
            {"name": "Tashabbuskorlik", "plan_value": 5, "unit": "ball",
             "weight": 0.15},
        ],
    },
]

# Bonus shkalalari (Excel'dagi jadval bilan bir xil)
PCT_TIERS = [(0.70, 0.0), (0.80, 0.01), (0.90, 0.02), (1.00, 0.03), (9.9, 0.035)]
FIXED_TIERS = [(0.70, 0), (0.80, 500_000), (0.90, 1_000_000), (9.9, 2_000_000)]


def ensure_month(year, month):
    """Oy uchun kartalar yo'q bo'lsa — avvalgi oydan yoki andozadan yaratadi."""
    cards = KpiCard.query.filter_by(year=year, month=month).all()
    if cards:
        return cards
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    prev = KpiCard.query.filter_by(year=py, month=pm).all()
    if prev:
        for p in prev:
            c = KpiCard(year=year, month=month, role_key=p.role_key,
                        role_name=p.role_name, person=p.person,
                        garant=p.garant, bonus_mode=p.bonus_mode)
            db.session.add(c)
            for it in p.items:
                db.session.add(KpiItem(
                    card=c, name=it.name, plan_value=it.plan_value,
                    plan_label=it.plan_label, unit=it.unit, weight=it.weight,
                    inverse=it.inverse, auto_key=it.auto_key))
    else:
        for t in TEMPLATES:
            c = KpiCard(year=year, month=month, role_key=t["role_key"],
                        role_name=t["role_name"], garant=t["garant"],
                        bonus_mode=t["bonus_mode"])
            db.session.add(c)
            for it in t["items"]:
                db.session.add(KpiItem(card=c, **it))
    db.session.commit()
    return KpiCard.query.filter_by(year=year, month=month).all()


def autofill(card):
    """Moliya ma'lumotlaridan faktlarni avtomatik to'ldirish."""
    filled = []
    for it in card.items:
        if it.auto_key == "sales_month":
            cf = core.month_cashflow(card.year, card.month)
            it.fact = round(cf["income_total"])
            filled.append(it.name)
        elif it.auto_key == "new_students":
            ue = core.unit_economics(card.year, card.month)
            it.fact = ue["new_students"]
            filled.append(it.name)
    db.session.commit()
    return filled


def compute(card):
    """Kartani hisoblash: indexlar, umumiy ball, bonus, oylik."""
    rows, total = [], 0.0
    for it in card.items:
        idx = None
        if it.fact is not None and it.plan_value:
            if it.inverse:
                idx = (it.plan_value / it.fact) if it.fact else 1.5
            else:
                idx = it.fact / it.plan_value
            idx = max(0.0, min(idx, 1.5))   # himoya chegarasi
            total += idx * it.weight
        rows.append({"item": it, "idx": idx,
                     "wfact": (idx or 0) * it.weight})
    # bonus
    if card.bonus_mode == "pct":
        base = core.month_cashflow(card.year, card.month)["income_total"]
        rate = next(r for lim, r in PCT_TIERS if total <= lim)
        bonus = base * rate
        bonus_note = f"tushum {core_short(base)} × {rate*100:.1f}%"
    else:
        bonus = next(b for lim, b in FIXED_TIERS if total <= lim)
        bonus_note = "qat'iy shkala bo'yicha"
    return {"rows": rows, "total": total, "bonus": round(bonus),
            "bonus_note": bonus_note, "salary": round(card.garant + bonus),
            "has_facts": any(r["idx"] is not None for r in rows)}


def core_short(v):
    if abs(v) >= 1e9:
        return f"{v/1e9:.1f} mlrd"
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f} mln"
    return f"{v:,.0f}".replace(",", " ")
