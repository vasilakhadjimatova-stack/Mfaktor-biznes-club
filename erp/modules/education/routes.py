"""
O'quv bo'limi (Ta'lim/LMS) — route'lar.

  /education                         — bo'lim markazi: KPI, guruhlar, kurslar, risk
  /education/cohort/<id>             — guruh sahifasi: o'quvchilar, davomat,
                                       vazifalar, to'lov holati
  /education/assignment/<id>         — vazifa: topshiriqlar va baholash (AI + qo'lda)
  /cert/<token>                      — PUBLIC: sertifikat haqiqiyligini tekshirish

Ruxsat: education moduli yoki rahbar/admin. Sertifikat sahifasi login'siz.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort)

from database import db
from core.auth import login_required, current_user
from models.education import (Course, Cohort, Enrollment, LessonSession,
                              StudentAttendance, Assignment, Submission,
                              Certificate, ENROLLMENT_STATUSES,
                              COHORT_STATUSES, ATT_STATUSES)

bp = Blueprint("education", __name__)


def _gate():
    """O'quv bo'limiga kirish: education ruxsati yoki rahbar/admin."""
    u = current_user()
    if not (u.can("education") or u.is_boss):
        flash("O'quv bo'limiga ruxsat yo'q", "error")
        return redirect(url_for("auth.no_access"))
    return None


def _f(name, default=""):
    return (request.form.get(name) or default).strip()


def _num(name):
    try:
        return float((request.form.get(name) or "0").replace(" ", "") or 0)
    except (TypeError, ValueError):
        return 0.0


# ══════════════════════════════════════════════════════════════════
#  BO'LIM MARKAZI
# ══════════════════════════════════════════════════════════════════
@bp.route("/education")
@login_required
def index():
    if (r := _gate()) is not None:
        return r
    from core.education import edu_stats, risk_students
    cohorts = Cohort.query.order_by(
        db.case((Cohort.status == "active", 0),
                (Cohort.status == "planned", 1), else_=2),
        Cohort.start_date.desc()).all()
    courses = Course.query.order_by(Course.is_active.desc(),
                                    Course.name.asc()).all()
    return render_template("education/index.html",
                           stats=edu_stats(), cohorts=cohorts,
                           courses=courses, risk=risk_students(),
                           cohort_statuses=COHORT_STATUSES)


# ── Kurslar ──────────────────────────────────────────────────────
@bp.route("/education/course/save", methods=["POST"])
@login_required
def course_save():
    if (r := _gate()) is not None:
        return r
    name = _f("name")
    if not name:
        flash("Kurs nomi majburiy", "error")
        return redirect(url_for("education.index"))
    cid = _f("course_id")
    c = Course.query.get(int(cid)) if cid.isdigit() else None
    if c is None:
        c = Course()
        db.session.add(c)
    c.name = name[:160]
    c.description = _f("description")[:4000]
    c.duration_weeks = int(_num("duration_weeks") or 8)
    c.price = _num("price")
    c.is_active = _f("is_active", "1") == "1"
    db.session.commit()
    flash("Kurs saqlandi", "ok")
    return redirect(url_for("education.index"))


# ── Guruhlar ─────────────────────────────────────────────────────
@bp.route("/education/cohort/save", methods=["POST"])
@login_required
def cohort_save():
    if (r := _gate()) is not None:
        return r
    name, course_id = _f("name"), _f("course_id")
    if not name or not course_id.isdigit() or not Course.query.get(int(course_id)):
        flash("Guruh nomi va kursi majburiy", "error")
        return redirect(url_for("education.index"))
    gid = _f("cohort_id")
    g = Cohort.query.get(int(gid)) if gid.isdigit() else None
    if g is None:
        g = Cohort()
        db.session.add(g)
    g.name = name[:120]
    g.course_id = int(course_id)
    g.teacher = _f("teacher")[:160]
    g.start_date = _f("start_date")[:10]
    g.end_date = _f("end_date")[:10]
    g.schedule = _f("schedule")[:200]
    g.capacity = int(_num("capacity") or 20)
    if _f("status") in COHORT_STATUSES:
        g.status = _f("status")
    db.session.commit()
    flash("Guruh saqlandi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=g.id))


@bp.route("/education/cohort/<int:cohort_id>")
@login_required
def cohort_view(cohort_id):
    if (r := _gate()) is not None:
        return r
    g = Cohort.query.get_or_404(cohort_id)
    students = (g.enrollments
                .order_by(db.case((Enrollment.status == "active", 0), else_=1),
                          Enrollment.risk_score.desc(),
                          Enrollment.student_name.asc()).all())
    sessions = g.sessions.order_by(LessonSession.date.asc()).all()
    assignments = g.assignments.order_by(Assignment.created_at.desc()).all()
    # Davomat jadvali: {(session_id, enrollment_id): status}
    att = {}
    if sessions:
        sids = [s.id for s in sessions]
        for a in StudentAttendance.query.filter(
                StudentAttendance.session_id.in_(sids)).all():
            att[(a.session_id, a.enrollment_id)] = a.status
    # Vazifa topshirganlar soni
    sub_counts = {a.id: a.submissions.count() for a in assignments}
    pending_counts = {a.id: a.submissions.filter_by(status="pending").count()
                      for a in assignments}
    return render_template("education/cohort.html",
                           g=g, students=students, sessions=sessions,
                           assignments=assignments, att=att,
                           sub_counts=sub_counts, pending_counts=pending_counts,
                           enr_statuses=ENROLLMENT_STATUSES,
                           att_statuses=ATT_STATUSES,
                           cohort_statuses=COHORT_STATUSES,
                           courses=Course.query.order_by(Course.name).all())


# ── O'quvchi yozish / yangilash ──────────────────────────────────
@bp.route("/education/cohort/<int:cohort_id>/enroll", methods=["POST"])
@login_required
def enroll(cohort_id):
    if (r := _gate()) is not None:
        return r
    g = Cohort.query.get_or_404(cohort_id)
    name = _f("student_name")
    if not name:
        flash("O'quvchi ismi majburiy", "error")
        return redirect(url_for("education.cohort_view", cohort_id=g.id))
    e = Enrollment(
        cohort_id=g.id, student_name=name[:160], phone=_f("phone")[:40],
        telegram=_f("telegram")[:80], source=_f("source")[:80],
        contract_sum=_num("contract_sum") or (g.course.price if g.course else 0),
        paid_sum=_num("paid_sum"), next_pay_date=_f("next_pay_date")[:10],
        note=_f("note")[:2000])
    lead_id = _f("lead_id")
    if lead_id.isdigit():
        e.lead_id = int(lead_id)
    db.session.add(e)
    db.session.commit()
    flash(f"{e.student_name} guruhga yozildi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=g.id))


@bp.route("/education/enrollment/<int:enr_id>/update", methods=["POST"])
@login_required
def enrollment_update(enr_id):
    if (r := _gate()) is not None:
        return r
    e = Enrollment.query.get_or_404(enr_id)
    st = _f("status")
    if st in ENROLLMENT_STATUSES:
        e.status = st
    if request.form.get("paid_sum") is not None:
        e.paid_sum = _num("paid_sum")
    if request.form.get("contract_sum") is not None and _num("contract_sum"):
        e.contract_sum = _num("contract_sum")
    if request.form.get("next_pay_date") is not None:
        e.next_pay_date = _f("next_pay_date")[:10]
    db.session.commit()
    flash("O'quvchi ma'lumoti yangilandi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=e.cohort_id))


@bp.route("/education/enrollment/<int:enr_id>/certificate", methods=["POST"])
@login_required
def issue_certificate(enr_id):
    if (r := _gate()) is not None:
        return r
    e = Enrollment.query.get_or_404(enr_id)
    u = current_user()
    e.status = "finished"
    cert = Certificate.issue(e, issued_by=u.name)
    db.session.commit()
    flash(f"Sertifikat berildi: {cert.serial}", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=e.cohort_id))


# ── Darslar va davomat ───────────────────────────────────────────
@bp.route("/education/cohort/<int:cohort_id>/session/add", methods=["POST"])
@login_required
def session_add(cohort_id):
    if (r := _gate()) is not None:
        return r
    g = Cohort.query.get_or_404(cohort_id)
    date = _f("date")
    if not date:
        flash("Dars sanasi majburiy", "error")
        return redirect(url_for("education.cohort_view", cohort_id=g.id))
    db.session.add(LessonSession(cohort_id=g.id, date=date[:10],
                                 topic=_f("topic")[:200]))
    db.session.commit()
    flash("Dars qo'shildi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=g.id))


@bp.route("/education/session/<int:session_id>/attendance", methods=["POST"])
@login_required
def mark_attendance(session_id):
    if (r := _gate()) is not None:
        return r
    s = LessonSession.query.get_or_404(session_id)
    s.held = True
    active = Enrollment.query.filter_by(cohort_id=s.cohort_id,
                                        status="active").all()
    for e in active:
        st = _f(f"st_{e.id}")
        if st not in ATT_STATUSES:
            continue
        row = StudentAttendance.query.filter_by(
            session_id=s.id, enrollment_id=e.id).first()
        if row is None:
            row = StudentAttendance(session_id=s.id, enrollment_id=e.id)
            db.session.add(row)
        row.status = st
    db.session.commit()
    # Davomat o'zgardi → guruh riskini darhol yangilaymiz
    from core.education import refresh_cohort_risk
    refresh_cohort_risk(s.cohort_id)
    flash("Davomat saqlandi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=s.cohort_id))


# ── Vazifalar va baholash ────────────────────────────────────────
@bp.route("/education/cohort/<int:cohort_id>/assignment/add", methods=["POST"])
@login_required
def assignment_add(cohort_id):
    if (r := _gate()) is not None:
        return r
    g = Cohort.query.get_or_404(cohort_id)
    title = _f("title")
    if not title:
        flash("Vazifa sarlavhasi majburiy", "error")
        return redirect(url_for("education.cohort_view", cohort_id=g.id))
    db.session.add(Assignment(
        cohort_id=g.id, title=title[:200], description=_f("description")[:8000],
        due_date=_f("due_date")[:10], max_score=int(_num("max_score") or 100)))
    db.session.commit()
    flash("Vazifa berildi", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=g.id))


@bp.route("/education/assignment/<int:assignment_id>")
@login_required
def assignment_view(assignment_id):
    if (r := _gate()) is not None:
        return r
    a = Assignment.query.get_or_404(assignment_id)
    g = Cohort.query.get(a.cohort_id)
    subs = a.submissions.order_by(
        db.case((Submission.status == "pending", 0), else_=1),
        Submission.submitted_at.desc()).all()
    submitted_ids = {s.enrollment_id for s in subs}
    not_submitted = [e for e in Enrollment.query.filter_by(
        cohort_id=a.cohort_id, status="active").all()
        if e.id not in submitted_ids]
    return render_template("education/assignment.html",
                           a=a, g=g, subs=subs, not_submitted=not_submitted)


@bp.route("/education/assignment/<int:assignment_id>/submit", methods=["POST"])
@login_required
def submission_add(assignment_id):
    """Topshiriqni qayd etish (v1: kurator kiritadi; v2: o'quvchi portali/bot)."""
    if (r := _gate()) is not None:
        return r
    a = Assignment.query.get_or_404(assignment_id)
    enr_id = _f("enrollment_id")
    e = Enrollment.query.get(int(enr_id)) if enr_id.isdigit() else None
    if e is None or e.cohort_id != a.cohort_id:
        flash("O'quvchi tanlanmadi", "error")
        return redirect(url_for("education.assignment_view",
                                assignment_id=a.id))
    sub = Submission.query.filter_by(assignment_id=a.id,
                                     enrollment_id=e.id).first()
    if sub is None:
        sub = Submission(assignment_id=a.id, enrollment_id=e.id)
        db.session.add(sub)
    sub.content = _f("content")[:20000]
    sub.status = "pending"
    db.session.commit()
    # AI birinchi qatlam bahosi (sozlangan bo'lsa) — xatoda jim o'tadi
    from core.education import ai_grade
    score, feedback = ai_grade(a, sub.content, a.max_score)
    if score is not None:
        sub.ai_score = score
        sub.ai_feedback = feedback
        db.session.commit()
    from core.education import refresh_cohort_risk
    refresh_cohort_risk(a.cohort_id)
    flash("Topshiriq qabul qilindi" +
          (" · AI bahosi tayyor" if score is not None else ""), "ok")
    return redirect(url_for("education.assignment_view", assignment_id=a.id))


@bp.route("/education/submission/<int:sub_id>/grade", methods=["POST"])
@login_required
def submission_grade(sub_id):
    """Yakuniy baho — kurator AI taklifini tasdiqlaydi yoki o'z ballini qo'yadi."""
    if (r := _gate()) is not None:
        return r
    sub = Submission.query.get_or_404(sub_id)
    a = Assignment.query.get(sub.assignment_id)
    if _f("use_ai") == "1" and sub.ai_score is not None:
        sub.score = sub.ai_score
        if not _f("feedback"):
            sub.feedback = sub.ai_feedback
    else:
        try:
            score = int(_num("score"))
        except (TypeError, ValueError):
            score = 0
        sub.score = max(0, min(a.max_score or 100, score))
    if _f("feedback"):
        sub.feedback = _f("feedback")[:4000]
    from datetime import datetime
    sub.status = "graded"
    sub.graded_by = current_user().name
    sub.graded_at = datetime.utcnow()
    db.session.commit()
    flash(f"Baholandi: {sub.score} ball", "ok")
    return redirect(url_for("education.assignment_view",
                            assignment_id=sub.assignment_id))


@bp.route("/education/cohort/<int:cohort_id>/refresh-risk", methods=["POST"])
@login_required
def refresh_risk(cohort_id):
    if (r := _gate()) is not None:
        return r
    from core.education import refresh_cohort_risk
    n = refresh_cohort_risk(cohort_id)
    flash(f"Risk qayta hisoblandi ({n} o'quvchi)", "ok")
    return redirect(url_for("education.cohort_view", cohort_id=cohort_id))


# ══════════════════════════════════════════════════════════════════
#  PUBLIC: sertifikat tekshiruvi (login'siz, QR uchun)
# ══════════════════════════════════════════════════════════════════
@bp.route("/cert/<token>")
def cert_verify(token):
    cert = Certificate.query.filter_by(token=token).first()
    if not cert:
        return render_template("education/cert_verify.html", cert=None), 404
    e = Enrollment.query.get(cert.enrollment_id)
    g = Cohort.query.get(e.cohort_id) if e else None
    course = Course.query.get(g.course_id) if g else None
    return render_template("education/cert_verify.html",
                           cert=cert, e=e, g=g, course=course)
