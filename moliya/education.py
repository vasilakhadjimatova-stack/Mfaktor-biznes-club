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
