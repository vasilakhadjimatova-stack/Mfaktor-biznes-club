"""Hisobvaraqlar orasidagi o'tkazmalarni juftlash va juftsizlarini topish.

Muammo nimadan kelib chiqadi
════════════════════════════
ДДС da bitta o'tkazma IKKITA qator bilan yoziladi:

    «Расход — Перевод между счетами»   A hamyondan chiqdi
    «Доход  — Перевод между счетами»   B hamyonga kirdi

Ikkinchi qator yozilmay qolsa, pul A dan chiqib hech qayerga kirmaydi —
natijada hamyon qoldig'i kamayib ketadi va MANFIY bo'lib qolishi mumkin.
Naqd pul manfiy bo'lolmaydi, ya'ni bu har doim ma'lumot xatosi.

Muhim: bu foyda hisobotiga TA'SIR QILMAYDI — u yerda o'tkazmalar
`activity='tech'` bo'yicha allaqachon chiqarib tashlangan. Buziladigan
narsa — faqat hamyon qoldig'i.

Juftlash nega oddiy tenglik bilan bo'lmaydi
═══════════════════════════════════════════
Haqiqiy o'tkazmalarda summa ikki tomonda bir xil bo'lmaydi:
  • bank komissiyasi ushlab qolinadi (10 mln → 9.9 mln);
  • valyuta ayirboshlashda («obmen») kurs farqi bo'ladi;
  • bitta chiqim ikkita kirimga bo'linib tushadi (11 mln → 6 + 5);
  • ba'zan 1 so'mlik yaxlitlash farqi bo'ladi.

Shuning uchun juftlash uch bosqichda, qat'iydan bo'shroqqa qarab boradi —
aniq mos kelganlar avval band qilinadi, qolganiga yon beriladi.
"""
from datetime import timedelta
from itertools import combinations

from database import db
from models import DdsRow, Transaction, Wallet

OUT_ART = "Расход — Перевод между счетами"
IN_ART = "Доход — Перевод между счетами"

DAY_WINDOW = 3          # juft sana bo'yicha shuncha kun ichida qidiriladi
PCT_TOL = 0.015         # summa farqi: 1.5% gacha (komissiya/kurs farqi)
ABS_TOL = 5_000         # yoki shuncha so'mgacha (yaxlitlash)


def _tol(amount):
    return max(amount * PCT_TOL, ABS_TOL)


def _near(a, b):
    return abs((a.ddate - b.ddate).days) <= DAY_WINDOW


def transfer_rows():
    """Barcha o'tkazma qatorlari: (chiqimlar, kirimlar)."""
    outs = (DdsRow.query.filter(DdsRow.article == OUT_ART)
            .order_by(DdsRow.ddate, DdsRow.rownum).all())
    ins = (DdsRow.query.filter(DdsRow.article == IN_ART)
           .order_by(DdsRow.ddate, DdsRow.rownum).all())
    return outs, ins


def pair_transfers():
    """O'tkazmalarni juftlaydi.

    Qaytaradi: (juftlar, juftsiz_chiqimlar, juftsiz_kirimlar)
    Har juft — {"out": [...], "in": [...], "diff": farq, "why": sabab}
    """
    outs, ins = transfer_rows()
    used = set()
    pairs = []

    def take(o_rows, i_rows, why):
        used.update(r.id for r in o_rows + i_rows)
        so = sum(r.amount for r in o_rows)
        si = sum(r.amount for r in i_rows)
        pairs.append({"out": o_rows, "in": i_rows, "diff": so - si, "why": why})

    # 1-bosqich: aniq mos kelganlar (avval ular band qilinsin)
    for o in outs:
        if o.id in used:
            continue
        m = next((r for r in ins if r.id not in used and _near(r, o)
                  and abs(r.amount - o.amount) < 1), None)
        if m:
            take([o], [m], "aniq")

    # 2-bosqich: komissiya / kurs farqi bilan
    for o in outs:
        if o.id in used:
            continue
        best = None
        for r in ins:
            if r.id in used or not _near(r, o):
                continue
            d = abs(r.amount - o.amount)
            if d <= _tol(o.amount) and (best is None
                                        or d < abs(best.amount - o.amount)):
                best = r
        if best:
            take([o], [best], "farq bilan")

    # 3-bosqich: bo'lib yuborilgan (1 ↔ 2)
    for src, is_out in ((outs, True), (ins, False)):
        for o in src:
            if o.id in used:
                continue
            other = ins if is_out else outs
            cands = [r for r in other if r.id not in used and _near(r, o)]
            hit = next((c for c in combinations(cands, 2)
                        if abs(c[0].amount + c[1].amount - o.amount)
                        <= _tol(o.amount)), None)
            if hit:
                take([o] if is_out else list(hit),
                     list(hit) if is_out else [o], "bo'lingan")

    lone_out = [r for r in outs if r.id not in used]
    lone_in = [r for r in ins if r.id not in used]
    return pairs, lone_out, lone_in


def negative_wallets():
    """Qoldig'i manfiy bo'lib qolgan hamyonlar — har doim xato belgisi."""
    import core
    rows, _ = core.wallet_balances()
    return [r for r in rows if r["balance"] < 0]


def report():
    """«Juftlanmagan o'tkazmalar» sahifasi uchun to'liq ma'lumot."""
    pairs, lone_out, lone_in = pair_transfers()
    outs, ins = transfer_rows()
    s_out = sum(r.amount for r in lone_out)
    s_in = sum(r.amount for r in lone_in)

    # Juftsiz qatorlarni sana bo'yicha bitta ro'yxatga qo'shamiz — buxgalter
    # yonma-yon ko'rib, qaysi biri qaysiga tegishli ekanini o'zi topadi.
    # DIQQAT: kalit «rows» — «items» bo'lsa Jinja uni dict.items() metodi
    # deb o'qiydi va sahifa ishlamay qoladi.
    rows = ([{"row": r, "dir": "out"} for r in lone_out]
            + [{"row": r, "dir": "in"} for r in lone_in])
    rows.sort(key=lambda x: (x["row"].ddate, x["row"].rownum))
    for it in rows:
        it["near"] = _suggestions(it["row"], it["dir"], lone_in, lone_out)

    return {
        "rows": rows,
        "n_pairs": len(pairs),
        "n_rows": len(outs) + len(ins),
        "lone_out": lone_out, "lone_in": lone_in,
        "sum_out": s_out, "sum_in": s_in,
        "gap": s_out - s_in,
        "negatives": negative_wallets(),
    }


def _suggestions(row, direction, lone_in, lone_out, limit=3):
    """Shu qatorga eng yaqin nomzodlar — buxgalterga taklif sifatida.

    Qat'iy juftlash topa olmagan bo'lsa ham, oyna kengaytirilib (30 kun,
    30% farq) eng ehtimolli qatorlar ko'rsatiladi. Bu avtomatik BOG'LAMAYDI
    — faqat «shu bo'lishi mumkin» deb ko'rsatadi.
    """
    pool = lone_in if direction == "out" else lone_out
    out = []
    for r in pool:
        dd = abs((r.ddate - row.ddate).days)
        if dd > 30:
            continue
        big = max(row.amount, r.amount) or 1
        gap = abs(r.amount - row.amount) / big
        if gap > 0.30:
            continue
        out.append((dd + gap * 100, r))
    out.sort(key=lambda x: x[0])
    return [r for _, r in out[:limit]]


def add_counterpart(row, wallet, amount=None, ddate=None, purpose=None):
    """Tushib qolgan qarama-qarshi ДДС qatorini qo'shadi.

    ДДС — yagona manba, shuning uchun kassa yozuvi qo'lda yaratilmaydi:
    qator qo'shiladi, `ddsflow.sync_row` uni o'zi kassaga o'tkazadi va
    hamyon qoldig'i shu zahoti tuzaladi.
    """
    import ddsflow

    if row.article not in (OUT_ART, IN_ART):
        return None, "Bu qator o'tkazma emas"
    if not wallet:
        return None, "Hamyonni tanlang"
    opposite = IN_ART if row.article == OUT_ART else OUT_ART
    last = db.session.query(db.func.max(DdsRow.rownum)).scalar() or 2
    new = DdsRow(rownum=last + 1,
                 ddate=ddate or row.ddate,
                 amount=amount if amount is not None else row.amount,
                 wallet=wallet,
                 wallet2="",
                 purpose=purpose or (row.purpose or ""),
                 article=opposite)
    db.session.add(new)
    db.session.flush()
    tx = ddsflow.sync_row(new)
    if tx is None:
        db.session.delete(new)
        _, why = ddsflow.check_row(new)
        return None, f"Kassaga tushmadi: {why}"
    db.session.commit()
    return new, ""


def wallet_names():
    """ДДС da yoziladigan hamyon nomlari (qator uchun matn ko'rinishida)."""
    seen, out = set(), []
    for (w,) in db.session.query(DdsRow.wallet).distinct().all():
        w = (w or "").strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return sorted(out)
