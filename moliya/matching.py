"""Mijoz to'lovini shartnomaga avtomat bog'lash (2-bosqich).

Andoza — bank ko'chirmasini yuklash (1C «Загрузка выписки», QuickBooks/Xero
bank feed): tizim taxmin qiladi, lekin **jimgina** qaror qabul qilmaydi.
Ishonchi yetmasa — navbatga qo'yadi, odam bir bosishda tasdiqlaydi.

Uch manba ishlatiladi:
  • Статья              → yo'nalish (РОП / СМК / ТББ)
  • Назначение платежа  → o'quvchi ismi
  • Кошелек (2)         → to'lov turi (Depozit / Debitorka / Toliq tolov)

Ishonch darajasi:
  ≥ 0.92 va yagona nomzod  → avtomat bog'lanadi  (match_status="auto")
  aks holda                → navbatga tushadi    (match_status="none")
"""
import re
import unicodedata
from difflib import SequenceMatcher

from database import db
from models import Contract, DdsRow, Student, Transaction

import ddsflow

# shu chegaradan yuqori bo'lsagina avtomat bog'lanadi
AUTO_THRESHOLD = 0.92
# navbatda ko'rsatiladigan eng past o'xshashlik — bundan pasti shunchaki shovqin
SUGGEST_THRESHOLD = 0.65

# ism emas — umumiy izohlar (bulardan hech qachon ism qidirilmaydi)
STOPWORDS = {
    "prixod klient", "klient prixod", "rop prixod", "prixod", "klient",
    "click", "payme", "uzum", "smk", "rop", "tbb", "mbm", "mfaktor",
    "prixod klienta", "oplata", "tolov", "to'lov", "перевод", "приход",
    "поступление", "клиент", "оплата",
}

# Yuqoridagi ro'yxat faqat AYNAN mos kelgan izohni ushlaydi. Amalda izohlar
# xato yoziladi («prixod klientt rop», «prixod klietn», «klienty») va bunday
# qator ism deb qabul qilinib qolardi. Shuning uchun har bir so'z alohida,
# o'zak bo'yicha tekshiriladi.
JARGON_STEMS = (
    "prix", "prih", "приход", "klien", "kliyen", "kleint", "klietn", "клиент",
    "oplat", "оплат", "tolov", "tulov", "inkass", "инкасс", "perevod", "перевод",
    "postup", "поступ", "depozit", "депозит", "ostatok", "остаток",
    "vozvrat", "возврат", "dogovor", "договор", "shartnoma", "avans", "аванс",
    "predoplat", "chastich", "summa", "сумма", "obmen", "обмен",
    # to'lov kanali va ichki xarajat izohlari — bular ham ism emas
    "edinn", "едины", "gonorar", "гонорар", "spiker", "спикер",
    "qaytar", "kaytar", "chiqaril", "ortiqch",
)
# to'liq so'z sifatida uchrasa jargon (o'zak sifatida ismga tegib ketmasin)
JARGON_WORDS = {
    "rop", "smk", "tbb", "twb", "tvv", "mbm", "mfaktor", "click", "payme",
    "uzum", "mchj", "yatt", "ooo", "мчж", "naqd", "karta", "kartaga",
    "schet", "schetdan", "bank", "bankdan", "dolg", "qarz", "kurs", "seminar",
}

# Bitta qatorda bir nechta odamning ismi sanalgan bo'lishi mumkin (to'plam
# to'lov). Bunday qator bitta shartnomaga tegishli emas — chetlab o'tiladi.
MAX_NAME_WORDS = 4


def _is_jargon(word):
    return word in JARGON_WORDS or any(word.startswith(s) for s in JARGON_STEMS)

# lotin ↔ kirill: ismlarni bir alifboga keltiramiz
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


def translit(s):
    return "".join(_CYR.get(ch, ch) for ch in s)


def norm_name(s):
    """Ismni solishtirishga tayyorlash: kichik harf, bitta alifbo, tartiblangan.

    «Suyunova Barno» va «Barno Suyunova» bir xil deb qaraladi.
    """
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    s = s.replace("ʼ", "").replace("'", "").replace("`", "").replace("’", "")
    s = translit(s)
    s = re.sub(r"[^a-z\s]", " ", s)
    parts = [p for p in s.split() if len(p) > 1]
    # o'zbek familiya qo'shimchalarini bir xillashtirish: -ov/-ova, -yev/-yeva
    return " ".join(sorted(parts))


def looks_like_name(purpose):
    """Izohda haqiqiy ism bormi?"""
    n = norm_name(purpose)
    if not n:
        return False
    raw = " ".join(str(purpose or "").strip().lower().split())
    if raw in STOPWORDS:
        return False
    parts = n.split()
    if len(parts) < 2:
        return False
    if len(parts) > MAX_NAME_WORDS:
        return False                      # to'plam to'lov: ko'p ism sanalgan
    # jargon so'z qatnashsa — bu ism emas, to'lov izohi
    if any(_is_jargon(p) for p in parts):
        return False
    # har bir bo'lak stop-so'z bo'lsa — ism emas
    if all(p in STOPWORDS for p in parts):
        return False
    return True


def similarity(a, b):
    """0..1 — ikki ism qanchalik yaqin."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    base = SequenceMatcher(None, na, nb).ratio()
    # umumiy so'zlar ulushi — «Suyunova Barno Baxtiyorovna» holati uchun
    sa, sb = set(na.split()), set(nb.split())
    if sa and sb:
        jac = len(sa & sb) / len(sa | sb)
        full = len(sa & sb) / min(len(sa), len(sb))   # biri ikkinchisini qamrasa
        base = max(base, (base + jac) / 2, full * 0.95)
    return round(min(base, 1.0), 4)


# ══════════════════════════════════════════════════════════════════
#  Nomzodlarni topish
# ══════════════════════════════════════════════════════════════════
def _course_matches(contract, direction):
    """Shartnoma kursi ДДС yo'nalishiga mos keladimi?"""
    if not direction:
        return True
    name = ddsflow.norm(contract.cohort.course.name if contract.cohort else "")
    keys = {"РОП": ("роп", "rop", "rahbar"),
            "СМК": ("смк", "smk", "sotuv"),
            "ТББ": ("тбб", "tbb", "тбв", "biznes")}.get(direction, ())
    return any(k in name for k in keys)


def candidates(row, limit=5):
    """Qatorga mos shartnomalar — o'xshashligi bo'yicha tartiblangan.

    Qaytaradi: [{"contract":…, "score":…, "reason":…}]
    """
    if not ddsflow.is_client_payment(row) or not looks_like_name(row.purpose):
        return []
    direction = ddsflow.direction_for(row.article)
    out = []
    # Namunaviy (vaqtinchalik) shartnomalar chetlab o'tiladi — haqiqiy to'lov
    # hech qachon uydirma o'quvchiga bog'lanib qolmasligi kerak.
    for c in (Contract.query
              .filter(Contract.status != "refunded")
              .filter(~Contract.note.like("%[namuna]%")).all()):
        sc = similarity(row.purpose, c.student.name)
        reasons = [f"ism {int(sc * 100)}%"]
        if _course_matches(c, direction):
            reasons.append(f"yo'nalish {direction}")
        else:
            sc -= 0.15                     # boshqa yo'nalish — ishonch pasayadi
            reasons.append(f"yo'nalish mos emas ({direction})")
        if c.due_total() > 0.01:
            reasons.append("qarzi bor")
        else:
            sc -= 0.05                     # to'liq to'langan — ehtimoli past
            reasons.append("to'liq to'langan")
        if sc < SUGGEST_THRESHOLD:         # jarimalardan KEYIN tekshiramiz
            continue
        out.append({"contract": c, "score": round(max(sc, 0), 4),
                    "reason": ", ".join(reasons)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ══════════════════════════════════════════════════════════════════
#  Bog'lash / bekor qilish
# ══════════════════════════════════════════════════════════════════
def apply(row, contract, status="manual", score=None):
    """Qatorni shartnomaga bog'laydi va grafikni FIFO bo'yicha yopadi.

    Kassa yozuvi QAYTA yaratilmaydi — u 1-bosqichda allaqachon bor.
    Faqat unga contract_id qo'yiladi. Shuning uchun pul ikki marta
    hisoblanmaydi.
    """
    if row.contract_id:
        unapply(row)
    row.contract_id = contract.id
    row.match_status = status
    row.match_score = score if score is not None else 1.0

    tx = Transaction.query.filter_by(dds_row_id=row.id).first()
    if tx:
        tx.contract_id = contract.id

    # FIFO: eng eski to'lanmagan qatordan boshlab yopamiz
    rest = row.amount or 0.0
    for line in contract.lines:
        need = line.amount - line.paid
        if need <= 0.01 or rest <= 0:
            continue
        pay = min(need, rest)
        line.paid += pay
        rest -= pay
    # grafikka aynan qancha yozilgani eslab qolinadi: bekor qilinganda
    # xuddi shu summa qaytariladi (ortiqchasi — avans — tegilmaydi)
    row.applied_amount = (row.amount or 0.0) - rest
    return rest                            # ortiqcha qolgan summa (avans)


def unapply(row):
    """Bog'lanishni bekor qiladi va grafikdan to'lovni teskari yechadi."""
    if not row.contract_id:
        return
    c = db.session.get(Contract, row.contract_id)
    if c:
        # Aynan shu qator grafikka qancha yozgan bo'lsa, shuncha qaytariladi.
        # applied_amount = 0 ham to'liq ma'noli qiymat (hammasi avansga
        # ketgan) — faqat NULL, ya'ni eski qator, summaga tayanadi.
        rest = row.amount or 0.0 if row.applied_amount is None \
            else row.applied_amount
        for line in reversed(list(c.lines)):   # LIFO — apply'ning teskarisi
            if rest <= 0 or line.paid <= 0:
                continue
            back = min(line.paid, rest)
            line.paid -= back
            rest -= back
    tx = Transaction.query.filter_by(dds_row_id=row.id).first()
    if tx:
        tx.contract_id = None
    row.contract_id = None
    row.match_score = 0.0
    row.applied_amount = 0.0
    if row.match_status in ("auto", "manual"):
        row.match_status = "none"


def auto_match(row):
    """Ishonch yetsa — o'zi bog'laydi. Aks holda navbatda qoladi.

    Qaytaradi: "auto" | "none" | "skip"
    """
    if not ddsflow.is_client_payment(row):
        return "skip"
    if row.match_status in ("manual", "skipped", "new"):
        return row.match_status           # odam qaror qilgan — tegmaymiz
    cands = candidates(row, limit=2)
    if not cands:
        # ilgari bog'langan bo'lsa — grafikdan ham yechib qo'yamiz, aks holda
        # «bog'lanmagan» deb turib, pul shartnomada yozilgancha qolardi
        if row.contract_id:
            unapply(row)
        row.match_status = "none"
        return "none"
    top = cands[0]
    second = cands[1]["score"] if len(cands) > 1 else 0
    # yagona va ishonchli bo'lsagina avtomat
    if top["score"] >= AUTO_THRESHOLD and top["score"] - second >= 0.08:
        apply(row, top["contract"], status="auto", score=top["score"])
        return "auto"
    row.match_status = "none"
    row.match_score = top["score"]
    return "none"


def run_all(commit=True):
    """Barcha bog'lanmagan mijoz to'lovlarini qayta ko'rib chiqadi.

    commit=False — import kabi chaqiruvchi hammasini bitta tranzaksiyada
    saqlamoqchi bo'lganda ishlatiladi.
    """
    auto = queued = skipped = 0
    for row in DdsRow.query.order_by(DdsRow.rownum).all():
        r = auto_match(row)
        if r == "auto":
            auto += 1
        elif r == "none":
            queued += 1
        else:
            skipped += 1
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return {"auto": auto, "queued": queued, "skipped": skipped}


# ══════════════════════════════════════════════════════════════════
#  Navbat («Tanilmagan to'lovlar»)
# ══════════════════════════════════════════════════════════════════
def inbox(limit=300, show="open", art="", month=""):
    """Navbatdagi qatorlar + har biriga tayyor takliflar.

    art   — kurs belgisi bo'yicha filtr (РОП / СМК / ТББ)
    month — oy bo'yicha filtr («2026-06» ko'rinishida)
    """
    q = DdsRow.query.filter(DdsRow.article.in_(_client_article_names()))
    if show == "open":
        q = q.filter(db.or_(DdsRow.contract_id.is_(None),
                            DdsRow.contract_id == 0),
                     DdsRow.match_status.notin_(["skipped", "new"]))
    elif show == "skipped":
        q = q.filter(DdsRow.match_status == "skipped")
    elif show == "matched":
        q = q.filter(DdsRow.contract_id.isnot(None))
    if art:
        q = q.filter(DdsRow.article.like(f"%{art}%"))
    rows = q.order_by(DdsRow.ddate.desc(), DdsRow.rownum.desc()).all()
    if month:
        rows = [r for r in rows if r.ddate and r.ddate.strftime("%Y-%m") == month]
    out = []
    for r in rows[:limit]:
        out.append({"row": r,
                    "direction": ddsflow.direction_for(r.article),
                    "named": looks_like_name(r.purpose),
                    "cands": candidates(r, limit=3) if show != "matched" else []})
    return out


def inbox_months(show="open"):
    """Filtr chiplari uchun: qaysi oylarda nechta qator bor."""
    from collections import Counter
    q = DdsRow.query.filter(DdsRow.article.in_(_client_article_names()))
    if show == "open":
        q = q.filter(DdsRow.contract_id.is_(None),
                     DdsRow.match_status.notin_(["skipped", "new"]))
    elif show == "skipped":
        q = q.filter(DdsRow.match_status == "skipped")
    elif show == "matched":
        q = q.filter(DdsRow.contract_id.isnot(None))
    c = Counter(r.ddate.strftime("%Y-%m") for r in q.all() if r.ddate)
    return sorted(c.items())


def bulk_skip(ids, reason=""):
    """Bir nechta qatorni birdan chetlatish (sabab bilan)."""
    n = 0
    for rid in ids:
        row = db.session.get(DdsRow, rid)
        if row is None:
            continue
        unapply(row)
        row.match_status = "skipped"
        row.skip_note = (reason or "").strip()[:200]
        n += 1
    db.session.commit()
    return n


def bulk_restore(ids):
    """Chetlatilganlarni navbatga qaytarish."""
    n = 0
    for rid in ids:
        row = db.session.get(DdsRow, rid)
        if row is not None and row.match_status == "skipped":
            row.match_status = "none"
            row.skip_note = ""
            n += 1
    db.session.commit()
    return n


def _client_article_names():
    from models import DDS_SPRAVOCHNIK
    return [a for a, _, _ in DDS_SPRAVOCHNIK
            if ddsflow.direction_for(a) is not None]


def open_count():
    """Navbatdagi qatorlar soni — har sahifada chaqiriladi, yengil so'rov."""
    return (DdsRow.query
            .filter(DdsRow.article.in_(_client_article_names()),
                    DdsRow.contract_id.is_(None),
                    DdsRow.match_status.notin_(["skipped", "new"]))
            .count())


def stats():
    """Navbat holati — dashboard va sahifa sarlavhasi uchun."""
    arts = _client_article_names()
    rows = DdsRow.query.filter(DdsRow.article.in_(arts)).all()
    total = len(rows)
    matched = [r for r in rows if r.contract_id]
    auto = [r for r in matched if r.match_status == "auto"]
    skipped = [r for r in rows if r.match_status == "skipped"]
    openq = [r for r in rows
             if not r.contract_id and r.match_status not in ("skipped", "new")]
    amt = lambda L: sum(x.amount for x in L)
    return {"total": total, "total_amt": amt(rows),
            "matched": len(matched), "matched_amt": amt(matched),
            "auto": len(auto), "manual": len(matched) - len(auto),
            "skipped": len(skipped),
            "open": len(openq), "open_amt": amt(openq),
            "named": sum(1 for r in openq if looks_like_name(r.purpose)),
            "pct": round(len(matched) / total * 100) if total else 0}


def find_or_create_student(name, source=""):
    """Ismi bo'yicha o'quvchini topadi, bo'lmasa yaratadi."""
    target = norm_name(name)
    for s in Student.query.all():
        if norm_name(s.name) == target:
            return s, False
    s = Student(name=name.strip(), source=source)
    db.session.add(s)
    db.session.flush()
    return s, True
