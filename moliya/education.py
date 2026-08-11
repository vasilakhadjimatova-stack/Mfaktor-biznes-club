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
import re
import urllib.request
from datetime import date, datetime

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


# ──────────────────────────────────────────────────────────────────
# VIDEO DARSLIKLAR — o'quvchi ilovasi kontenti
# ──────────────────────────────────────────────────────────────────
def embed_url(url):
    """Havolani ilova ichida ochiladigan pleyer manziliga aylantiradi.

    Video o'z serverimizda saqlanmaydi (trafik qimmat) — YouTube/Vimeo/
    Drive havolasi beriladi, ilova uni o'z ichida ko'rsatadi.
    Tanilmagan havola bo'lsa None qaytadi — u oddiy tugma bo'lib chiqadi.
    """
    u = (url or "").strip()
    if not u:
        return None
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))"
                   r"([A-Za-z0-9_-]{6,})", u)
    if m:
        # enablejsapi — ilova pleyerdan «hozir nechinchi soniyada» deb
        # so'ray olishi uchun; ko'rish analitikasi shunga asoslangan.
        return (f"https://www.youtube.com/embed/{m.group(1)}"
                f"?rel=0&modestbranding=1&enablejsapi=1&playsinline=1")
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", u)
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}"
    m = re.search(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)", u)
    if m:
        return f"https://drive.google.com/file/d/{m.group(1)}/preview"
    if u.lower().endswith((".mp4", ".webm", ".m3u8")):
        return u                      # to'g'ridan-to'g'ri video fayl
    return None


def course_content(contract):
    """O'quvchining kursi bo'yicha modullar, darslar, elementlar va qulf."""
    from models import LessonItem, LessonView, VideoModule
    course_id = contract.cohort.course_id if contract.cohort else None
    mods = (VideoModule.query.filter_by(course_id=course_id)
            .order_by(VideoModule.sort, VideoModule.id).all()) if course_id else []
    lids = [l.id for m in mods for l in m.lessons]
    seen = set()
    if lids:
        seen = {v.lesson_id for v in LessonView.query.filter(
            LessonView.contract_id == contract.id,
            LessonView.lesson_id.in_(lids), LessonView.done.is_(True)).all()}
    item_ids = [i.id for i in LessonItem.query.filter(
        LessonItem.lesson_id.in_(lids)).all()] if lids else []
    watch = watch_map(contract.id, item_ids)
    today = date.today()

    out, total, done, locked_n = [], 0, 0, 0
    for m in mods:
        rows = []
        for l in m.lessons:
            ok = l.id in seen
            lock, odate = lesson_locked(l, contract.cohort, today)
            total += 1
            done += 1 if ok else 0
            locked_n += 1 if lock else 0
            vids = [i for i in l.items if i.kind == "video"]
            pcts = [round(watch[i.id].pct) for i in vids if i.id in watch]
            rows.append({
                "l": l, "done": ok, "locked": lock, "open_at": odate,
                "pct": round(sum(pcts) / len(vids)) if vids and pcts else 0,
                "n_items": len(l.items),
                "minutes": sum(i.minutes or 0 for i in vids),
                "has_quiz": any(i.kind == "test" for i in l.items),
            })
        out.append({"m": m, "lessons": rows,
                    "done": sum(1 for r in rows if r["done"]),
                    "total": len(rows)})
    nxt = None
    for g in out:
        for r in g["lessons"]:
            if not r["done"] and not r["locked"]:
                nxt = {"l": r["l"], "m": g["m"]}
                break
        if nxt:
            break
    return {"modules": out, "total": total, "done": done,
            "pct": (done / total * 100) if total else 0, "next": nxt,
            "seen": seen, "watch": watch, "locked": locked_n}


def mark_view(contract, lesson, done=True):
    """Darsni «ko'rildi» deb belgilash (yoki bekor qilish)."""
    from models import LessonView
    row = LessonView.query.filter_by(lesson_id=lesson.id,
                                     contract_id=contract.id).first()
    if row is None:
        row = LessonView(lesson_id=lesson.id, contract_id=contract.id)
        db.session.add(row)
    row.done = bool(done)
    row.viewed_at = datetime.utcnow()
    db.session.commit()
    return row


# ──────────────────────────────────────────────────────────────────
# VIDEO KO'RISH ANALITIKASI
# ──────────────────────────────────────────────────────────────────
WATCH_DONE_PCT = 85          # shu foizdan oshsa dars «ko'rildi» bo'ladi
_GAP = 1.5                   # shundan kichik uzilish — bir oraliq deb olinadi


def merge_spans(spans, duration=0.0):
    """Oraliqlarni tartiblab birlashtiradi: [[0,10],[8,20]] -> [[0,20]].

    Foizni oxirgi nuqtadan emas, aynan shu birlashgan oraliqlardan
    hisoblaymiz — videoni sudrab o'tgan o'quvchi 100% olmaydi.
    """
    clean = []
    for sp in spans or []:
        try:
            a, b = float(sp[0]), float(sp[1])
        except (TypeError, ValueError, IndexError):
            continue
        if b < a:
            a, b = b, a
        a = max(0.0, a)
        if duration and duration > 0:
            b = min(b, duration)
        if b - a >= 0.5:                       # juda qisqa bo'lagi hisobmas
            clean.append([round(a, 1), round(b, 1)])
    if not clean:
        return []
    clean.sort()
    out = [clean[0]]
    for a, b in clean[1:]:
        if a <= out[-1][1] + _GAP:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def spans_seconds(spans):
    return round(sum(b - a for a, b in spans), 1)


def record_watch(contract, item, spans, duration=0.0, pos=0.0, opened=False):
    """Ilovadan kelgan oraliqlarni saqlaydi va foizni qayta hisoblaydi.

    Hisob dars emas, ELEMENT bo'yicha yuritiladi — bitta darsda bir
    nechta video bo'lishi mumkin.
    """
    from models import LessonWatch
    row = LessonWatch.query.filter_by(item_id=item.id,
                                      contract_id=contract.id).first()
    if row is None:
        row = LessonWatch(item_id=item.id, lesson_id=item.lesson_id,
                          contract_id=contract.id, covered="[]")
        db.session.add(row)
    if duration and duration > 0:
        row.duration = round(float(duration), 1)
    try:
        old_spans = json.loads(row.covered or "[]")
    except ValueError:
        old_spans = []
    merged = merge_spans(list(old_spans) + list(spans or []), row.duration)
    row.covered = json.dumps(merged)
    row.seconds = spans_seconds(merged)
    row.pct = round(100.0 * row.seconds / row.duration, 1) if row.duration else 0.0
    row.max_pos = max(row.max_pos or 0.0, float(pos or 0.0),
                      merged[-1][1] if merged else 0.0)
    if opened:
        row.opens = (row.opens or 0) + 1
    row.last_at = datetime.utcnow()
    db.session.commit()
    sync_lesson_done(contract, item.lesson)
    return row


def sync_lesson_done(contract, lesson):
    """Darsning barcha majburiy elementlari bajarilgan bo'lsa — belgilaydi.

    Majburiy deb video (85% ko'rilishi) va test (o'tish bali) olinadi.
    Matn va material — ma'lumot uchun, ular belgilashga ta'sir qilmaydi.
    """
    from models import LessonView
    st = lesson_state(contract, lesson)
    if st["required"] == 0:
        return None
    v = LessonView.query.filter_by(lesson_id=lesson.id,
                                   contract_id=contract.id).first()
    done = st["done_required"] >= st["required"]
    if done and v is None:
        db.session.add(LessonView(lesson_id=lesson.id,
                                  contract_id=contract.id, done=True))
        db.session.commit()
    elif done and not v.done:
        v.done = True
        db.session.commit()
    return done


def lesson_state(contract, lesson):
    """Darsning har bir elementi qanday holatda — ilova va kurator uchun."""
    from models import LessonWatch, Quiz
    out, required, done_required = [], 0, 0
    for it in lesson.items:
        st = {"it": it, "done": False, "pct": 0, "resume": 0.0, "quiz": None,
              "best": None}
        if it.kind == "video":
            w = LessonWatch.query.filter_by(item_id=it.id,
                                            contract_id=contract.id).first()
            st["pct"] = round(w.pct) if w else 0
            st["resume"] = (w.max_pos or 0) if w else 0
            st["done"] = bool(w and (w.pct or 0) >= WATCH_DONE_PCT)
            required += 1
            done_required += 1 if st["done"] else 0
        elif it.kind == "test":
            q = Quiz.query.filter_by(item_id=it.id).first()
            st["quiz"] = q
            if q is not None:
                best = quiz_best(q.id, contract.id)
                st["best"] = best
                st["done"] = bool(best and best.passed)
                required += 1
                done_required += 1 if st["done"] else 0
        out.append(st)
    return {"rows": out, "required": required,
            "done_required": done_required}


def watch_map(contract_id, item_ids):
    """{element_id: yozuv} — ilovada har video yonida foiz ko'rsatish uchun."""
    from models import LessonWatch
    if not item_ids:
        return {}
    rows = LessonWatch.query.filter(
        LessonWatch.contract_id == contract_id,
        LessonWatch.item_id.in_(item_ids)).all()
    return {r.item_id: r for r in rows}


RETENTION_BUCKETS = 20


def lesson_watch_stats(item):
    """Bitta video elementi bo'yicha: kim qancha ko'rgan, qayerda tashlagan.

    «retention» — videoni 20 bo'lakka bo'lib, har bo'lakni nechta o'quvchi
    ko'rgani. Egri chiziq keskin tushgan joy — darsning zaif nuqtasi.
    """
    from models import Cohort, Contract, LessonWatch
    rows = (LessonWatch.query.filter_by(item_id=item.id)
            .order_by(LessonWatch.pct.desc()).all())
    rows = [r for r in rows if r.contract is not None]
    dur = max([r.duration or 0 for r in rows], default=0.0)

    buckets = [0] * RETENTION_BUCKETS
    for r in rows:
        if not dur:
            continue
        try:
            spans = json.loads(r.covered or "[]")
        except ValueError:
            spans = []
        for i in range(RETENTION_BUCKETS):
            lo = dur * i / RETENTION_BUCKETS
            hi = dur * (i + 1) / RETENTION_BUCKETS
            if any(a < hi and b > lo for a, b in spans):
                buckets[i] += 1

    started = len(rows)
    finished = sum(1 for r in rows if (r.pct or 0) >= WATCH_DONE_PCT)
    avg = round(sum(r.pct or 0 for r in rows) / started, 1) if started else 0.0

    drop_i, drop_n = None, 0
    for i in range(1, RETENTION_BUCKETS):
        d = buckets[i - 1] - buckets[i]
        if d > drop_n:
            drop_i, drop_n = i, d
    drop_at = (dur * drop_i / RETENTION_BUCKETS) if (drop_i and dur) else None

    seen_ids = {r.contract_id for r in rows}
    cohort_ids = [ch.id for ch in Cohort.query.filter_by(
        course_id=item.lesson.module.course_id).all()]
    never = []
    if cohort_ids:
        q = Contract.query.filter(Contract.status == "active",
                                  Contract.cohort_id.in_(cohort_ids))
        if seen_ids:
            q = q.filter(~Contract.id.in_(seen_ids))
        never = q.all()

    return {"rows": rows, "duration": dur, "buckets": buckets,
            "started": started, "finished": finished, "avg": avg,
            "drop_at": drop_at, "drop_n": drop_n, "never": never,
            "max_bucket": max(buckets or [0])}


def course_watch_summary(course_id):
    """{element_id: {'started','avg'}} — darsliklar jadvalida ko'rsatish uchun."""
    from models import LessonItem, LessonWatch, VideoLesson, VideoModule
    ids = [i.id for i in LessonItem.query.join(VideoLesson).join(VideoModule)
           .filter(VideoModule.course_id == course_id,
                   LessonItem.kind == "video").all()]
    if not ids:
        return {}
    out = {}
    for r in LessonWatch.query.filter(LessonWatch.item_id.in_(ids)).all():
        d = out.setdefault(r.item_id, {"started": 0, "sum": 0.0})
        d["started"] += 1
        d["sum"] += (r.pct or 0)
    for d in out.values():
        d["avg"] = round(d["sum"] / d["started"], 1) if d["started"] else 0.0
    return out


def fmt_sec(s):
    """123.4 -> «2:03»"""
    try:
        s = int(round(float(s)))
    except (TypeError, ValueError):
        return "—"
    return f"{s // 60}:{s % 60:02d}"


# ──────────────────────────────────────────────────────────────────
# BOSQICHMA-BOSQICH OCHILISH
# ──────────────────────────────────────────────────────────────────
def lesson_open_date(lesson, cohort):
    """Dars qaysi kundan ochiladi (oqim boshlanishiga nisbatan)."""
    from datetime import timedelta
    d = int(lesson.open_day or 0)
    if d <= 0 or cohort is None or cohort.start_date is None:
        return None
    return cohort.start_date + timedelta(days=d)


def lesson_locked(lesson, cohort, today=None):
    """(qulflangan_mi, ochilish_sanasi)."""
    od = lesson_open_date(lesson, cohort)
    if od is None:
        return False, None
    return (today or date.today()) < od, od


# ──────────────────────────────────────────────────────────────────
# TESTLAR
# ──────────────────────────────────────────────────────────────────
def grade_quiz(quiz, contract, chosen):
    """chosen = {savol_id: variant_id}. Tekshiradi va urinishni saqlaydi."""
    from models import QuizAttempt
    qs = list(quiz.questions)
    if not qs:
        return None
    right = 0
    for q in qs:
        pick = chosen.get(str(q.id)) or chosen.get(q.id)
        try:
            pick = int(pick)
        except (TypeError, ValueError):
            continue
        if any(o.id == pick and o.is_correct for o in q.options):
            right += 1
    score = int(round(100.0 * right / len(qs)))
    att = QuizAttempt(quiz_id=quiz.id, contract_id=contract.id, score=score,
                      passed=score >= (quiz.pass_score or 70),
                      answers=json.dumps({str(k): v for k, v in chosen.items()}))
    db.session.add(att)
    db.session.commit()
    return att


def quiz_best(quiz_id, contract_id):
    """O'quvchining shu testdagi eng yaxshi urinishi."""
    from models import QuizAttempt
    return (QuizAttempt.query.filter_by(quiz_id=quiz_id,
                                        contract_id=contract_id)
            .order_by(QuizAttempt.score.desc()).first())


def quiz_stats(quiz):
    """Kurator uchun: nechta urinish, o'rtacha ball, qaysi savol qiyin."""
    from models import QuizAttempt
    atts = QuizAttempt.query.filter_by(quiz_id=quiz.id).all()
    best = {}
    for a in atts:
        cur = best.get(a.contract_id)
        if cur is None or (a.score or 0) > (cur.score or 0):
            best[a.contract_id] = a
    people = list(best.values())
    avg = round(sum(a.score or 0 for a in people) / len(people), 1) if people else 0.0
    passed = sum(1 for a in people if a.passed)

    # Savol bo'yicha to'g'ri javob ulushi — past ko'rsatkich «tushunilmagan»
    hard = []
    for q in quiz.questions:
        ok = tot = 0
        right_ids = {o.id for o in q.options if o.is_correct}
        for a in people:
            try:
                ans = json.loads(a.answers or "{}")
            except ValueError:
                continue
            if str(q.id) not in ans:
                continue
            tot += 1
            try:
                if int(ans[str(q.id)]) in right_ids:
                    ok += 1
            except (TypeError, ValueError):
                pass
        hard.append({"q": q, "ok": ok, "total": tot,
                     "pct": round(100.0 * ok / tot) if tot else None})
    hard.sort(key=lambda x: (x["pct"] is None, x["pct"] or 0))
    return {"attempts": len(atts), "people": len(people), "avg": avg,
            "passed": passed, "best": people, "hard": hard}


# ──────────────────────────────────────────────────────────────────
# KURATOR ISH NAVBATI
# ──────────────────────────────────────────────────────────────────
# Bo'lim sahifasi avval faqat raqam ko'rsatardi: «12 faol o'quvchi,
# 3 tekshirilmagan». Kurator bundan nima qilish kerakligini bilmasdi.
# Quyidagi funksiya aynan shuni beradi — bugun qo'l tegishi kerak
# bo'lgan ishlar, eng shoshilinchidan boshlab.

def curator_queue(today=None):
    from models import (Assignment, Cohort, Contract, LessonSession,
                        Submission)
    today = today or date.today()
    items = []

    # 1) Davomat olinmagan darslar — eng shoshilinchi, chunki kechiksa
    #    o'quvchi kelgan-kelmagani umuman yozilmay qoladi.
    late = (LessonSession.query
            .filter(LessonSession.held.is_(False), LessonSession.date <= today)
            .order_by(LessonSession.date).all())
    for s in late:
        d = (today - s.date).days
        items.append({
            "kind": "davomat", "urgent": d >= 1,
            "title": "Davomat olinmagan",
            "what": f"{s.cohort.course.name} — {s.date.strftime('%d.%m')}"
                    + (f" · {s.topic}" if s.topic else ""),
            "note": "bugungi dars" if d == 0 else f"{d} kun kechikdi",
            "url": f"/oquv/cohort/{s.cohort_id}#s{s.id}",
            "cta": "Davomat olish",
        })

    # 2) Tekshirilmagan topshiriqlar — vazifa bo'yicha guruhlanadi
    pend = {}
    for sb in Submission.query.filter_by(status="pending").all():
        pend.setdefault(sb.assignment_id, 0)
        pend[sb.assignment_id] += 1
    for aid, n in sorted(pend.items(), key=lambda x: -x[1]):
        a = db.session.get(Assignment, aid)
        if a is None:
            continue
        items.append({
            "kind": "baho", "urgent": n >= 5,
            "title": "Tekshirilmagan javob",
            "what": a.title,
            "note": f"{n} ta o'quvchi kutmoqda",
            "url": f"/oquv/assignment/{a.id}",
            "cta": "Tekshirish",
        })

    # 3) Ertaga boshlanadigan yoki bugun tugaydigan oqim
    for ch in Cohort.query.all():
        if ch.start_date == today:
            items.append({"kind": "oqim", "urgent": False,
                          "title": "Bugun oqim boshlanadi",
                          "what": f"{ch.course.name} — {ch.name}",
                          "note": "dars jadvali tayyormi?",
                          "url": f"/oquv/cohort/{ch.id}", "cta": "Ochish"})
        elif ch.end_date == today:
            items.append({"kind": "oqim", "urgent": False,
                          "title": "Bugun oqim tugaydi",
                          "what": f"{ch.course.name} — {ch.name}",
                          "note": "sertifikat berish vaqti",
                          "url": f"/oquv/cohort/{ch.id}", "cta": "Ochish"})

    # 4) Ilova havolasi berilmagan o'quvchilar — ular darslarni ko'ra olmaydi
    no_link = (Contract.query.filter(Contract.status == "active",
                                     Contract.portal_token.is_(None)).count())
    if no_link:
        items.append({"kind": "havola", "urgent": False,
                      "title": "Ilova havolasi berilmagan",
                      "what": f"{no_link} ta faol o'quvchi",
                      "note": "havolasiz ular darsni ocha olmaydi",
                      "url": "/oquv", "cta": None})

    items.sort(key=lambda x: (not x["urgent"],
                             {"davomat": 0, "baho": 1, "oqim": 2,
                              "havola": 3}.get(x["kind"], 9)))
    return items


def cohort_rows(today=None):
    """Oqimlar ro'yxati — har birida jarayon qay darajada ketgani."""
    from models import (Assignment, Cohort, Contract, LessonSession,
                        Submission)
    today = today or date.today()
    out = []
    for ch in Cohort.query.order_by(Cohort.start_date.desc()).all():
        actives = Contract.query.filter_by(cohort_id=ch.id,
                                           status="active").count()
        total = LessonSession.query.filter_by(cohort_id=ch.id).count()
        held = LessonSession.query.filter_by(cohort_id=ch.id, held=True).count()
        pending = (Submission.query.join(Assignment)
                   .filter(Assignment.cohort_id == ch.id,
                           Submission.status == "pending").count())
        at_risk = Contract.query.filter(Contract.cohort_id == ch.id,
                                        Contract.status == "active",
                                        Contract.risk_score >= RISK_MID).count()
        if ch.start_date > today:
            phase, plabel = "soon", "boshlanmagan"
        elif ch.end_date < today:
            phase, plabel = "done", "tugagan"
        else:
            phase, plabel = "live", "davom etmoqda"
        out.append({"cohort": ch, "students": actives, "sessions": total,
                    "held": held, "pending": pending, "at_risk": at_risk,
                    "phase": phase, "plabel": plabel,
                    "pct": round(100.0 * held / total) if total else 0,
                    "running": phase == "live"})
    order = {"live": 0, "soon": 1, "done": 2}
    out.sort(key=lambda r: (order[r["phase"]], -r["cohort"].start_date.toordinal()))
    return out


def risk_level(score):
    """Ball -> (sinf, so'z) — raqamning o'zi kuratorga hech nima demaydi."""
    s = score or 0
    if s >= RISK_HIGH:
        return "high", "yuqori"
    if s >= RISK_MID:
        return "mid", "o'rta"
    return "low", "past"


# ──────────────────────────────────────────────────────────────────
# ESKI TUZILMADAN YANGISIGA KO'CHIRISH
# ──────────────────────────────────────────────────────────────────
# Ilgari dars maydonlarida turgan mazmun (video_url, body, file_url,
# test) endi LessonItem qatorlariga aylanadi. Ko'chirish bir marta
# bo'ladi va hech narsa yo'qolmaydi: ko'rish tarixi ham, test
# natijalari ham o'z joyida qoladi.

def migrate_lesson_items():
    """Elementga ega bo'lmagan darslarni ko'chiradi. Qayta chaqirsa xavfsiz."""
    from models import LessonItem, LessonWatch, Quiz, Student, VideoLesson
    moved = 0
    for l in VideoLesson.query.all():
        if l.items:
            continue                       # allaqachon ko'chirilgan
        sort = 0
        video_item = None
        if (l.video_url or "").strip():
            sort += 1
            video_item = LessonItem(lesson_id=l.id, kind="video", sort=sort,
                                    url=l.video_url, minutes=l.minutes or 0)
            db.session.add(video_item)
        if (l.body or "").strip():
            sort += 1
            db.session.add(LessonItem(lesson_id=l.id, kind="matn", sort=sort,
                                      body=l.body, title="Konspekt"))
        if (l.file_url or "").strip():
            sort += 1
            db.session.add(LessonItem(lesson_id=l.id, kind="fayl", sort=sort,
                                      url=l.file_url,
                                      title="Qo'shimcha material"))
        q = Quiz.query.filter_by(lesson_id=l.id).first()
        if q is not None:
            sort += 1
            titem = LessonItem(lesson_id=l.id, kind="test", sort=sort,
                               title=q.title or "Nazorat testi")
            db.session.add(titem)
            db.session.flush()
            q.item_id = titem.id
        if sort:
            moved += 1
            db.session.flush()
            # eski ko'rish yozuvlari video elementiga bog'lanadi
            if video_item is not None:
                for w in LessonWatch.query.filter_by(lesson_id=l.id,
                                                     item_id=None).all():
                    w.item_id = video_item.id

    # Ilova kaliti: shartnomadan o'quvchiga ko'chadi
    linked = 0
    for s in Student.query.filter(Student.portal_token.is_(None)).all():
        tok = next((c.portal_token for c in s.contracts if c.portal_token), None)
        if tok:
            s.portal_token = tok           # eski havola ishlashda davom etadi
            linked += 1

    if moved or linked:
        db.session.commit()
        logger.info(f"Ko'chirildi: {moved} dars, {linked} o'quvchi kaliti")
    return moved, linked


def fix_watch_unique():
    """«lesson_watch» noyoblik shartini elementga o'tkazadi.

    Ilgari shart (dars, o'quvchi) edi — darsda bitta video bo'lgani uchun
    yetardi. Endi bir nechta video bo'lishi mumkin, shuning uchun shart
    (element, o'quvchi) bo'lishi kerak. Ustun qo'shish bilan bu
    o'zgarmaydi — jadvalni qayta qurish kerak.

    Yarim qolgan ko'chirishni o'zi tugatadi: agar «lesson_watch_eski»
    turgan bo'lsa, undagi yozuvlarni ko'chirib, keyin o'chiradi.
    """
    from sqlalchemy import inspect, text
    from models import LessonWatch
    COLS = ("id, lesson_id, item_id, contract_id, duration, covered, "
            "seconds, pct, max_pos, opens, first_at, last_at")

    def finish_copy():
        """Eski jadvaldan yetishmayotgan yozuvlarni ko'chirib, uni o'chiradi."""
        db.session.execute(text(
            f"INSERT INTO lesson_watch ({COLS}) SELECT {COLS} "
            f"FROM lesson_watch_eski WHERE id NOT IN "
            f"(SELECT id FROM lesson_watch)"))
        db.session.commit()
        db.session.execute(text("DROP TABLE lesson_watch_eski"))
        db.session.commit()

    insp = inspect(db.engine)
    tables = insp.get_table_names()
    if "lesson_watch" not in tables:
        return False
    if "lesson_watch_eski" in tables:      # oldingi urinish yarim qolgan
        finish_copy()
        logger.info("lesson_watch ko'chirishi yakunlandi")
        return True

    cons = {u["name"]: set(u["column_names"] or [])
            for u in insp.get_unique_constraints("lesson_watch")}
    if any(c == {"item_id", "contract_id"} for c in cons.values()):
        return False                        # allaqachon to'g'ri
    old = [n for n, c in cons.items() if c == {"lesson_id", "contract_id"}]
    if not old:
        return False

    if db.engine.dialect.name == "sqlite":
        # SQLite shartni olib tashlay olmaydi — jadval qayta quriladi
        db.session.execute(text("ALTER TABLE lesson_watch "
                                "RENAME TO lesson_watch_eski"))
        db.session.commit()
        LessonWatch.__table__.create(db.engine)
        finish_copy()
    else:
        for n in old:
            db.session.execute(text(
                f'ALTER TABLE lesson_watch DROP CONSTRAINT "{n}"'))
        db.session.execute(text(
            "ALTER TABLE lesson_watch ADD CONSTRAINT uq_lesson_watch_item "
            "UNIQUE (item_id, contract_id)"))
        db.session.commit()
    logger.info("lesson_watch noyoblik sharti elementga o'tkazildi")
    return True
