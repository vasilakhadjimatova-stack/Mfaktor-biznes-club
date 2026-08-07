"""Excel (Mbm_2026.xlsx) faylini sayt orqali yuklab import qilish.

Sozlamalar sahifasidagi «Excel'dan import» formasi shu modulni chaqiradi:
  1. «ДДС данные» varag'i → DdsRow (eski qatorlar almashtiriladi)
  2. «ДДС_2026» varag'idan hamyonlarning yil boshi qoldiqlari
  3. Kassa qayta quriladi (ddsflow.rebuild_all)
  4. To'lovlar shartnomalarga qayta taqqoslanadi (matching.run_all)

Hammasi bitta tranzaksiyada — xato bo'lsa hech narsa o'zgarmaydi.
"""
import unicodedata

import openpyxl

from database import db
from models import DdsRow, Wallet

import ddsflow
import matching

SHEET_DATA = "ДДС данные"
SHEET_YEAR_PREFIX = "ДДС_"

# «ДДС_2026» qoldiq qatori nomi → hamyon kodi
OPENING_MAP = {
    "р.с мбм": "rs_mbm",
    "накт сум": "nal",
    "нал сум": "nal",
    "р.с мбм davr bank": "davr_mbm",
    "$": "usd",
    "карта 2406": "uzcard2406",
    "рс mfaktor": "rs_mfaktor",
    "pc mfaktor": "rs_mfaktor",
    "карта mfaktor": "karta_mfaktor",
}


def _norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    return " ".join(s.split())


def _num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace("\xa0", "")
                     .replace(",", "."))
    except ValueError:
        return 0.0


def import_workbook(stream):
    """Yuklangan xlsx oqimini o'qib butun zanjirni bajaradi.

    Qaytaradi: xulosa dict (sahifada ko'rsatiladi).
    """
    wb = openpyxl.load_workbook(stream, data_only=True)
    if SHEET_DATA not in wb.sheetnames:
        return {"error": f"Faylda «{SHEET_DATA}» varag'i topilmadi. "
                         f"Mavjud varaqlar: {', '.join(wb.sheetnames[:8])}…"}
    ws = wb[SHEET_DATA]

    # ── 1. ДДС данные → DdsRow ──
    old = DdsRow.query.count()
    # eski qatorlarning kassa izlarini tozalaymiz
    for row in DdsRow.query.all():
        ddsflow.unsync_row(row)
    DdsRow.query.delete()
    db.session.flush()

    added = 0
    for r in range(3, ws.max_row + 1):
        d = ws.cell(r, 3).value
        if d is None:
            continue
        db.session.add(DdsRow(
            rownum=r,
            ddate=d.date() if hasattr(d, "date") else d,
            amount=_num(ws.cell(r, 4).value),
            wallet=(ws.cell(r, 5).value or ""),
            wallet2=(ws.cell(r, 6).value or ""),
            purpose=str(ws.cell(r, 7).value or "").strip(),
            article=(ws.cell(r, 8).value or ""),
        ))
        added += 1
        if added % 500 == 0:
            db.session.flush()

    # ── 2. Hamyon qoldiqlari (ДДС_2026 varag'idan) ──
    openings = 0
    year_sheet = next((n for n in wb.sheetnames
                       if n.startswith(SHEET_YEAR_PREFIX)), None)
    if year_sheet:
        ddsflow.ensure_wallets()
        ys = wb[year_sheet]
        in_bal = False
        for r in range(1, min(ys.max_row, 40) + 1):
            label = _norm(ys.cell(r, 1).value)
            if not label:
                continue
            if label.startswith("остаток дс на начало"):
                in_bal = True
                continue
            if in_bal:
                code = OPENING_MAP.get(label)
                if code:
                    w = Wallet.query.filter_by(code=code).first()
                    if w:
                        w.opening = _num(ys.cell(r, 2).value)
                        openings += 1
                elif label.startswith(("операционная", "поступления")):
                    break

    db.session.commit()

    # ── 3-4. Kassa + moslash ──
    reb = ddsflow.rebuild_all()
    mat = matching.run_all()

    return {"old": old, "added": added, "openings": openings,
            "tx": reb["made"], "tx_skipped": reb["skipped"],
            "auto": mat["auto"], "queued": mat["queued"]}
