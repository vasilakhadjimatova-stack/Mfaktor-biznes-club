"""Chuqur tahlil qatlami — boshqaruv hisobotlari.

Bu modul moliyaviy ma'lumotni "raqamlar" darajasidan "qarorlar" darajasiga
ko'taradi: P&L tuzilmasi, trend va prognoz, yo'nalishlar rentabelligi,
qarzdorlik yoshi, qaytarishlar tahlili va avtomatik xulosalar.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

import core
from models import (Contract, Cohort, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction)

MN = ["", "Yan", "Fev", "Mar", "Apr", "May", "Iyn",
      "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]

# P&L guruhlari — statyalarni ma'noli bloklarga yig'amiz
VAR_CATS = ["Зарплата СМК", "Зарплата РОП", "Зарплата ТББ", "Премия",
            "Комиссия банка", "Кофе-брейк", "Выпускные расходы"]
MKT_CATS = ["Таргет (реклама)"]
REFUND_CATS = ["Возврат клиенту"]
FIN_CATS = ["Дивиденды", "Налог/дивиденд Зп"]


def _months_back(year, month, n):
    """Oxirgi n oy ro'yxati (eng eskisidan)."""
    out = []
    y, m = year, month
    for _ in range(n):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


# ══════════════════════════════════════════════════════════════════
#  1. P&L — foyda qanday shakllanadi
# ══════════════════════════════════════════════════════════════════
def pnl(year, month):
    cf = core.month_cashflow(year, month)
    inc = cf["income_total"]
    refunds = sum(cf["expense"].get(c, 0.0) for c in REFUND_CATS)
    var = sum(cf["expense"].get(c, 0.0) for c in VAR_CATS)
    mkt = sum(cf["expense"].get(c, 0.0) for c in MKT_CATS)
    fin = sum(cf["expense"].get(c, 0.0) for c in FIN_CATS)
    accounted = set(REFUND_CATS + VAR_CATS + MKT_CATS + FIN_CATS)
    fixed = sum(v for k, v in cf["expense"].items() if k not in accounted)

    net_rev = inc - refunds
    gross = net_rev - var
    after_mkt = gross - mkt
    op = after_mkt - fixed
    return {
        "income": inc, "refunds": refunds, "net_rev": net_rev,
        "var": var, "gross": gross, "gross_pct": gross / net_rev * 100 if net_rev else 0,
        "mkt": mkt, "after_mkt": after_mkt,
        "fixed": fixed, "op": op, "op_pct": op / net_rev * 100 if net_rev else 0,
        "fin": fin, "net": op - fin,
        "steps": [
            {"name": "Tushum", "value": inc, "kind": "start"},
            {"name": "Qaytarish", "value": refunds, "kind": "minus"},
            {"name": "O'zgaruvchan", "value": var, "kind": "minus"},
            {"name": "Marketing", "value": mkt, "kind": "minus"},
            {"name": "Doimiy", "value": fixed, "kind": "minus"},
            {"name": "Operatsion foyda", "value": op, "kind": "end"},
        ],
    }


# ══════════════════════════════════════════════════════════════════
#  2. Trend va prognoz
# ══════════════════════════════════════════════════════════════════
def trend(year, month, back=12, ahead=3):
    """Oxirgi `back` oy fakti + keyingi `ahead` oy prognozi (3 oylik o'rtacha
    o'sish sur'ati bilan). Kassa qoldig'i traektoriyasi ham qaytariladi."""
    hist = []
    for y, m in _months_back(year, month, back):
        cf = core.month_cashflow(y, m)
        hist.append({"label": f"{MN[m]} {str(y)[2:]}",
                     "inc": round(cf["income_total"]),
                     "exp": round(cf["expense_total"]),
                     "net": round(cf["net"])})

    def _forecast(key):
        vals = [h[key] for h in hist if h[key]]
        if len(vals) < 3:
            return [round(vals[-1]) if vals else 0] * ahead
        base = sum(vals[-3:]) / 3
        prev = sum(vals[-6:-3]) / 3 if len(vals) >= 6 else base
        g = (base / prev) if prev > 0 else 1.0
        g = max(0.85, min(g, 1.15))          # ekstremal o'sishni cheklash
        out, cur = [], base
        for _ in range(ahead):
            cur *= g
            out.append(round(cur))
        return out

    f_inc, f_exp = _forecast("inc"), _forecast("exp")
    labels = [h["label"] for h in hist]
    y, m = year, month
    for i in range(ahead):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        labels.append(f"{MN[m]} {str(y)[2:]} ·")

    n = len(hist)
    return {
        "labels": labels,
        "inc": [h["inc"] for h in hist] + [None] * ahead,
        "exp": [h["exp"] for h in hist] + [None] * ahead,
        "net": [h["net"] for h in hist] + [None] * ahead,
        # prognoz chizig'i oxirgi fakt nuqtasidan davom etadi
        "f_inc": [None] * (n - 1) + [hist[-1]["inc"]] + f_inc if hist else [],
        "f_exp": [None] * (n - 1) + [hist[-1]["exp"]] + f_exp if hist else [],
        "next_inc": f_inc, "next_exp": f_exp,
        "next_net": [i - e for i, e in zip(f_inc, f_exp)],
    }


def runway(year, month):
    """Kassa necha oyga yetadi (oxirgi 3 oyning o'rtacha sof oqimi bilan)."""
    _rows, cash = core.wallet_balances()
    nets = []
    for y, m in _months_back(year, month, 3):
        nets.append(core.month_cashflow(y, m)["net"])
    avg = sum(nets) / len(nets) if nets else 0
    months = (cash / -avg) if avg < 0 else None
    return {"cash": cash, "avg_net": avg, "months": months}


# ══════════════════════════════════════════════════════════════════
#  3. Yo'nalishlar rentabelligi (РОП / СМК / ТББ)
# ══════════════════════════════════════════════════════════════════
DIRS = [
    ("РОП", "Поступление от клиента РОП", "Зарплата РОП"),
    ("СМК", "Поступление от клиента СМК", "Зарплата СМК"),
    ("ТББ", "Поступление от клиента ТББ", "Зарплата ТББ"),
]


def directions(year, month=None):
    """Yo'nalish kesimida: tushum, to'g'ridan-to'g'ri ish haqi, marja."""
    def _sum(cat, op):
        q = (Transaction.query
             .filter(Transaction.is_transfer.is_(False),
                     Transaction.activity != "tech",
                     Transaction.operation == op,
                     Transaction.category == cat,
                     func.extract("year", Transaction.tdate) == year))
        if month:
            q = q.filter(func.extract("month", Transaction.tdate) == month)
        return q.with_entities(
            func.coalesce(func.sum(Transaction.amount), 0.0)).scalar() or 0.0

    rows = []
    for name, inc_cat, sal_cat in DIRS:
        inc = _sum(inc_cat, "kirim")
        sal = _sum(sal_cat, "chiqim")
        rows.append({"name": name, "income": inc, "salary": sal,
                     "margin": inc - sal,
                     "margin_pct": (inc - sal) / inc * 100 if inc else 0,
                     "sal_pct": sal / inc * 100 if inc else 0})
    total = sum(r["income"] for r in rows) or 1.0
    for r in rows:
        r["share"] = r["income"] / total * 100
    rows.sort(key=lambda r: -r["income"])
    return rows


# ══════════════════════════════════════════════════════════════════
#  4. Qarzdorlik yoshi (aging)
# ══════════════════════════════════════════════════════════════════
AGING = [(15, "1–15 kun"), (30, "16–30 kun"), (60, "31–60 kun"), (10**6, "60+ kun")]


def aging(today=None):
    today = today or date.today()
    buckets = {label: {"sum": 0.0, "n": 0} for _, label in AGING}
    rows = core.overdue_lines(today)
    for r in rows:
        for lim, label in AGING:
            if r["days"] <= lim:
                buckets[label]["sum"] += r["rest"]
                buckets[label]["n"] += 1
                break
    total = sum(b["sum"] for b in buckets.values())
    # eng qarigan 60+ ulushi — "yo'qolish xavfi"
    risk = buckets["60+ kun"]["sum"]
    return {"buckets": buckets, "total": total, "risk": risk,
            "risk_pct": risk / total * 100 if total else 0,
            "count": len(rows)}


# ══════════════════════════════════════════════════════════════════
#  5. Qaytarishlar (refund) tahlili
# ══════════════════════════════════════════════════════════════════
def refunds(year):
    by_month = [0.0] * 12
    q = (Transaction.query
         .filter(Transaction.is_transfer.is_(False),
                 Transaction.category.in_(REFUND_CATS),
                 func.extract("year", Transaction.tdate) == year))
    items = q.all()
    for t in items:
        by_month[t.tdate.month - 1] += t.amount
    total = sum(by_month)
    inc_year = 0.0
    for m in range(1, 13):
        inc_year += core.month_cashflow(year, m)["income_total"]
    big = sorted(items, key=lambda t: -t.amount)[:5]
    return {"by_month": [round(v) for v in by_month], "total": total,
            "pct": total / inc_year * 100 if inc_year else 0,
            "count": len(items), "big": big,
            "big_share": sum(t.amount for t in big) / total * 100 if total else 0}


# ══════════════════════════════════════════════════════════════════
#  6. Xarajat tarkibi (top statyalar)
# ══════════════════════════════════════════════════════════════════
def expense_mix(year, month, top=8):
    cf = core.month_cashflow(year, month)
    items = sorted(cf["expense"].items(), key=lambda x: -x[1])
    head, tail = items[:top], items[top:]
    rows = [{"cat": k, "val": v} for k, v in head]
    if tail:
        rows.append({"cat": "Boshqa", "val": sum(v for _, v in tail)})
    tot = cf["expense_total"] or 1
    for r in rows:
        r["pct"] = r["val"] / tot * 100
    return rows


# ══════════════════════════════════════════════════════════════════
#  7. Avtomatik xulosalar — nima qilish kerakligini aytadi
# ══════════════════════════════════════════════════════════════════
def insights(year, month):
    out = []
    p = pnl(year, month)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    pp = pnl(prev_y, prev_m)
    ue = core.unit_economics(year, month)
    ag = aging()
    rw = runway(year, month)
    dirs = directions(year, month)

    def add(kind, title, text):
        out.append({"kind": kind, "title": title, "text": text})

    # operatsion foyda
    if p["op"] < 0:
        add("bad", "Oy zarar bilan yopilmoqda",
            f"Operatsion natija {p['op']:,.0f} so'm. Doimiy xarajat "
            f"{p['fixed']:,.0f} so'm — bu tushumning "
            f"{p['fixed']/p['net_rev']*100 if p['net_rev'] else 0:.0f}% i.")
    elif p["op_pct"] < 15:
        add("warn", "Foyda marjasi past",
            f"Operatsion marja {p['op_pct']:.0f}% — sog'lom ta'lim biznesi "
            f"uchun 20–30% maqsad qilinadi.")
    else:
        add("good", "Foyda marjasi sog'lom",
            f"Operatsion marja {p['op_pct']:.0f}% — yaxshi daraja.")

    # tushum dinamikasi
    if pp["income"]:
        d = (p["income"] - pp["income"]) / pp["income"] * 100
        if d <= -15:
            add("bad", "Tushum keskin tushdi",
                f"O'tgan oyga nisbatan {abs(d):.0f}% kam. Sabab: yangi "
                f"o'quvchilar oqimi yoki oqim jadvali bo'shligi bo'lishi mumkin.")
        elif d >= 15:
            add("good", "Tushum o'smoqda", f"O'tgan oyga nisbatan +{d:.0f}%.")

    # CAC / LTV
    if ue["cac"] and ue["ltv_cac"]:
        if ue["ltv_cac"] < 3:
            add("warn", "Jalb qilish narxi qimmat",
                f"LTV/CAC = {ue['ltv_cac']:.1f} (3 dan yuqori bo'lishi kerak). "
                f"1 o'quvchi {ue['cac']:,.0f} so'mga tushmoqda.")
        else:
            add("good", "Marketing samarali",
                f"LTV/CAC = {ue['ltv_cac']:.1f} — 1 so'm reklama "
                f"{ue['ltv_cac']:.1f} so'm qiymat keltirmoqda.")
    elif ue["marketing_spend"] and not ue["new_students"]:
        add("bad", "Reklama pul yemoqda, natija yo'q",
            f"Bu oy {ue['marketing_spend']:,.0f} so'm sarflandi, yangi "
            f"shartnoma esa yo'q.")

    # qarzdorlik
    if ag["risk"] > 0:
        add("bad" if ag["risk_pct"] > 40 else "warn", "Eski qarzlar xavfi",
            f"60 kundan oshgan qarz {ag['risk']:,.0f} so'm — bu barcha "
            f"kechikkanlarning {ag['risk_pct']:.0f}% i. Bunday qarzlar "
            f"odatda qaytmaydi, darhol ishlash kerak.")
    elif ag["total"]:
        add("warn", "Kechikkan to'lovlar bor",
            f"Jami {ag['total']:,.0f} so'm, {ag['count']} kishi — hammasi "
            f"60 kungacha, hali qaytarish oson.")

    # kassa zaxirasi
    if rw["months"] is not None:
        if rw["months"] < 3:
            add("bad", "Kassa zaxirasi kam",
                f"Hozirgi sur'atda pul {rw['months']:.1f} oyga yetadi. "
                f"Xavfsiz daraja — 3–6 oy.")
        else:
            add("warn", "Kassa kamayib bormoqda",
                f"Oxirgi 3 oyda o'rtacha oyiga {abs(rw['avg_net']):,.0f} so'm "
                f"kamaymoqda, zaxira {rw['months']:.1f} oyga yetadi.")

    # yo'nalishlar
    weak = [d for d in dirs if d["income"] and d["margin"] < 0]
    if weak:
        w = weak[0]
        add("bad", f"{w['name']} yo'nalishi zarar keltirmoqda",
            f"Tushum {w['income']:,.0f}, jamoa ish haqi {w['salary']:,.0f} — "
            f"marja {w['margin']:,.0f} so'm.")
    lead = dirs[0] if dirs and dirs[0]["income"] else None
    if lead and lead["share"] > 65:
        add("warn", "Bitta yo'nalishga bog'liqlik",
            f"{lead['name']} butun tushumning {lead['share']:.0f}% ini "
            f"beryapti — u susaysa, biznes butunlay tebranadi.")

    order = {"bad": 0, "warn": 1, "good": 2}
    out.sort(key=lambda x: order[x["kind"]])
    return out
