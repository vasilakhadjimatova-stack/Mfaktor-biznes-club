"""
Telegram xabarnoma.

Nima uchun Telegram: O'zbekistonda deyarli hamma foydalanadi, SMS'dan
farqli o'laroq bepul va xabar uzunligi cheklanmagan.

Qanday ishlaydi:
  1. Direktor sozlamalarda bot tokenini kiritadi (@BotFather beradi).
  2. O'quvchi kuratordan olgan havolasini bosadi: t.me/<bot>?start=<kalit>.
     Bot «/start <kalit>» xabarini oladi, biz shu kalit orqali o'quvchini
     topib, uning chat_id sini shartnomaga yozamiz.
  3. Shundan keyin unga eslatma yuborish mumkin.

Ikkinchi qadam uchun Telegram bizning serverimizni ko'ra olishi kerak
(webhook). Offline nusxada bu ishlamaydi — shuning uchun kurator chat_id ni
qo'lda ham kirita oladi va xabar yuborishni sinab ko'radi.

Xabar tarixi TgMessage jadvalida turadi: bir xil eslatma bir kunda ikki
marta ketmaydi (dedup_key).
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import localtime

from database import db

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 20

KINDS = {
    "qarz": "To'lov eslatmasi",
    "dars": "Dars eslatmasi",
    "vazifa": "Vazifa muddati",
    "qolda": "Qo'lda yozilgan",
}


# ── Sozlama ───────────────────────────────────────────────────────
def _get(key, default=""):
    from models import AppSetting
    try:
        row = db.session.get(AppSetting, key)
    except Exception:                                  # noqa: BLE001
        db.session.rollback()
        return default
    return (row.value or default) if row else default


def _set(key, value):
    from models import AppSetting
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        db.session.add(row)
    row.value = value
    db.session.commit()


def bot_token():
    return _get("tg_token", "").strip()


def bot_username():
    return _get("tg_username", "").strip().lstrip("@")


def set_bot(token, username):
    _set("tg_token", (token or "").strip())
    _set("tg_username", (username or "").strip().lstrip("@"))


def enabled():
    return bool(bot_token())


def link_url(contract):
    """O'quvchiga beriladigan havola — bosgach bot uni taniydi."""
    u = bot_username()
    if not u or not contract.portal_token:
        return None
    return f"https://t.me/{u}?start={contract.portal_token}"


# ── Telegram bilan gaplashish ─────────────────────────────────────
def _call(method, payload):
    """(ok, natija_yoki_xato). Tarmoq yo'q bo'lsa ham yiqilmaydi."""
    token = bot_token()
    if not token:
        return False, "Bot tokeni kiritilmagan"
    url = f"{API}/bot{token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if not data.get("ok"):
            return False, str(data.get("description") or "noma'lum xato")[:300]
        return True, data.get("result")
    except urllib.error.HTTPError as exc:
        try:
            d = json.loads(exc.read().decode("utf-8", "replace"))
            return False, str(d.get("description") or exc)[:300]
        except Exception:                              # noqa: BLE001
            return False, f"HTTP {exc.code}"
    except Exception as exc:                           # noqa: BLE001
        logger.error(f"Telegram xato: {exc}")
        return False, str(exc)[:300]


def check_bot():
    """Token to'g'rimi — @username ni qaytaradi."""
    ok, res = _call("getMe", {})
    if not ok:
        return False, res
    name = (res or {}).get("username", "")
    if name and not bot_username():
        _set("tg_username", name)
    return True, name


def send(contract, text, kind="qolda", dedup_key=None):
    """Bitta o'quvchiga xabar. Tarixga yozadi, takrorlanishdan saqlaydi."""
    from models import TgMessage
    if dedup_key:
        was = TgMessage.query.filter_by(dedup_key=dedup_key, ok=True).first()
        if was:
            return None                    # bugun allaqachon yuborilgan
    chat = (contract.tg_chat_id or "").strip()
    row = TgMessage(contract_id=contract.id, kind=kind, text=text,
                    dedup_key=dedup_key or "")
    if not chat:
        row.ok, row.error = False, "O'quvchi botga ulanmagan"
    else:
        ok, res = _call("sendMessage", {
            "chat_id": chat, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True})
        row.ok = bool(ok)
        row.error = "" if ok else str(res)[:300]
    db.session.add(row)
    db.session.commit()
    return row


# ── Xabar matnlari ────────────────────────────────────────────────
def _money(v):
    return f"{float(v or 0):,.0f}".replace(",", " ")


def text_debt(contract, rest, days):
    name = contract.student.name.split()[0] if contract.student else "Assalom"
    kurs = contract.cohort.course.name if contract.cohort else ""
    kech = f" ({days} kun kechikdi)" if days else ""
    return (f"<b>{name}, salom!</b>\n\n"
            f"«{kurs}» kursi bo'yicha to'lovingiz kutilmoqda{kech}.\n"
            f"Qoldiq: <b>{_money(rest)} so'm</b>\n\n"
            f"To'lov qilgan bo'lsangiz — bu xabarni e'tiborsiz qoldiring. "
            f"Savol bo'lsa kuratorga yozing.")


def text_lesson(contract, sess):
    name = contract.student.name.split()[0] if contract.student else "Assalom"
    when = sess.date.strftime("%d.%m.%Y")
    topic = f"\nMavzu: <b>{sess.topic}</b>" if getattr(sess, "topic", "") else ""
    return (f"<b>{name}, salom!</b>\n\n"
            f"Ertaga darsimiz bor — {when}.{topic}\n\n"
            f"Kutamiz!")


def text_task(contract, assignment, days):
    name = contract.student.name.split()[0] if contract.student else "Assalom"
    when = assignment.due_date.strftime("%d.%m.%Y") if assignment.due_date else ""
    qoldi = "bugun oxirgi kun" if days == 0 else f"{days} kun qoldi"
    return (f"<b>{name}, salom!</b>\n\n"
            f"«{assignment.title}» vazifasini topshirish muddati: {when} "
            f"— {qoldi}.\n\n"
            f"Ilovadagi «Vazifalar» bo'limidan yuborishingiz mumkin.")


# ── Kimga nima yuborish kerak (yuborilmaydi, faqat ro'yxat) ────────
def pending(today=None, debt_days=1, lesson_ahead=1, task_ahead=2):
    """Bugun yuborilishi kerak bo'lgan eslatmalar ro'yxati.

    Hech nima yubormaydi — kurator avval ko'rib, keyin tugmani bosadi.
    """
    from models import (Assignment, Contract, LessonSession, Submission)
    today = today or localtime.today()
    out = []

    # 1) Muddati o'tgan to'lovlar
    for c in Contract.query.filter_by(status="active").all():
        rest = sum(max(0.0, (ln.amount or 0) - (ln.paid or 0))
                   for ln in c.lines if ln.due_date and ln.due_date <= today)
        if rest <= 0:
            continue
        days = max((ln.overdue_days() for ln in c.lines), default=0)
        if days < debt_days:
            continue
        out.append({"c": c, "kind": "qarz",
                    "text": text_debt(c, rest, days),
                    "key": f"qarz:{c.id}:{today.isoformat()}"})

    # 2) Ertangi darslar
    nxt = today + timedelta(days=lesson_ahead)
    for s in LessonSession.query.filter(LessonSession.date == nxt).all():
        for c in Contract.query.filter_by(cohort_id=s.cohort_id,
                                          status="active").all():
            out.append({"c": c, "kind": "dars", "text": text_lesson(c, s),
                        "key": f"dars:{s.id}:{c.id}"})

    # 3) Muddati yaqinlashgan vazifalar — topshirmaganlarga
    lim = today + timedelta(days=task_ahead)
    for a in Assignment.query.filter(Assignment.due_date != None,      # noqa: E711
                                     Assignment.due_date >= today,
                                     Assignment.due_date <= lim).all():
        done = {s.contract_id for s in
                Submission.query.filter_by(assignment_id=a.id).all()}
        for c in Contract.query.filter_by(cohort_id=a.cohort_id,
                                          status="active").all():
            if c.id in done:
                continue
            out.append({"c": c, "kind": "vazifa",
                        "text": text_task(c, a, (a.due_date - today).days),
                        "key": f"vazifa:{a.id}:{c.id}"})

    # Botga ulanmaganlar oxirida tursin — ular baribir ketmaydi
    out.sort(key=lambda x: (not (x["c"].tg_chat_id or "").strip(), x["kind"]))
    return out


def send_pending(items):
    """Ro'yxatdagilarni yuboradi. (yuborildi, o'tkazildi, xato)."""
    sent = skipped = failed = 0
    for it in items:
        row = send(it["c"], it["text"], it["kind"], it["key"])
        if row is None:
            skipped += 1
        elif row.ok:
            sent += 1
        else:
            failed += 1
    return sent, skipped, failed


# ── Webhook: o'quvchi «/start <kalit>» bosganda ────────────────────
def handle_update(update):
    """Telegram yuborgan xabarni ko'rib, o'quvchini bog'laydi."""
    from models import Contract
    msg = (update or {}).get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = str((msg.get("chat") or {}).get("id") or "")
    if not chat or not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    if not token:
        return None
    c = Contract.query.filter_by(portal_token=token).first()
    if not c:
        return None
    c.tg_chat_id = chat
    db.session.commit()
    name = c.student.name.split()[0] if c.student else "Assalom"
    _call("sendMessage", {"chat_id": chat, "parse_mode": "HTML", "text":
          f"<b>{name}, ulandingiz!</b>\n\nEndi to'lov, dars va vazifa "
          f"eslatmalari shu yerga keladi."})
    return c
