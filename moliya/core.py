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

import charts

from database import db
from models import (Budget, Cohort, Contract, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction, Wallet, dds_norm)


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


def wallet_cards(limit_tx=8):
    """Super-app kartalari: har hamyon uchun balans + oxirgi harakatlar."""
    balances, total = wallet_balances()
    cards = []
    for i, r in enumerate(balances):
        w = r["wallet"]
        txs = (Transaction.query
               .filter((Transaction.wallet_code == w.code) |
                       (Transaction.transfer_to_wallet == w.code))
               .order_by(Transaction.tdate.desc(), Transaction.id.desc())
               .limit(limit_tx).all())
        hist = []
        for t in txs:
            incoming = (t.operation == "kirim" or
                        (t.is_transfer and t.transfer_to_wallet == w.code))
            hist.append({
                "d": t.tdate.strftime("%d.%m"),
                "t": (t.counterparty or t.category or "—")[:34],
                "c": ("Perevod" if (t.is_transfer or t.activity == "tech")
                      else (t.category or ""))[:26],
                "a": t.amount, "in": bool(incoming),
            })
        low = w.name.lower()
        if w.code == "usd" or "$" in w.name:
            cur = "usd"                     # dollar hisobi
        elif w.code == "nal" or "налич" in low or "naqd" in low or "нал " in low:
            cur = "cash"                    # naqd pul — banknot dastasi
        else:
            cur = "card"                    # bank kartasi/hisobi — toza karta
        cards.append({"code": w.code, "name": w.name,
                      "balance": r["balance"], "grad": i % 6,
                      "cur": cur, "hist": hist})
    return {"cards": cards, "total": total}


# KPI/bonus uchun «sotuv» — faqat o'quvchi to'lovlari. Qarz, kredit, Б2Б,
# egа qo'ygan pul va «Мфактор поступления» bunga kirmaydi; aks holda ROP
# sotuv rejasi ham, foizli bonus bazasi ham shishib ketardi (masalan egа
# 200 mln qarz qo'ysa — reja bajarilgan ko'rinib, nohaq bonus chiqardi).
SALES_CATS = {
    "Поступление от клиента РОП",
    "Поступление от клиента СМК",
    "Поступление от клиента ТББ",
}


def sales_income(year, month):
    """Oylik sof sotuv tushumi — faqat o'quvchi (mijoz) to'lovlari."""
    q = (Transaction.query
         .filter(Transaction.operation == "kirim",
                 Transaction.is_transfer.is_(False),
                 Transaction.activity != "tech")
         .filter(func.extract("year", Transaction.tdate) == year)
         .filter(func.extract("month", Transaction.tdate) == month))
    return sum(t.amount for t in q if t.category in SALES_CATS)


def month_cashflow(year, month):
    """Oylik DDS: statya kesimida kirim/chiqim (transferlar hisobga olinmaydi)."""
    q = (Transaction.query
         .filter(Transaction.is_transfer.is_(False),
                 Transaction.activity != "tech")
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
        base = c.net_price - c.refund_amount
        # Qaytarilgan pul o'quvchida emas — u majburiyat ham, avans ham emas.
        # Grafikda «to'langan» bo'lib qolgani uchun uni chegirib tashlaymiz,
        # aks holda qaytarilgan summa abadiy «ishlanmagan avans» bo'lib turardi.
        paid = max(c.paid_total() - (c.refund_amount or 0.0), 0.0)
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
    q = Transaction.query.filter(Transaction.category == "Таргет (реклама)",
                                 Transaction.is_transfer.is_(False),
                                 Transaction.activity != "tech")
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
        # oqimga bog'liq to'g'ridan-to'g'ri xarajat: yo'nalish jamoasi
        # ish haqi + kofe-breyk + bitiruv (davr bo'yicha sodda taqsimot)
        from models import salary_cat_for_course
        direct_cats = ["Кофе-брейк", "Выпускные расходы"]
        sal = salary_cat_for_course(ch.course.name)
        if sal:
            direct_cats.append(sal)
        direct = (Transaction.query
                  .filter(Transaction.is_transfer.is_(False),
                          Transaction.operation == "chiqim",
                          Transaction.category.in_(direct_cats),
                          Transaction.tdate >= ch.start_date,
                          Transaction.tdate <= ch.end_date)
                  .with_entities(func.coalesce(func.sum(Transaction.amount), 0.0))
                  .scalar())
        margin = revenue - direct
        outstanding = sum(c.due_total() for c in active)
        n = len(active)
        rows.append({
            "cohort": ch, "students": n,
            "fill_rate": n / ch.capacity * 100 if ch.capacity else 0,
            "revenue": revenue, "paid": paid, "direct_cost": direct,
            "margin": margin,
            "margin_pct": margin / revenue * 100 if revenue else 0,
            "refunds": sum(c.refund_amount for c in contracts),
            # chuqur kesim: yig'ilish darajasi va 1 o'quvchi iqtisodi
            "paid_pct": paid / revenue * 100 if revenue else 0,
            "outstanding": outstanding,
            "arpu": revenue / n if n else 0,
            "margin_per_st": margin / n if n else 0,
        })
    return rows


# ══════════════════════════════════════════════════════════════════
#  BEP — zararsizlik nuqtasi
# ══════════════════════════════════════════════════════════════════
def break_even(year, month):
    """Oyiga nechta o'quvchi kerak: doimiy xarajat ÷ (o'rtacha chek marjasi)."""
    cf = month_cashflow(year, month)
    fixed_cats = ["Зарплата МБМ", "Аренда", "Коммунальные услуги",
                  "CRM OnlinePBX", "Интернет/IP-телефония",
                  "Абонентские подписки", "Обед сотрудников"]
    fixed = sum(cf["expense"].get(c, 0.0) for c in fixed_cats)
    # takrorlanuvchi to'lovlar rejasi ham doimiy hisoblanadi (fakt bo'lmasa)
    rec = sum(r.amount for r in RecurringPayment.query.filter_by(is_active=True))
    fixed = max(fixed, rec)
    ue = unit_economics(year, month)
    avg = ue["avg_check"]
    # o'zgaruvchan ulush: yo'nalish jamoalari ish haqi + premiya + komissiya +
    # kofe-breyk — tushumga bog'liq o'sadigan xarajatlar
    var_cats = ["Зарплата СМК", "Зарплата РОП", "Зарплата ТББ", "Премия",
                "Комиссия банка", "Кофе-брейк", "Выпускные расходы"]
    var = sum(cf["expense"].get(c, 0.0) for c in var_cats)
    inc = cf["income_total"]
    var_ratio = var / inc if inc else 0.3
    contribution = avg * (1 - var_ratio)
    need = (fixed / contribution) if contribution > 0 else None
    return {"fixed": fixed, "avg_check": avg, "var_ratio": var_ratio,
            "contribution": contribution, "students_needed": need}


# ══════════════════════════════════════════════════════════════════
#  YILLIK ДДС MATRITSASI — Mfaktor Sheets formati bilan 1:1
# ══════════════════════════════════════════════════════════════════
def dds_matrix(year):
    """Yillik ДДС: statya × 12 oy, oy boshi/oxiri qoldiqlari, % ulushi.

    Mfaktor jamoasi ko'nikkan «Отчет о движении денежных средств»
    formatini beradi: ustunlar — oylar, qatorlar — statyalar.
    """
    from models import INCOME_CATS, EXPENSE_CATS

    inc = {c: [0.0] * 12 for c in INCOME_CATS}
    exp = {c: [0.0] * 12 for c in EXPENSE_CATS}
    other_inc, other_exp = [0.0] * 12, [0.0] * 12
    fin = defaultdict(lambda: [0.0] * 12)     # Финансовая деятельность (dividend...)
    fin_net = [0.0] * 12

    year_txs = (Transaction.query
                .filter(Transaction.is_transfer.is_(False),
                 Transaction.activity != "tech")
                .filter(func.extract("year", Transaction.tdate) == year).all())
    for t in year_txs:
        i = t.tdate.month - 1
        if t.activity == "finance":
            sign = 1 if t.operation == "kirim" else -1
            fin[t.category or "Финансовая"][i] += sign * t.amount
            fin_net[i] += sign * t.amount
            continue
        if t.operation == "kirim":
            if t.category in inc:
                inc[t.category][i] += t.amount
            else:
                other_inc[i] += t.amount
        else:
            if t.category in exp:
                exp[t.category][i] += t.amount
            else:
                other_exp[i] += t.amount

    inc_tot = [sum(inc[c][i] for c in inc) + other_inc[i] for i in range(12)]
    exp_tot = [sum(exp[c][i] for c in exp) + other_exp[i] for i in range(12)]
    net = [inc_tot[i] - exp_tot[i] + fin_net[i] for i in range(12)]

    # yil boshigacha bo'lgan qoldiq: hamyon ochilishlari + avvalgi harakat
    opening_total = sum(w.opening for w in Wallet.query.all())
    prior = 0.0
    for t in Transaction.query.filter(Transaction.is_transfer.is_(False),
                 Transaction.activity != "tech") \
            .filter(Transaction.tdate < date(year, 1, 1)).all():
        prior += t.amount if t.operation == "kirim" else -t.amount
    start = opening_total + prior
    opens, closes = [], []
    bal = start
    for i in range(12):
        opens.append(bal)
        bal += net[i]
        closes.append(bal)

    inc_year_total = sum(inc_tot) or 1.0
    rows_inc = [{"cat": c, "vals": inc[c], "total": sum(inc[c]),
                 "pct": sum(inc[c]) / inc_year_total * 100,
                 "spark": charts.sparkline(inc[c])}
                for c in INCOME_CATS if any(inc[c])]
    rows_exp = [{"cat": c, "vals": exp[c], "total": sum(exp[c]),
                 "pct": sum(exp[c]) / inc_year_total * 100,
                 "spark": charts.sparkline(exp[c])}
                for c in EXPENSE_CATS if any(exp[c])]
    rows_fin = [{"cat": c, "vals": v, "total": sum(v)}
                for c, v in sorted(fin.items())]
    return {
        "year": year, "opens": opens, "closes": closes,
        "rows_inc": rows_inc, "rows_exp": rows_exp, "rows_fin": rows_fin,
        "other_inc": other_inc, "other_exp": other_exp,
        "inc_tot": inc_tot, "exp_tot": exp_tot, "net": net,
        "fin_net": fin_net, "fin_year": sum(fin_net),
        "inc_year": sum(inc_tot), "exp_year": sum(exp_tot),
        "net_year": sum(net),
    }


# ══════════════════════════════════════════════════════════════════
#  «ДДС_2026» — Excel varag'ining 1:1 nusxasi
# ══════════════════════════════════════════════════════════════════
# Sheets'dagi hamyon tartibi va yozuvlari (Остаток qatorlarida shunday turadi)
DDS_XL_WALLETS = [
    ("РС MBM", "р.с МБМ", "rs_mbm"),
    ("Наличные", "накт сум", "nal"),
    (" РС DAVR BANK MBM", "р.с МБМ Davr bank", "davr_mbm"),
    ("$", "$", "usd"),
    ("UZCARD 2406", "карта 2406", "uzcard2406"),
    ("PC MFAKTOR", "PC Mfaktor", "rs_mfaktor"),
    ("MFAKTOR karta", "карта MFAKTOR", "karta_mfaktor"),
]
_XL_TRANSFER_IN = "Доход — Перевод между счетами"
_XL_TRANSFER_OUT = "Расход — Перевод между счетами"


def dds_excel(year):
    """«ДДС_2026» varag'i bilan bir xil tuzilma: to'g'ridan-to'g'ri
    «ДДС данные» (DdsRow) ustida hisoblanadi — Sheets formulalari kabi.
    """
    from models import DdsRow, DDS_SPRAVOCHNIK, Wallet as _W

    rows = [r for r in DdsRow.query.all() if r.ddate and r.ddate.year == year]

    def msum(pred):
        v = [0.0] * 12
        for r in rows:
            if pred(r):
                v[r.ddate.month - 1] += r.amount
        return v

    # ── modda bloklari: faoliyat × yo'nalish (Sheets'dagi FILTER kabi) ──
    def block(activity, flow):
        arts = [a for a, g, v in DDS_SPRAVOCHNIK
                if v == activity and g == flow
                and a not in (_XL_TRANSFER_IN, _XL_TRANSFER_OUT)]
        out = []
        for a in arts:
            # Statya nomi bo'shliq/registr bilan farq qilishi mumkin (Excel
            # spravochnigida " Поступление Б2Б" kabi kalitlar bor, sayt
            # formasi esa bo'shliqsiz yuboradi) — normallashtirib solishtiramiz,
            # aks holda qator hech bir blokka tushmay, hisobotdan yo'qolardi.
            na = dds_norm(a)
            vals = msum(lambda r, na=na: dds_norm(r.article) == na)
            if any(vals):
                out.append({"name": a.strip(), "vals": vals, "total": sum(vals)})
        sub = [sum(x["vals"][i] for x in out) for i in range(12)]
        return out, sub

    op_in, op_in_t = block("Операционная", "Поступление")
    op_out, op_out_t = block("Операционная", "Выбытие")
    inv_in, inv_in_t = block("Инвестиционная", "Поступление")
    inv_out, inv_out_t = block("Инвестиционная", "Выбытие")
    fin_in, fin_in_t = block("Финансовая", "Поступление")
    fin_out, fin_out_t = block("Финансовая", "Выбытие")
    tr_in = msum(lambda r: dds_norm(r.article) == dds_norm(_XL_TRANSFER_IN))
    tr_out = msum(lambda r: dds_norm(r.article) == dds_norm(_XL_TRANSFER_OUT))

    # ── hamyonlar bo'yicha oylik qoldiqlar (perevodlar bilan birga) ──
    opening0 = {}
    for dds_name, label, code in DDS_XL_WALLETS:
        w = _W.query.filter_by(code=code).first()
        opening0[dds_name] = w.opening if w else 0.0
    # yil boshigacha bo'lgan harakat ham qoldiqqa kiradi
    for r in DdsRow.query.all():
        if r.ddate and r.ddate.year < year and r.wallet in opening0:
            opening0[r.wallet] += r.amount if r.flow == "Поступление" else -r.amount

    delta = {n: [0.0] * 12 for n, _, _ in DDS_XL_WALLETS}
    for r in rows:
        if r.wallet in delta:
            m = r.ddate.month - 1
            delta[r.wallet][m] += r.amount if r.flow == "Поступление" else -r.amount

    wal_open, wal_close = {}, {}
    for n, _, _ in DDS_XL_WALLETS:
        o, c, bal = [], [], opening0[n]
        for i in range(12):
            o.append(bal)
            bal += delta[n][i]
            c.append(bal)
        wal_open[n], wal_close[n] = o, c

    open_tot = [sum(wal_open[n][i] for n, _, _ in DDS_XL_WALLETS) for i in range(12)]
    close_tot = [sum(wal_close[n][i] for n, _, _ in DDS_XL_WALLETS) for i in range(12)]
    # ЧДП — oy davomidagi jami harakat (barcha qatorlar, perevod bilan)
    chdp = [close_tot[i] - open_tot[i] for i in range(12)]
    # Разница — nazorat: ЧДП == modda bloklari + perevod farqi bo'lishi shart
    flows = [op_in_t[i] - op_out_t[i] + inv_in_t[i] - inv_out_t[i]
             + fin_in_t[i] - fin_out_t[i] + tr_in[i] - tr_out[i]
             for i in range(12)]
    razn = [chdp[i] - flows[i] for i in range(12)]

    tot = lambda v: sum(v)
    return {
        "year": year, "months": ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                                 "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"],
        "wallets": [(label, wal_open[n], wal_close[n])
                    for n, label, _ in DDS_XL_WALLETS],
        "open_tot": open_tot, "close_tot": close_tot,
        "op_in": op_in, "op_in_t": op_in_t, "op_out": op_out, "op_out_t": op_out_t,
        "inv_in": inv_in, "inv_in_t": inv_in_t, "inv_out": inv_out,
        "inv_out_t": inv_out_t,
        "fin_in": fin_in, "fin_in_t": fin_in_t, "fin_out": fin_out,
        "fin_out_t": fin_out_t,
        "tr_in": tr_in, "tr_out": tr_out,
        "chdp": chdp, "razn": razn,
        "ok": all(abs(x) < 1 for x in razn),
    }


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
    dm = dds_matrix(y)
    series = [{"m": i + 1, "inc": dm["inc_tot"][i], "exp": dm["exp_tot"][i]}
              for i in range(m)]
    # o'tgan oy bilan taqqoslash (KPI kartochkalardagi ▲/▼ uchun)
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    prev = month_cashflow(py, pm)

    # xarajatlar tarkibi (donut) — yil boshidan, top-5 statya
    exp_rows = sorted([(r["cat"], r["total"]) for r in dm["rows_exp"]],
                      key=lambda x: -x[1])
    exp_total_year = sum(v for _, v in exp_rows) or 1.0
    top5 = exp_rows[:5]
    other = exp_total_year - sum(v for _, v in top5)
    exp_top = [{"cat": cat, "val": v, "pct": v / exp_total_year * 100}
               for cat, v in top5]
    if other > 0:
        exp_top.append({"cat": "Boshqa", "val": other,
                        "pct": other / exp_total_year * 100})

    # ── Diagrammalar ──
    MN = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn",
          "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
    chart_main = charts.line_area(
        [{"key": "inc", "name": "Tushum", "values": dm["inc_tot"][:m]},
         {"key": "exp", "name": "Xarajat", "values": dm["exp_tot"][:m]}],
        MN[:m])
    wf = charts.waterfall([
        {"name": "Yil boshi", "value": dm["opens"][0], "kind": "start"},
        {"name": "Tushum", "value": sum(dm["inc_tot"]), "kind": "plus"},
        {"name": "Xarajat", "value": sum(dm["exp_tot"]), "kind": "minus"},
        {"name": "Dividend", "value": abs(dm["fin_year"]), "kind": "minus"},
        {"name": "Hozir", "value": dm["closes"][m - 1], "kind": "end"},
    ])
    rank = charts.rank_bars([{"cat": r["cat"], "val": r["total"]}
                             for r in dm["rows_exp"]])

    def delta(cur, old):
        if not old:
            return None
        return (cur - old) / abs(old) * 100
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
        "delta_inc": delta(cf["income_total"], prev["income_total"]),
        "delta_exp": delta(cf["expense_total"], prev["expense_total"]),
        "exp_top": exp_top,
        "chart_main": chart_main, "wf": wf, "rank": rank,
        # ECharts uchun xom qatorlar (wow-grafiklar)
        "ech": {
            "months": MN[:m],
            "inc": [round(v) for v in dm["inc_tot"][:m]],
            "exp": [round(v) for v in dm["exp_tot"][:m]],
            "wf": [
                {"name": "Yil boshi", "value": round(dm["opens"][0]), "kind": "start"},
                {"name": "Tushum", "value": round(sum(dm["inc_tot"])), "kind": "plus"},
                {"name": "Xarajat", "value": round(sum(dm["exp_tot"])), "kind": "minus"},
                {"name": "Dividend", "value": round(abs(dm["fin_year"])), "kind": "minus"},
                {"name": "Hozir", "value": round(dm["closes"][m - 1]), "kind": "end"},
            ],
        },
        "wcards": wallet_cards(),
        "series": series,
        "series_max": max([max(r["inc"], r["exp"]) for r in series] or [1]) or 1,
        "active_contracts": Contract.query.filter_by(status="active").count(),
        "students": Student.query.count(),
    }


# ══════════════════════════════════════════════════════════════════
#  SHARTNOMALAR TAXTASI — oqim kartochkalari va ichidagi o'quvchilar
# ══════════════════════════════════════════════════════════════════
def contracts_board(status="active", today=None):
    """Har oqim uchun bitta kartochka + ichida o'quvchi kartochkalari.

    Jadval o'rniga ko'z bilan o'qiladigan ko'rinish: oqimning to'ldirilishi,
    puli va qarzi bir qarashda; ochilganda har o'quvchining to'lov holati,
    keyingi muddati va kechikishi ko'rinadi.
    """
    today = today or date.today()
    out = []
    for ch in (Cohort.query.order_by(Cohort.start_date.desc()).all()):
        q = Contract.query.filter_by(cohort_id=ch.id)
        if status != "all":
            q = q.filter_by(status=status)
        contracts = q.order_by(Contract.signed_date.desc()).all()

        students, c_paid, c_price, c_due, c_over, over_n = [], 0.0, 0.0, 0.0, 0.0, 0
        for c in contracts:
            price = c.net_price - (c.refund_amount or 0.0)
            paid = c.paid_total()
            due = c.due_total()
            # keyingi muddat va kechikish
            nxt, overdue_amt, overdue_days = None, 0.0, 0
            for l in c.lines:
                rest = max(l.amount - l.paid, 0.0)
                if rest <= 0.01:
                    continue
                if l.due_date < today:
                    overdue_amt += rest
                    overdue_days = max(overdue_days, (today - l.due_date).days)
                elif nxt is None or l.due_date < nxt["date"]:
                    nxt = {"date": l.due_date, "amount": rest,
                           "days": (l.due_date - today).days}
            students.append({
                "c": c, "name": c.student.name, "phone": c.student.phone,
                "source": c.student.source,
                "price": price, "paid": paid, "due": due,
                "pct": (paid / price * 100) if price > 0 else 0,
                "next": nxt, "overdue": overdue_amt, "overdue_days": overdue_days,
                "installments": len(c.lines),
                "done": len([l for l in c.lines if l.paid >= l.amount - 0.01]),
            })
            c_price += price
            c_paid += paid
            c_due += due
            if overdue_amt > 0:
                c_over += overdue_amt
                over_n += 1

        # eng muammolisi yuqorida: avval kechikkanlar, keyin qarzi ko'plar
        students.sort(key=lambda s: (-s["overdue"], -s["due"]))

        n = len(students)
        # oqim bosqichi
        if today < ch.start_date:
            phase, phase_label = "soon", "Boshlanmagan"
            progress = 0
        elif today > ch.end_date:
            phase, phase_label = "done", "Tugagan"
            progress = 100
        else:
            phase, phase_label = "live", "Davom etmoqda"
            progress = (today - ch.start_date).days / ch.duration_days() * 100
        out.append({
            "cohort": ch, "students": students, "count": n,
            "demo": "[namuna]" in (ch.name or ""),
            "capacity": ch.capacity or 0,
            "fill": (n / ch.capacity * 100) if ch.capacity else 0,
            "price": c_price, "paid": c_paid, "due": c_due,
            "paid_pct": (c_paid / c_price * 100) if c_price > 0 else 0,
            "overdue": c_over, "overdue_n": over_n,
            "phase": phase, "phase_label": phase_label,
            "progress": min(max(progress, 0), 100),
        })
    # Tartib: avval davom etayotganlar, keyin boshlanmaganlar, oxirida
    # tugaganlar; bo'sh oqimlar esa eng oxirida.
    rank = {"live": 0, "soon": 1, "done": 2}
    out.sort(key=lambda r: (r["count"] == 0, rank.get(r["phase"], 3),
                            -r["cohort"].start_date.toordinal()))
    return out
