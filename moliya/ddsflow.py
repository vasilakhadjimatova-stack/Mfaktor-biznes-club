"""ДДС → Kassa avtomat oqimi (1-bosqich).

Falsafa: buxgalter faqat «ДДС данные» varag'ini to'ldiradi — boshqa hamma
narsa o'zi hosil bo'ladi. Har bir ДДС qatori aynan bitta kassa yozuvini
(Transaction) tug'diradi va u qatorga qattiq bog'lanadi:

    DdsRow.id  ←──  Transaction.dds_row_id

Shu bog'lanish tufayli:
  • qator qo'shilsa   → kassa yozuvi yaratiladi
  • qator tahrirlansa → o'sha yozuv yangilanadi (yangisi qo'shilmaydi)
  • qator o'chirilsa  → yozuv ham o'chadi, shartnomaga ta'siri qaytariladi

Ya'ni ikki marta hisoblanish ham, «osilib qolgan» yozuv ham bo'lmaydi.
"""
import unicodedata

from database import db
from models import (TRANSFER_CAT, DDS_LOOKUP, Transaction, Wallet)


# ══════════════════════════════════════════════════════════════════
#  Spravochniklar: ДДС nomi → dastur kodi
# ══════════════════════════════════════════════════════════════════
WALLET_MAP = {
    "рс mbm": ("rs_mbm", "РС МБМ"),
    "наличные": ("nal", "Наличные (сум)"),
    "рс davr bank mbm": ("davr_mbm", "РС Davr bank МБМ"),
    "$": ("usd", "$ (valyuta)"),
    "uzcard 2406": ("uzcard2406", "UZCARD 2406"),
    "pc mfaktor": ("rs_mfaktor", "РС MFAKTOR"),
    "рс mfaktor": ("rs_mfaktor", "РС MFAKTOR"),
    "mfaktor karta": ("karta_mfaktor", "карта MFAKTOR"),
}

CAT_MAP = {
    "поступление от клиента роп": "Поступление от клиента РОП",
    "поступление от клиента смк": "Поступление от клиента СМК",
    "поступление от клиента tbb": "Поступление от клиента ТББ",
    "поступление от клиента твв": "Поступление от клиента ТББ",
    "поступление от клиента тбб": "Поступление от клиента ТББ",
    "поступление б2б": "Поступление Б2Б",
    "мфактор поступления": "Мфактор поступления",
    "доход — долг": "Доход — долг",
    "доход - долг": "Доход — долг",
    "возврат поступления/клиент": "Возврат клиенту",
    "зарплата": "Зарплата МБМ",
    "зарплата смк": "Зарплата СМК",
    "зарплата роп": "Зарплата РОП",
    "зарплата тбб": "Зарплата ТББ",
    "премия": "Премия",
    "аренда": "Аренда",
    "налог дивиденд/зп": "Налог/дивиденд Зп",
    "дивиденды": "Дивиденды",
    "обед сотрудники": "Обед сотрудников",
    "комиссия банк": "Комиссия банка",
    "комунальные услуги": "Коммунальные услуги",
    "коммунальные услуги": "Коммунальные услуги",
    "ремонт": "Ремонт",
    "таргет": "Таргет (реклама)",
    "закуп/хоз товар": "Закуп хоз. товаров",
    "выпускное расходы": "Выпускные расходы",
    "кофе брейк": "Кофе-брейк",
    "срм online pbx": "CRM OnlinePBX",
    "crm online pbx": "CRM OnlinePBX",
    "такси": "Такси",
    "интернет/ip-телефония": "Интернет/IP-телефония",
    "интернет/iр-телефония": "Интернет/IP-телефония",
    "абонентские подписки": "Абонентские подписки",
    "хайрия": "Хайрия",
    "корпоративный расход": "Корпоративный расход",
    "прочие расходы": "Прочие расходы",
    "расход — долг": "Расход — долг",
    "расход - долг": "Расход — долг",
    "продажа ос": "Продажа ОС",
    "покупка ос": "Покупка ОС",
    "поступление кредитов и займов": "Поступление кредитов и займов",
    "прочие поступления от фин. операции": "Прочие поступления",
    "займ от собственника": "Займ от собственника",
    "погашение тела кредита, займа": "Погашение кредита",
    "погашение процентов по кредитам, займам": "Проценты по кредитам",
    "доход — перевод между счетами": TRANSFER_CAT,
    "расход — перевод между счетами": TRANSFER_CAT,
    "доход - перевод между счетами": TRANSFER_CAT,
    "расход - перевод между счетами": TRANSFER_CAT,
}

# mijoz to'lovi statyalari → yo'nalish (moslash uchun 2-bosqichda kerak)
CLIENT_ARTICLES = {
    "поступление от клиента роп": "РОП",
    "поступление от клиента смк": "СМК",
    "поступление от клиента tbb": "ТББ",
    "поступление от клиента твв": "ТББ",
    "поступление от клиента тбб": "ТББ",
}


def norm(s):
    """Solishtirish uchun bir xil ko'rinishga keltirish."""
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    return " ".join(s.split())


def wallet_for(name):
    return WALLET_MAP.get(norm(name))


def category_for(article):
    return CAT_MAP.get(norm(article))


def direction_for(article):
    """Mijoz to'lovi bo'lsa yo'nalish (РОП/СМК/ТББ), aks holda None."""
    return CLIENT_ARTICLES.get(norm(article))


def is_client_payment(row):
    return direction_for(row.article) is not None


# ══════════════════════════════════════════════════════════════════
#  Bitta qator → bitta kassa yozuvi
# ══════════════════════════════════════════════════════════════════
def check_row(row):
    """Qator kassaga tushishi mumkinmi? (kod, sabab) qaytaradi."""
    if not row.ddate:
        return None, "sana yo'q"
    if not row.amount or row.amount <= 0:
        return None, "summa 0"
    w = wallet_for(row.wallet)
    if not w:
        return None, f"notanish hamyon: {row.wallet}"
    c = category_for(row.article)
    if not c:
        return None, f"notanish statya: {row.article}"
    return (w, c), None


def ensure_wallets():
    """ДДС hamyonlari dasturda ham bo'lsin."""
    made = 0
    for code, name in WALLET_MAP.values():
        if not Wallet.query.filter_by(code=code).first():
            db.session.add(Wallet(code=code, name=name, opening=0.0))
            made += 1
    if made:
        db.session.flush()
    return made


def sync_row(row):
    """ДДС qatorini kassa yozuviga aylantiradi (yoki mavjudini yangilaydi).

    Qaytaradi: Transaction yoki None (agar qator kassaga tushmasa).
    """
    parsed, why = check_row(row)
    tx = Transaction.query.filter_by(dds_row_id=row.id).first()
    if not parsed:
        # qator yaroqsiz bo'lib qolgan bo'lsa — eski yozuvni olib tashlaymiz
        if tx:
            db.session.delete(tx)
        return None

    (wcode, _wname), cat = parsed
    flow = DDS_LOOKUP.get(row.article, ("", ""))[0]
    operation = "kirim" if flow == "Поступление" else "chiqim"
    activity = {"Техническая операция": "tech",
                "Финансовая": "finance",
                "Инвестиционная": "invest"}.get(row.activity, "operating")
    if cat == TRANSFER_CAT:
        activity = "tech"

    if not tx:
        tx = Transaction(dds_row_id=row.id)
        db.session.add(tx)

    tx.tdate = row.ddate
    tx.wallet_code = wcode
    tx.operation = operation
    tx.amount = row.amount
    tx.category = cat
    tx.activity = activity
    tx.counterparty = (row.purpose or "")[:200]
    tx.comment = f"[{row.wallet2}] {row.purpose}".strip() if row.wallet2 \
        else (row.purpose or "")
    # shartnoma bog'lanishi 2-bosqichda qo'yiladi — bu yerda faqat ko'chiramiz
    tx.contract_id = row.contract_id
    return tx


def unsync_row(row):
    """Qator o'chirilishidan oldin: kassa yozuvi va shartnomaga ta'sirini qaytarish."""
    import matching                      # aylanma importni oldini olish uchun
    matching.unapply(row)                # grafikdagi to'lovni qaytaradi
    tx = Transaction.query.filter_by(dds_row_id=row.id).first()
    if tx:
        db.session.delete(tx)


def rebuild_all(wipe_legacy=True):
    """Barcha ДДС qatorlarini kassaga qayta yozadi.

    wipe_legacy=True bo'lsa, eski `import_dds.py` qoldirgan bog'lanmagan
    yozuvlarni ham tozalaydi — shunda kassa ДДС bilan aynan 1:1 bo'ladi.
    """
    from models import DdsRow
    ensure_wallets()
    removed = 0
    if wipe_legacy:
        removed = (Transaction.query
                   .filter(Transaction.comment.like("%[dds-import]%"))
                   .delete(synchronize_session=False))
    made = skipped = 0
    problems = {}
    for row in DdsRow.query.order_by(DdsRow.rownum).all():
        parsed, why = check_row(row)
        if not parsed:
            problems[why] = problems.get(why, 0) + 1
            skipped += 1
            continue
        sync_row(row)
        made += 1
        if made % 500 == 0:
            db.session.flush()
    db.session.commit()
    return {"made": made, "skipped": skipped, "removed": removed,
            "problems": problems}
