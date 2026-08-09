"""
O'quv bo'limi yadrosi — statistika, dropout risk-skoring, AI baholash.

Risk-skoring (v1, qoidaviy — AI'siz ham ishlaydi):
  davomat + vazifa topshirish + to'lov qarzdorligi signallaridan 0–100 ball.
  60+ → yuqori xavf (qizil), 30–59 → o'rta (sariq), <30 → past.

AI baholash: ANTHROPIC_API_KEY sozlangan bo'lsa, topshiriqni rubrika bo'yicha
baholab ball + izoh taklif qiladi. Sozlanmagan bo'lsa modul to'liq qo'lda
ishlayveradi (AI — qo'shimcha qatlam, majburiyat emas).
"""
import json
import logging
import os
import urllib.request

from database import db

logger = logging.getLogger(__name__)

RISK_HIGH = 60
RISK_MID = 30

# Anthropic API (SDK'siz, urllib bilan)
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL",
                                 "claude-sonnet-5").strip() or "claude-sonnet-5"
API_TIMEOUT_SEC = 90


# ──────────────────────────────────────────────────────────────────
# STATISTIKA (dashboard uchun)
# ──────────────────────────────────────────────────────────────────
def edu_stats():
    """O'quv bo'limi asosiy raqamlari — bitta so'rov to'plami."""
    from models.education import (Cohort, Enrollment, Submission)
    active_cohorts = Cohort.query.filter_by(status="active").count()
    active_students = Enrollment.query.filter_by(status="active").count()
    finished = Enrollment.query.filter_by(status="finished").count()
    dropped = Enrollment.query.filter_by(status="dropped").count()
    pending_subs = Submission.query.filter_by(status="pending").count()
    debt_total = 0.0
    debtors = 0
    for e in Enrollment.query.filter_by(status="active").all():
        d = e.debt
        if d > 0:
            debt_total += d
            debtors += 1
    total_closed = finished + dropped
    completion_rate = round(100.0 * finished / total_closed) if total_closed else None
    return {
        "active_cohorts": active_cohorts,
        "active_students": active_students,
        "finished": finished,
        "dropped": dropped,
        "completion_rate": completion_rate,
        "pending_subs": pending_subs,
        "debt_total": debt_total,
        "debtors": debtors,
    }


# ──────────────────────────────────────────────────────────────────
# DROPOUT RISK-SKORING (qoidaviy v1)
# ──────────────────────────────────────────────────────────────────
def compute_risk(enrollment):
    """Bitta o'quvchi uchun risk ballini hisoblaydi (saqlamaydi).

    Qaytaradi: (score 0-100, reasons [str])
    """
    from models.education import LessonSession, StudentAttendance, Assignment
    score = 0
    reasons = []

    # 1) Davomat — o'tkazilgan darslarga nisbatan (eng og'ir signal)
    held_ids = [s.id for s in LessonSession.query.filter_by(
        cohort_id=enrollment.cohort_id, held=True).all()]
    if held_ids:
        rows = StudentAttendance.query.filter(
            StudentAttendance.enrollment_id == enrollment.id,
            StudentAttendance.session_id.in_(held_ids)).all()
        marked = {r.session_id: r.status for r in rows}
        absents = sum(1 for sid in held_ids
                      if marked.get(sid) in (None, "absent"))
        miss_pct = 100.0 * absents / len(held_ids)
        if miss_pct >= 50:
            score += 45
            reasons.append(f"darslarning {miss_pct:.0f}% iga kelmagan")
        elif miss_pct >= 25:
            score += 25
            reasons.append(f"{absents} ta dars qoldirgan")
        elif absents >= 1:
            score += 10
        # Ketma-ket oxirgi 2 dars kelmagan — kuchli ogohlantirish
        last2 = held_ids[-2:]
        if len(last2) == 2 and all(
                marked.get(sid) in (None, "absent") for sid in last2):
            score += 20
            reasons.append("oxirgi 2 darsga kelmagan")

    # 2) Vazifalar — berilganlarga nisbatan topshirmaganlik
    assign_ids = [a.id for a in Assignment.query.filter_by(
        cohort_id=enrollment.cohort_id).all()]
    if assign_ids:
        done = enrollment.submissions.count()
        missing = len(assign_ids) - done
        if missing >= 2:
            score += 20
            reasons.append(f"{missing} ta vazifa topshirmagan")
        elif missing == 1:
            score += 8

    # 3) To'lov qarzdorligi
    if enrollment.debt > 0:
        score += 15
        reasons.append("to'lov qarzdorligi bor")

    return min(100, score), reasons


def refresh_cohort_risk(cohort_id):
    """Guruhning barcha faol o'quvchilari risk ballini qayta hisoblab saqlaydi."""
    from models.education import Enrollment
    rows = Enrollment.query.filter_by(cohort_id=cohort_id,
                                      status="active").all()
    for e in rows:
        score, reasons = compute_risk(e)
        e.risk_score = score
        e.risk_reasons = "; ".join(reasons)[:300]
    db.session.commit()
    return len(rows)


def risk_students(limit=15):
    """Eng xavfli faol o'quvchilar — dashboard «diqqat» ro'yxati."""
    from models.education import Enrollment
    return (Enrollment.query.filter_by(status="active")
            .filter(Enrollment.risk_score >= RISK_MID)
            .order_by(Enrollment.risk_score.desc())
            .limit(limit).all())


# ──────────────────────────────────────────────────────────────────
# AI BAHOLASH — topshiriqni rubrika bo'yicha tekshirish
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
    """AI birinchi qatlam bahosi. Qaytaradi (score, feedback) yoki (None, "").

    Kalit sozlanmagan / xato bo'lsa jimgina (None, "") — oqim qo'lda davom etadi.
    """
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
        # JSON'ni matn ichidan ajratib olish (model qo'shimcha matn yozsa ham)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None, ""
        parsed = json.loads(raw[start:end + 1])
        score = int(parsed.get("score"))
        score = max(0, min(int(max_score or 100), score))
        feedback = str(parsed.get("feedback") or "").strip()[:2000]
        return score, feedback
    except Exception as exc:
        logger.error(f"AI baholash xato: {exc}")
        return None, ""
