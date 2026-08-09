"""Chuqur tahlil qatlami — boshqaruv hisobotlari.

Bu modul moliyaviy ma'lumotni "raqamlar" darajasidan "qarorlar" darajasiga
ko'taradi: P&L tuzilmasi, trend va prognoz, yo'nalishlar rentabelligi,
qarzdorlik yoshi, qaytarishlar tahlili va avtomatik xulosalar.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

import core
from models import (Contract, Cohort, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction)

def _n(v):
    """Raqamni bo'shliq bilan ajratib formatlash: 1 234 567."""
    try:
        return f"{float(v):,.0f}".replace(",", "\u00a0")
    except (TypeError, ValueError):
        return str(v)


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

    # joriy tugallanmagan oy prognoz bazasini buzmasin: oy hali oxirlamagan
    # bo'lsa, uning qisman raqamlari o'rtacha hisobidan chiqariladi
    today = date.today()
    partial = (year == today.year and month == today.month and today.day < 28)
    base_hist = hist[:-1] if (partial and len(hist) > 1) else hist

    def _forecast(key):
        """Daraja = oxirgi 6 oy o'rtachasi (bitta sakragan oy hukmron bo'lmasin),
        yo'nalish = oxirgi 3 oy / avvalgi 3 oy, so'nuvchi sur'at bilan.
        Oddiy murakkab foiz 6 oyga cho'zilsa, bitta g'ayrioddiy oy butun
        prognozni buzadi — shuning uchun sur'at har oy so'nib boradi."""
        vals = [h[key] for h in base_hist if h[key]]
        if len(vals) < 3:
            return [round(vals[-1]) if vals else 0] * ahead
        level = sum(vals[-6:]) / len(vals[-6:])
        cur3 = sum(vals[-3:]) / 3
        # yo'nalish: so'nggi choraq yarim yillik normadan qanchaga og'gan.
        # (3-oy vs 3-oy taqqoslash bitta anomal oy tufayli qarama-qarshi
        # "qaychi" hosil qilardi — norma bilan taqqoslash barqarorroq)
        g = (cur3 / level) if level > 0 else 1.0
        g = max(0.93, min(g, 1.07))          # ekstremal sur'atni cheklash
        out, cur, damp = [], level, 1.0
        for _ in range(ahead):
            cur *= g ** damp
            damp *= 0.5                      # sur'at har oy ikki barobar so'nadi
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


def _months_ahead(year, month, n):
    """Keyingi n oy ro'yxati (joriy oydan keyin)."""
    out = []
    y, m = year, month
    for _ in range(n):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((y, m))
    return out


def collection_rate(days=90, today=None):
    """Grafik to'lovlarining amalda yig'ilish darajasi (0..1).

    Oxirgi `days` kunda muddati kelgan bo'lib-to'lash qatorlari bo'yicha:
    qancha so'ralgan bo'lsa, shuncha necha foizi haqiqatda tushgan.
    Shartnoma ma'lumoti hali yo'q bo'lsa None qaytadi.
    """
    today = today or date.today()
    since = today - timedelta(days=days)
    lines = (InstallmentLine.query.join(Contract)
             .filter(Contract.status == "active",
                     InstallmentLine.due_date >= since,
                     InstallmentLine.due_date <= today)
             .all())
    due = sum(l.amount for l in lines)
    paid = sum(min(l.paid, l.amount) for l in lines)
    return (paid / due) if due else None


def cash_forecast(year, month, ahead=6):
    """Kassa balansi prognozi — `ahead` oy oldinga, uch stsenariy.

    Ikki mustaqil manba birlashtiriladi:
      • statistik — oxirgi oylar kirim/chiqim sur'ati (trend bilan bir usul);
      • shartnomaviy — InstallmentLine grafigi bo'yicha kutilayotgan
        to'lovlar, tarixiy yig'ilish darajasi bilan tuzatilgan.
    Qisqa muddatda grafik aniqroq, shuning uchun bazaviy kirim sifatida
    ikkalasining kattasi olinadi (grafik statistikaning bir qismi, qo'shib
    yuborilsa ikki marta hisoblangan bo'lardi).
    """
    _rows, cash = core.wallet_balances()
    # prognoz har doim "bugundan" boshlanadi: kassa qoldig'i bugungi holat,
    # shuning uchun statistika oxirgi TO'LIQ oyga bog'lanadi va joriy oyning
    # qolgan kunlari ulush sifatida qo'shiladi
    today = date.today()
    ty, tm = today.year, today.month
    ay, am = (ty - 1, 12) if tm == 1 else (ty, tm - 1)
    tr = trend(ay, am, back=12, ahead=ahead + 1)
    cur_inc, cur_exp = tr["next_inc"][0], tr["next_exp"][0]   # joriy oy bahosi
    stat_inc, stat_exp = tr["next_inc"][1:], tr["next_exp"][1:]
    dim = calendar.monthrange(ty, tm)[1]
    frac = max(dim - today.day, 0) / dim                       # oyning qolgan qismi

    months = _months_ahead(ty, tm, ahead)
    labels = [f"{MN[m]} {str(y)[2:]}" for y, m in months]

    # Shartnoma grafigi: oyma-oy kutilayotgan (hali to'lanmagan) summalar.
    # Hisob BUGUNDAN boshlanadi — shu oyning qolgan kunlaridagi to'lovlar
    # hech qayerda hisobga olinmay qolmasligi uchun ular alohida yig'iladi.
    sched = [0.0] * ahead
    cur_sched = 0.0
    lines = (InstallmentLine.query.join(Contract)
             .filter(Contract.status == "active",
                     InstallmentLine.due_date >= today)
             .all())
    idx = {ym: i for i, ym in enumerate(months)}
    for l in lines:
        rest = max(l.amount - l.paid, 0.0)
        if not rest:
            continue
        i = idx.get((l.due_date.year, l.due_date.month))
        if i is not None:
            sched[i] += rest
        elif (l.due_date.year, l.due_date.month) == (ty, tm):
            cur_sched += rest              # shu oyning qolgan kunlari
    # muddati allaqachon o'tgan, ammo to'lanmagan qarzlar
    overdue_rest = sum(r["rest"] for r in core.overdue_lines())
    rate = collection_rate()
    rate_eff = rate if rate is not None else 0.85
    sched_adj = [s * rate_eff for s in sched]
    # Eski qarzning bir qismi qaytadi deb ehtiyotkor baholaymiz. Bu — odatdagi
    # aylanmadan tashqaridagi bir martalik tushum, shuning uchun statistik
    # sur'at bilan solishtirilmaydi, ustiga qo'shiladi.
    overdue_gain = overdue_rest * min(rate_eff, 0.5)

    # stsenariylar: kirim/chiqim koeffitsiyentlari
    scen = {"pes": (0.85, 1.05), "base": (1.0, 1.0), "opt": (1.10, 0.97)}
    bal = {}
    for key, (ki, ke) in scen.items():
        # joriy oyning qolgan kunlaridagi kutilayotgan oqim
        cur = cash + (max(cur_inc * frac, cur_sched * rate_eff) * ki
                      - cur_exp * frac * ke)
        path = []
        for i in range(ahead):
            inc = max(stat_inc[i], sched_adj[i]) * ki
            if i == 0:
                inc += overdue_gain * ki
            cur += inc - stat_exp[i] * ke
            path.append(round(cur))
        bal[key] = path

    def _zero_cross(path):
        for i, v in enumerate(path):
            if v < 0:
                return labels[i]
        return None

    return {
        "labels": labels, "cash": round(cash),
        "sched": [round(s) for s in sched],
        "sched_total": round(sum(sched) + cur_sched),
        "cur_sched": round(cur_sched),
        "overdue_rest": round(overdue_rest),
        "overdue_gain": round(overdue_gain),
        "rate": rate,                      # None — shartnoma ma'lumoti yo'q
        "stat_inc": stat_inc, "stat_exp": stat_exp,
        "bal": bal,
        "zero": {k: _zero_cross(p) for k, p in bal.items()},
        "end": {k: p[-1] for k, p in bal.items()},
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
            f"Operatsion natija {_n(p['op'])} so'm. Doimiy xarajat "
            f"{_n(p['fixed'])} so'm — bu tushumning "
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
                f"1 o'quvchi {_n(ue['cac'])} so'mga tushmoqda.")
        else:
            add("good", "Marketing samarali",
                f"LTV/CAC = {ue['ltv_cac']:.1f} — 1 so'm reklama "
                f"{ue['ltv_cac']:.1f} so'm qiymat keltirmoqda.")
    elif ue["marketing_spend"] and not ue["new_students"]:
        add("bad", "Reklama pul yemoqda, natija yo'q",
            f"Bu oy {_n(ue['marketing_spend'])} so'm sarflandi, yangi "
            f"shartnoma esa yo'q.")

    # qarzdorlik
    if ag["risk"] > 0:
        add("bad" if ag["risk_pct"] > 40 else "warn", "Eski qarzlar xavfi",
            f"60 kundan oshgan qarz {_n(ag['risk'])} so'm — bu barcha "
            f"kechikkanlarning {ag['risk_pct']:.0f}% i. Bunday qarzlar "
            f"odatda qaytmaydi, darhol ishlash kerak.")
    elif ag["total"]:
        add("warn", "Kechikkan to'lovlar bor",
            f"Jami {_n(ag['total'])} so'm, {ag['count']} kishi — hammasi "
            f"60 kungacha, hali qaytarish oson.")

    # kassa zaxirasi
    if rw["months"] is not None:
        if rw["months"] < 3:
            add("bad", "Kassa zaxirasi kam",
                f"Hozirgi sur'atda pul {rw['months']:.1f} oyga yetadi. "
                f"Xavfsiz daraja — 3–6 oy.")
        else:
            add("warn", "Kassa kamayib bormoqda",
                f"Oxirgi 3 oyda o'rtacha oyiga {_n(abs(rw['avg_net']))} so'm "
                f"kamaymoqda, zaxira {rw['months']:.1f} oyga yetadi.")

    # kassa prognozi — stsenariylar bo'yicha ogohlantirish
    cast = cash_forecast(year, month)
    if cast["zero"]["base"]:
        add("bad", "Prognoz: kassa manfiyga o'tadi",
            f"Bazaviy stsenariyda balans {cast['zero']['base']} oyida noldan "
            f"pastga tushadi. Xarajatni qisqartirish yoki tushumni tezlashtirish "
            f"rejasi hoziroq kerak.")
    elif cast["zero"]["pes"]:
        add("warn", "Ehtiyot stsenariyda kassa yetmasligi mumkin",
            f"Tushum 15% pasaysa, balans {cast['zero']['pes']} oyida manfiy "
            f"bo'ladi. Zaxira rejani tayyorlab qo'ygan ma'qul.")
    if cast["overdue_rest"] > 0:
        add("warn", "Muddati o'tgan qarzlar prognozga ta'sir qilmoqda",
            f"Jami {_n(cast['overdue_rest'])} so'm kechikkan. Prognozda uning "
            f"faqat {_n(cast['overdue_gain'])} so'mi qaytadi deb olingan — "
            f"to'liq undirilsa, balans yana {_n(cast['overdue_rest'] - cast['overdue_gain'])} "
            f"so'mga yaxshilanadi.")

    # yo'nalishlar
    weak = [d for d in dirs if d["income"] and d["margin"] < 0]
    if weak:
        w = weak[0]
        add("bad", f"{w['name']} yo'nalishi zarar keltirmoqda",
            f"Tushum {_n(w['income'])}, jamoa ish haqi {_n(w['salary'])} — "
            f"marja {_n(w['margin'])} so'm.")
    lead = dirs[0] if dirs and dirs[0]["income"] else None
    if lead and lead["share"] > 65:
        add("warn", "Bitta yo'nalishga bog'liqlik",
            f"{lead['name']} butun tushumning {lead['share']:.0f}% ini "
            f"beryapti — u susaysa, biznes butunlay tebranadi.")

    order = {"bad": 0, "warn": 1, "good": 2}
    out.sort(key=lambda x: order[x["kind"]])
    return out
