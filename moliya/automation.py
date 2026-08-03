"""
Avtomatika yadrosi — «bir amal → bir nechta jarayon» (Impulse falsafasi).

Har bir asosiy amal zanjir ishga tushiradi:

  TO'LOV QABUL QILINDI (bitta forma):
    1) kassaga tranzaksiya yoziladi
    2) grafik FIFO bo'yicha yopiladi
    3) muddati o'tgan eslatmalar avtomatik bekor bo'ladi
    4) to'liq to'langanda shartnoma belgilanadi
    5) kvitansiya matni tayyorlanadi (Telegram/SMSga yuborishga tayyor)
    6) jurnalga voqea tushadi

  KUNNI YOPISH (bitta tugma):
    1) muddati o'tgan har bir qator uchun eslatma matni
    2) bugun muddati kelgan takrorlanuvchi to'lovlar ro'yxati
    3) ertaga/7 kunda kutilayotgan to'lovlar
    4) kunlik xulosa (kirim/chiqim/sof)
"""
from datetime import date, datetime, timedelta

from database import db
from models import (AutoEvent, Contract, InstallmentLine, RecurringPayment,
                    ReminderLog, Transaction)

import core


def log_event(kind, title, detail="", contract_id=None):
    db.session.add(AutoEvent(kind=kind, title=title, detail=detail,
                             contract_id=contract_id))


def feed(limit=60):
    return (AutoEvent.query.order_by(AutoEvent.created_at.desc())
            .limit(limit).all())


# ══════════════════════════════════════════════════════════════════
#  TO'LOV ZANJIRI
# ══════════════════════════════════════════════════════════════════
def on_payment(contract, amount, wallet_code):
    """To'lov qabul qilingandagi zanjir. Qaytaradi: (steps, receipt_text)."""
    steps = ["Kassaga kirim yozildi", "Grafik FIFO bo'yicha yopildi"]

    # 3) eslatma navbati tozalanadi — endi qarzi yo'q qatorlar uchun
    cleared = 0
    for line in contract.lines:
        if line.paid >= line.amount - 0.01:
            n = ReminderLog.query.filter_by(line_id=line.id).delete(
                synchronize_session=False)
            cleared += n
    if cleared:
        steps.append("Eslatma navbatidan chiqarildi")

    # 4) to'liq to'langan bo'lsa — belgilab qo'yamiz
    fully_paid = contract.due_total() <= 0.01
    if fully_paid:
        steps.append("Shartnoma TO'LIQ TO'LANGAN deb belgilandi")

    # 5) kvitansiya matni
    receipt = receipt_text(contract, amount)
    steps.append("Kvitansiya matni tayyorlandi")

    # 6) jurnal
    log_event("payment",
              f"To'lov: {contract.student.name} — {amount:,.0f} so'm",
              " → ".join(steps), contract.id)
    return steps, receipt


def receipt_text(contract, amount):
    c = contract
    left = c.due_total()
    lines = [
        "✅ To'lov qabul qilindi — MFAKTOR BIZNES MAKTABI",
        f"O'quvchi: {c.student.name}",
        f"Kurs: {c.cohort.course.name} ({c.cohort.name})",
        f"Summa: {amount:,.0f} so'm",
        f"Jami to'landi: {c.paid_total():,.0f} / {c.net_price:,.0f} so'm",
    ]
    if left > 0.01:
        nxt = next((l for l in c.lines if l.paid < l.amount - 0.01), None)
        if nxt:
            lines.append(f"Keyingi to'lov: {nxt.due_date.strftime('%d.%m.%Y')} "
                         f"— {nxt.amount - nxt.paid:,.0f} so'm")
    else:
        lines.append("Shartnoma to'liq to'landi. Rahmat! 🎉")
    return "\n".join(lines).replace(",", " ")


# ══════════════════════════════════════════════════════════════════
#  SHARTNOMA / REFUND ZANJIRLARI
# ══════════════════════════════════════════════════════════════════
def welcome_text(contract):
    n_parts = len(contract.lines) or 1
    return (f"Assalomu alaykum, {contract.student.name}!\n"
            f"Siz {contract.cohort.course.name} ({contract.cohort.name}) "
            f"oqimiga qabul qilindingiz. Boshlanish: "
            f"{contract.cohort.start_date.strftime('%d.%m.%Y')}.\n"
            f"Shartnoma summasi: {contract.net_price:,.0f} so'm, "
            f"{n_parts} qismga bo'lib to'lanadi. Ilk to'lov: "
            f"{contract.lines[0].due_date.strftime('%d.%m.%Y') if contract.lines else '—'}."
            ).replace(",", " ")


def on_contract_created(contract, n_parts):
    steps = [f"O'quvchi bazaga yozildi ({contract.student.source})",
             f"{n_parts} qismli to'lov grafigi tuzildi",
             "CAC hisobiga kanal biriktirildi",
             "Xush kelibsiz xabari tayyorlandi"]
    log_event("contract",
              f"Yangi shartnoma: {contract.student.name} — "
              f"{contract.cohort.course.name}",
              " → ".join(steps), contract.id)
    return steps, welcome_text(contract)


def on_refund(contract, amount):
    log_event("refund",
              f"Pul qaytarildi: {contract.student.name} — {amount:,.0f} so'm",
              "Chiqim yozildi → shartnoma holati yangilandi → "
              "tan olingan daromad qayta hisoblandi", contract.id)


# ══════════════════════════════════════════════════════════════════
#  KUNNI YOPISH — bitta tugma, to'rt jarayon
# ══════════════════════════════════════════════════════════════════
def reminder_text(item):
    """Muddati o'tgan grafik qatori uchun tayyor eslatma matni."""
    c = item["contract"]
    return (f"Assalomu alaykum, {c.student.name}!\n"
            f"MFAKTOR: {c.cohort.course.name} kursi bo'yicha "
            f"{item['line'].due_date.strftime('%d.%m.%Y')} dagi to'lovingiz "
            f"({item['rest']:,.0f} so'm) {item['days']} kun kechikdi.\n"
            f"Iltimos, imkon qadar tez to'lab qo'ying. Savollar bo'lsa shu "
            f"raqamga yozing. Rahmat!").replace(",", " ")


def close_day(today=None):
    """Kunlik avtomatika. Qaytadi: dict (eslatmalar, takroriylar, xulosa)."""
    today = today or date.today()

    # 1) muddati o'tganlar — bugun hali eslatilmaganlar
    overdue = core.overdue_lines(today)
    reminders = []
    for item in overdue:
        already = ReminderLog.query.filter_by(
            line_id=item["line"].id, sent_date=today).first()
        if already:
            continue
        reminders.append({**item, "text": reminder_text(item)})

    # 2) bugun muddati kelgan takrorlanuvchi to'lovlar (hali yozilmaganlari)
    rec_due = []
    for r in RecurringPayment.query.filter_by(is_active=True):
        if r.pay_day != today.day:
            continue
        exists = (Transaction.query
                  .filter(Transaction.category == r.category,
                          Transaction.operation == "chiqim",
                          Transaction.tdate == today,
                          Transaction.counterparty == r.name).first())
        if not exists:
            rec_due.append(r)

    # 3) 7 kunlik prognoz
    upcoming = core.upcoming_lines(7, today)

    # 4) kunlik xulosa
    day_txs = (Transaction.query
               .filter(Transaction.tdate == today,
                       Transaction.is_transfer.is_(False),
                       Transaction.activity != "tech").all())
    inc = sum(t.amount for t in day_txs if t.operation == "kirim")
    exp = sum(t.amount for t in day_txs if t.operation == "chiqim")

    log_event("day",
              f"Kun yopildi: {today.strftime('%d.%m.%Y')}",
              f"Kirim {inc:,.0f} · Chiqim {exp:,.0f} · "
              f"{len(reminders)} eslatma tayyorlandi · "
              f"{len(rec_due)} takroriy to'lov kutilmoqda")
    return {"today": today, "reminders": reminders, "rec_due": rec_due,
            "upcoming": upcoming, "inc": inc, "exp": exp, "net": inc - exp}


def mark_reminded(line_id, channel="manual", today=None):
    today = today or date.today()
    if not ReminderLog.query.filter_by(line_id=line_id, sent_date=today).first():
        db.session.add(ReminderLog(line_id=line_id, sent_date=today,
                                   channel=channel))
        line = db.session.get(InstallmentLine, line_id)
        if line:
            log_event("reminder",
                      f"Eslatma yuborildi: {line.contract.student.name}",
                      f"{line.due_date.strftime('%d.%m.%Y')} qatori, "
                      f"qoldiq {line.amount - line.paid:,.0f} so'm",
                      line.contract_id)


def book_recurring(rec_id, wallet_code, today=None):
    """Takrorlanuvchi to'lovni bir bosishda kassaga yozish."""
    today = today or date.today()
    r = db.session.get(RecurringPayment, rec_id)
    if not r:
        return None
    db.session.add(Transaction(
        tdate=today, wallet_code=wallet_code, operation="chiqim",
        amount=r.amount, category=r.category, counterparty=r.name,
        comment="Takrorlanuvchi to'lov (avtomatika)"))
    log_event("payment", f"Takroriy to'lov yozildi: {r.name}",
              f"{r.amount:,.0f} so'm → {r.category}")
    return r
