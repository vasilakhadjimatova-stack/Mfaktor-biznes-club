"""
O'quv bo'limi yadrosi — statistika, dropout risk-skoring, AI baholash.

Risk-skoring (qoidaviy v1, AI'siz ham ishlaydi) — signallar:
  • davomat: o'tkazilgan darslarga kelmaslik, ayniqsa oxirgi 2 dars
  • vazifalar: berilganlarni topshirmaslik
  • to'lov: muddati o'tgan bo'lib-to'lash qatorlari (InstallmentLine)
0–100 ball: 60+ yuqori xavf, 30–59 o'rta.

AI baholash: ANTHROPIC_API_KEY bo'lsa topshiriqni sotuv rubrikasi bo'yicha
tekshirib ball + izoh taklif qiladi; bo'lmasa modul to'liq qo'lda ishlaydi.
"""
import json
import logging
import os
import urllib.request
from datetime import date

from database import db

logger = logging.getLogger(__name__)

RISK_HIGH = 60
RISK_MID = 30

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = os.environ.get(
    "ANTHROPIC_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"
API_TIMEOUT_SEC = 90


# ──────────────────────────────────────────────────────────────────
# STATISTIKA (bo'lim markazi uchun)
# ──────────────────────────────────────────────────────────────────
def edu_stats():
    from models import Cohort, Contract, Submission
    today = date.today()
    running = Cohort.query.filter(Cohort.start_date <= today,
                                  Cohort.end_date >= today).count()
    active_students = Contract.query.filter_by(status="active").count()
    completed = Contract.query.filter_by(status="completed").count()
    pending_subs = Submission.query.filter_by(status="pending").count()
    at_risk = Contract.query.filter(
        Contract.status == "active",
        Contract.risk_score >= RISK_MID).count()
    return {
        "running_cohorts": running,
        "active_students": active_students,
        "completed": completed,
        "pending_subs": pending_subs,
        "at_risk": at_risk,
    }


# ──────────────────────────────────────────────────────────────────
# DROPOUT RISK-SKORING
# ──────────────────────────────────────────────────────────────────
def compute_risk(contract):
    """(score 0-100, reasons [str]) — saqlamaydi."""
    from models import LessonSession, LessonAttendance, Assignment, Submission
    score = 0
    reasons = []

    # 1) Davomat — o'tkazilgan darslar bo'yicha
    held = (LessonSession.query.filter_by(cohort_id=contract.cohort_id,
                                          held=True)
            .order_by(LessonSession.date).all())
    if held:
        marked = {a.session_id: a.status for a in
                  LessonAttendance.query.filter(
                      LessonAttendance.contract_id == contract.id,
                      LessonAttendance.session_id.in_(
                          [s.id for s in held])).all()}
        absents = sum(1 for s in held
                      if marked.get(s.id) in (None, "absent"))
        miss_pct = 100.0 * absents / len(held)
        if miss_pct >= 50:
            score += 45
            reasons.append(f"darslarning {miss_pct:.0f}% iga kelmagan")
        elif miss_pct >= 25:
            score += 25
            reasons.append(f"{absents} ta dars qoldirgan")
        elif absents >= 1:
            score += 10
        last2 = held[-2:]
        if len(last2) == 2 and all(
                marked.get(s.id) in (None, "absent") for s in last2):
            score += 20
            reasons.append("oxirgi 2 darsga kelmagan")

    # 2) Vazifalar — topshirmaganlik
    assign_ids = [a.id for a in Assignment.query.filter_by(
        cohort_id=contract.cohort_id).all()]
    if assign_ids:
        done = Submission.query.filter(
            Submission.contract_id == contract.id,
            Submission.assignment_id.in_(assign_ids)).count()
        missing = len(assign_ids) - done
        if missing >= 2:
            score += 20
            reasons.append(f"{missing} ta vazifa topshirmagan")
        elif missing == 1:
            score += 8

    # 3) To'lov — muddati o'tgan bo'lib-to'lash qatorlari
    overdue_days = max((ln.overdue_days() for ln in contract.lines),
                       default=0)
    if overdue_days > 14:
        score += 20
        reasons.append(f"to'lov {overdue_days} kun kechikkan")
    elif overdue_days > 0:
        score += 10
        reasons.append("to'lov kechikkan")

    return min(100, score), reasons


def refresh_cohort_risk(cohort_id):
    """Oqimning faol shartnomalari riskini qayta hisoblab saqlaydi."""
    from models import Contract
    rows = Contract.query.filter_by(cohort_id=cohort_id,
                                    status="active").all()
    for c in rows:
        s, r = compute_risk(c)
        c.risk_score = s
        c.risk_reasons = "; ".join(r)[:300]
    db.session.commit()
    return len(rows)


def risk_students(limit=15):
    from models import Contract
    return (Contract.query.filter(
        Contract.status == "active",
        Contract.risk_score >= RISK_MID)
        .order_by(Contract.risk_score.desc()).limit(limit).all())


# ──────────────────────────────────────────────────────────────────
# AI BAHOLASH
# ──────────────────────────────────────────────────────────────────
_GRADING_SYSTEM = (
    "Sen Mfaktor biznes maktabining sotuv kursi tekshiruvchisisan. Senga uy "
    "vazifasi sharti va o'quvchi javobi beriladi. FAQAT o'zbek tilida baholaysan.\n"
    "Rubrika: (1) shartga mosligi, (2) sotuv mantig'i to'g'riligi (ehtiyoj "
    "aniqlash, qiymat taklifi, e'tirozga ishlov, yopish), (3) amaliyligi, "
    "(4) ifoda ravonligi.\n"
    "Javobni QAT'IY JSON qilib qaytar: "
    '{"score": 0-100 butun son, "feedback": "2-4 jumlalik izoh: nima yaxshi, '
    'nimani aniq qanday yaxshilash kerak"}'
)


def ai_grade(assignment, submission_text, max_score=100):
    """AI birinchi qatlam bahosi: (score, feedback) yoki (None, "")."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    text = (submission_text or "").strip()
    if not api_key or not text:
        return None, ""
    user_msg = (
        f"VAZIFA: {assignment.title}\n"
        f"SHART: {(assignment.description or '')[:2000]}\n"
        f"MAKS BALL: {max_score}\n\n"
        f"O'QUVCHI JAVOBI:\n{text[:6000]}"
    )
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 500,
        "system": _GRADING_SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            ANTHROPIC_API_URL, data=body,
            headers={"x-api-key": api_key,
                     "anthropic-version": ANTHROPIC_VERSION,
                     "content-type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        raw = "\n".join(b.get("text", "") for b in data.get("content", [])
                        if b.get("type") == "text").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None, ""
        parsed = json.loads(raw[start:end + 1])
        score = max(0, min(int(max_score or 100), int(parsed.get("score"))))
        feedback = str(parsed.get("feedback") or "").strip()[:2000]
        return score, feedback
    except Exception as exc:
        logger.error(f"AI baholash xato: {exc}")
        return None, ""


# ──────────────────────────────────────────────────────────────────
# O'QUVCHI TARAQQIYOTI — davomat va vazifalar bir qarashda
# ──────────────────────────────────────────────────────────────────
def student_progress(contract, sessions=None, att_map=None, assignments=None):
    """Bitta o'quvchi: davomat foizi, vazifalar va o'rtacha ball.

    Ro'yxat sahifalarida har qator uchun alohida so'rov yubormaslik kerak —
    shuning uchun oqim bo'yicha tayyorlangan ma'lumot (sessions/att_map/
    assignments) tashqaridan berilishi mumkin.
    """
    from models import (LessonSession, LessonAttendance, Assignment,
                        Submission)
    if sessions is None:
        sessions = (LessonSession.query
                    .filter_by(cohort_id=contract.cohort_id, held=True).all())
    if att_map is None:
        att_map = {}
        if sessions:
            for a in LessonAttendance.query.filter(
                    LessonAttendance.contract_id == contract.id,
                    LessonAttendance.session_id.in_(
                        [s.id for s in sessions])).all():
                att_map[(a.session_id, a.contract_id)] = a.status
    if assignments is None:
        assignments = Assignment.query.filter_by(
            cohort_id=contract.cohort_id).all()

    held = [s for s in sessions if s.held]
    # «Keldi» va «Kechikdi» — bo'lgan hisoblanadi; «Sababli» foizni pasaytirmaydi
    counted = came = 0
    for s in held:
        st = att_map.get((s.id, contract.id))
        if st == "excused":
            continue
        counted += 1
        if st in ("present", "late"):
            came += 1
    att_pct = (came / counted * 100) if counted else None

    a_ids = [a.id for a in assignments]
    subs = []
    if a_ids:
        subs = Submission.query.filter(
            Submission.contract_id == contract.id,
            Submission.assignment_id.in_(a_ids)).all()
    graded = [s for s in subs if s.score is not None]
    return {
        "held": len(held), "came": came, "counted": counted,
        "att_pct": att_pct,
        "missed": counted - came,
        "assign_total": len(a_ids), "assign_done": len(subs),
        "avg_score": (sum(s.score for s in graded) / len(graded))
                     if graded else None,
    }


def refresh_all_risk(only_running=True):
    """Barcha (yoki faqat davom etayotgan) oqimlar riskini qayta hisoblaydi.

    Risk kundan kunga o'zgaradi — to'lov kechikishi o'sadi. Ilgari u faqat
    davomat saqlanganda yangilanardi, ya'ni hech kim davomat olmasa raqam
    eskirib qolardi. Endi bo'lim sahifasi ochilganda o'zi yangilanadi.
    """
    from models import Cohort
    q = Cohort.query
    if only_running:
        today = date.today()
        q = q.filter(Cohort.start_date <= today, Cohort.end_date >= today)
    n = 0
    for ch in q.all():
        n += refresh_cohort_risk(ch.id)
    return n


def contact_message(contract):
    """Xavf ostidagi o'quvchiga yuborish uchun tayyor, xushmuomala xabar."""
    name = (contract.student.name or "").split()[0] if contract.student.name \
        else "Assalomu alaykum"
    course = contract.cohort.course.name if contract.cohort else "kurs"
    reasons = (contract.risk_reasons or "").strip()
    body = [f"Assalomu alaykum, {name}!",
            f"«{course}» kursi bo'yicha aloqaga chiqyapmiz."]
    low = reasons.lower()
    if "kelmagan" in low or "qoldirgan" in low:
        body.append("Oxirgi darslarda ko'rinmadingiz — hammasi joyidami? "
                    "O'tkazib yuborilgan mavzularni yopishga yordam beramiz.")
    if "vazifa" in low:
        body.append("Bir nechta uy vazifasi topshirilmagan. Qiynalayotgan "
                    "joyingiz bo'lsa, ayting — birga ko'rib chiqamiz.")
    if "to'lov" in low or "tolov" in low:
        rest = contract.due_total()
        body.append(f"Shuningdek to'lov bo'yicha {rest:,.0f} so'm qoldiq bor. "
                    f"Qulay muddatni kelishib olsak bo'ladi."
                    .replace(",", " "))
    body.append("Javobingizni kutamiz. Mfaktor biznes maktabi")
    return "\n\n".join(body)


# ──────────────────────────────────────────────────────────────────
# O'QUVCHI KABINETI — parolsiz shaxsiy havola
# ──────────────────────────────────────────────────────────────────
def ensure_portal_token(contract):
    """Shartnomaga kabinet kaliti beradi (bo'lmasa yaratadi)."""
    import secrets as _s
    if not contract.portal_token:
        contract.portal_token = _s.token_urlsafe(24)
        db.session.commit()
    return contract.portal_token


def portal_data(contract):
    """O'quvchi o'z kabinetida ko'radigan hamma narsa.

    Ataylab faqat SHU o'quvchining ma'lumoti: boshqa o'quvchilar, guruh
    moliyasi yoki ichki izohlar ko'rinmaydi. Reytingda ham ismlar emas,
    faqat o'rin ko'rsatiladi.
    """
    from models import (Assignment, LessonSession, LessonAttendance,
                        Submission)
    ch = contract.cohort
    today = date.today()

    sessions = (LessonSession.query.filter_by(cohort_id=ch.id)
                .order_by(LessonSession.date).all())
    marks = {a.session_id: a.status for a in LessonAttendance.query.filter(
        LessonAttendance.contract_id == contract.id,
        LessonAttendance.session_id.in_([s.id for s in sessions])).all()} \
        if sessions else {}
    lessons = [{"s": s, "status": marks.get(s.id) if s.held else None,
                "past": s.date <= today} for s in sessions]

    assigns = (Assignment.query.filter_by(cohort_id=ch.id)
               .order_by(Assignment.created_at.desc()).all())
    subs = {x.assignment_id: x for x in Submission.query.filter(
        Submission.contract_id == contract.id,
        Submission.assignment_id.in_([a.id for a in assigns])).all()} \
        if assigns else {}
    tasks = []
    for a in assigns:
        sub = subs.get(a.id)
        overdue = bool(a.due_date and a.due_date < today and not sub)
        tasks.append({"a": a, "sub": sub, "overdue": overdue,
                      "done": sub is not None,
                      "graded": bool(sub and sub.status == "graded")})

    prog = student_progress(contract, sessions, {
        (sid, contract.id): st for sid, st in marks.items()}, assigns)

    # to'lov: faqat o'z shartnomasi bo'yicha
    nxt, overdue_amt = None, 0.0
    for ln in contract.lines:
        rest = max(ln.amount - ln.paid, 0.0)
        if rest <= 0.01:
            continue
        if ln.due_date < today:
            overdue_amt += rest
        elif nxt is None or ln.due_date < nxt["date"]:
            nxt = {"date": ln.due_date, "amount": rest,
                   "days": (ln.due_date - today).days}

    return {"c": contract, "ch": ch, "lessons": lessons, "tasks": tasks,
            "prog": prog, "next_pay": nxt, "overdue": overdue_amt,
            "paid": contract.paid_total(), "due": contract.due_total(),
            "rank": my_rank(contract)}


def leaderboard(cohort_id, limit=None):
    """Oqim reytingi: o'rtacha ball va davomat bo'yicha.

    Ball = o'rtacha baho × 0.7 + davomat foizi × 0.3 — faqat o'qishga
    tegishli ko'rsatkichlar, to'lov bu yerga umuman aralashmaydi.
    """
    from models import Assignment, Contract, LessonSession, LessonAttendance
    rows = Contract.query.filter_by(cohort_id=cohort_id,
                                    status="active").all()
    if not rows:
        return []
    sessions = LessonSession.query.filter_by(cohort_id=cohort_id,
                                             held=True).all()
    att = {}
    if sessions:
        for a in LessonAttendance.query.filter(
                LessonAttendance.session_id.in_([s.id for s in sessions])).all():
            att[(a.session_id, a.contract_id)] = a.status
    assigns = Assignment.query.filter_by(cohort_id=cohort_id).all()

    out = []
    for c in rows:
        p = student_progress(c, sessions, att, assigns)
        score = (p["avg_score"] or 0) * 0.7 + (p["att_pct"] or 0) * 0.3
        out.append({"c": c, "name": c.student.name,
                    "avg": p["avg_score"], "att": p["att_pct"],
                    "done": p["assign_done"], "total": p["assign_total"],
                    "score": round(score, 1)})
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out, 1):
        r["place"] = i
    return out[:limit] if limit else out


def my_rank(contract):
    """O'quvchining o'z oqimidagi o'rni: (o'rin, jami)."""
    board = leaderboard(contract.cohort_id)
    for r in board:
        if r["c"].id == contract.id:
            return {"place": r["place"], "of": len(board),
                    "score": r["score"]}
    return None
