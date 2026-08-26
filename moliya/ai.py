"""AI yordamchi — moliya ma'lumotlari bo'yicha savol-javob.

Qanday ishlaydi: har so'rovda bazadan ixcham «suratga olish» (hamyonlar,
oy oqimi, qarzdorlar, navbat) yig'iladi va Claude'ga tizim matni bilan
beriladi. Model faqat shu ma'lumotga tayanib o'zbekcha javob qaytaradi.

Kalit: ANTHROPIC_API_KEY muhit o'zgaruvchisi yoki Sozlamalarda kiritilgan
qiymat (AppSetting «anthropic_key»). Kalitsiz sahifa yo'riqnoma ko'rsatadi.

Tizim matni keshlanadi (prompt caching): barqaror qism birinchi blokda
cache_control bilan, o'zgaruvchan surат undan KEYIN — shунda har suhbatda
faqat surат qayta hisoblanadi.
"""
import os
from datetime import date

import localtime

from database import db

MODEL = os.environ.get("AI_MODEL", "claude-opus-5")

SYSTEM = """Sen — «Mfaktor biznes maktabi» kompaniyasining moliya bo'limi \
yordamchisisan. Dastur nomi: Mfaktor Moliya. Foydalanuvchilar: direktor va \
buxgalter. Til: faqat o'zbek tilida (lotin alifbosi) javob ber; moliya \
atamalari ruscha ko'rinishda bo'lsa (ДДС, статья kabi) o'z holicha qoldir.

Vazifang: quyida beriladigan JORIY MA'LUMOTLAR asosida savollarga aniq, \
qisqa va foydali javob berish. Qoidalar:
1. Faqat berilgan ma'lumotga tayanib javob ber. Ma'lumotda yo'q narsani \
taxmin qilma — «bu ma'lumot menга berilmagan, [sahifa nomi] sahifasidan \
qarang» deb ayt.
2. Summalarni 1 234 567 ko'rinishida, ming ajratib yoz; valyuta — so'm \
(agar $ deb belgilangan bo'lmasa).
3. Hisob-kitob so'ralsa (foiz, farq, ulush) — hisobla va qisqacha qanday \
chiqqanini ko'rsat.
4. Javob suhbat ohangida, lekin ixcham bo'lsin: avval javobning o'zi, \
keyin kerak bo'lsa 2-3 qator izoh. Ro'yxat so'ralganda jadval yoki \
ro'yxat ishlatsa bo'ladi.
5. Dastur bo'limlari (kerak bo'lsa yo'naltirish uchun): Dashboard, Kassa \
(tranzaksiyalar), ДДС данные (kiritish), To'lovlar navbati, Shartnomalar, \
Qarzdorlik, To'lov taqvimi, O'tkazmalar, Launch-hisob, Tahlillar, KPI, \
Sozlamalar.
6. Moliyaviy maslahat so'ralsa — ma'lumotdagi raqamlarga tayanib fikr \
bildir, lekin bu rasmiy audit emasligini bir og'iz eslat.
7. Ma'lumotlar maxfiy — ular haqida faqat shu suhbat ichida gapir."""


def api_key():
    """Kalit: avval muhit o'zgaruvchisi, keyin sozlamalardagi qiymat."""
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env
    from models import AppSetting
    try:
        row = db.session.get(AppSetting, "anthropic_key")
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        return ""
    return (row.value or "").strip() if row else ""


def save_key(value):
    from models import AppSetting
    row = db.session.get(AppSetting, "anthropic_key")
    if row is None:
        row = AppSetting(key="anthropic_key")
        db.session.add(row)
    row.value = (value or "").strip()
    db.session.commit()


def _grp(v):
    return f"{round(v):,}".replace(",", " ")


def snapshot():
    """Bazadan ixcham holat — modelga beriladigan joriy ma'lumot."""
    import core
    from models import Cohort, Contract, DdsRow

    today = localtime.today()
    lines = [f"Bugun: {today.isoformat()}"]
    skipped = []       # ma'lumot olinmagan bo'limlar — modelга ochiq aytamiz

    try:
        balances, total = core.wallet_balances()
        lines.append(f"\nHAMYONLAR (jami {_grp(total)} so'm):")
        for r in balances:
            lines.append(f"  {r['wallet'].name}: {_grp(r['balance'])}")
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        skipped.append("hamyonlar")

    try:
        cf = core.month_cashflow(today.year, today.month)
        lines.append(f"\nSHU OY ({today.month:02d}.{today.year}): "
                     f"kirim {_grp(cf['income_total'])}, "
                     f"chiqim {_grp(cf['expense_total'])}, "
                     f"natija {_grp(cf['net'])}")
        lines.append("  Kirim statyalari: " + "; ".join(
            f"{k} {_grp(v)}" for k, v in list(cf["income"].items())[:8]))
        lines.append("  Chiqim statyalari: " + "; ".join(
            f"{k} {_grp(v)}" for k, v in list(cf["expense"].items())[:10]))
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        skipped.append("oy oqimi")

    try:
        overdue = core.overdue_lines()
        tot = sum(r["line"].amount - r["line"].paid for r in overdue)
        lines.append(f"\nKECHIKKAN TO'LOVLAR: {len(overdue)} ta qator, "
                     f"jami {_grp(tot)} so'm")
        for r in overdue[:12]:
            rest = r["line"].amount - r["line"].paid
            lines.append(f"  {r['contract'].student.name} "
                         f"({r['contract'].cohort.name}): {_grp(rest)}, "
                         f"muddat {r['line'].due_date.isoformat()}")
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        skipped.append("kechikkan to'lovlar")

    try:
        active = Contract.query.filter_by(status="active").count()
        cohorts = Cohort.query.count()
        lines.append(f"\nSHARTNOMALAR: {active} ta faol, {cohorts} ta oqim")
        for c in Cohort.query.order_by(Cohort.id.desc()).limit(6).all():
            n = Contract.query.filter_by(cohort_id=c.id,
                                         status="active").count()
            paid = sum(x.paid_total() for x in
                       Contract.query.filter_by(cohort_id=c.id).all())
            lines.append(f"  {c.name}: {n} ta faol shartnoma, "
                         f"to'langan {_grp(paid)}")
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        skipped.append("shartnomalar")

    try:
        # AYNAN mijoz to'lovi navbati — hamma «none» qatorni sanamaymiz
        # (xarajat, o'tkazma, Б2Б ham «none» edi → son o'nlab barobar oshardi)
        import matching
        open_q = matching.open_count()
        lines.append(f"\nTo'lovlar navbatida tanilmagan mijoz to'lovi: "
                     f"{open_q} ta")
    except Exception:                                       # noqa: BLE001
        db.session.rollback()
        skipped.append("to'lovlar navbati")

    if skipped:
        lines.append("\nDIQQAT: quyidagi bo'limlar ma'lumoti shu so'rovda "
                     "olinmadi (vaqtinchalik xatolik): " + ", ".join(skipped) +
                     ". Bu bo'limlar bo'yicha savolga «hozir ma'lumot "
                     "olinmadi, birozdan keyin urinib ko'ring» deb javob ber.")
    return "\n".join(lines)


def chat(messages):
    """Suhbat: (javob_matni, xato_matni) qaytaradi."""
    key = api_key()
    if not key:
        return None, ("API kalit kiritilmagan — Sozlamalar sahifasida "
                      "«AI yordamchi» bo'limiga kalit kiriting.")

    import anthropic
    client = anthropic.Anthropic(api_key=key, timeout=90.0, max_retries=1)

    system = [
        {"type": "text", "text": SYSTEM,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "JORIY MA'LUMOTLAR:\n" + snapshot()},
    ]
    msgs = []
    for m in messages[-16:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()[:4000]
        if text:
            msgs.append({"role": role, "content": text})
    if not msgs or msgs[-1]["role"] != "user":
        return None, "Savol topilmadi"

    try:
        try:
            # xavfsizlik klassifikatori rad etsa, so'rov avtomatik zaxira
            # modelda qayta bajariladi (server-side fallback)
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=4096,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system, messages=msgs)
        except (TypeError, anthropic.BadRequestError):
            # eski SDK yoki beta qabul qilinmadi — oddiy yo'l
            resp = client.messages.create(
                model=MODEL, max_tokens=4096,
                system=system, messages=msgs)
    except anthropic.AuthenticationError:
        return None, "API kalit noto'g'ri — Sozlamalardan tekshiring."
    except anthropic.RateLimitError:
        return None, "So'rovlar cheklovi — bir daqiqadan keyin urinib ko'ring."
    except anthropic.APIStatusError as e:
        return None, f"Xizmat xatosi ({e.status_code}) — keyinroq urinib ko'ring."
    except anthropic.APIConnectionError:
        return None, "Tarmoq xatosi — internet aloqasini tekshiring."

    if resp.stop_reason == "refusal":
        return None, "Bu savolga javob berib bo'lmadi — boshqacha so'rab ko'ring."
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        return None, "Bo'sh javob keldi — qayta urinib ko'ring."
    return text, ""
