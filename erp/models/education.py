"""
O'quv bo'limi (Ta'lim/LMS) modellari — Mfaktor biznes maktabi yadrosi.

Zanjir: Kurs → Guruh (kohorta) → O'quvchi yozilmasi (Enrollment)
        Guruh → Dars mashg'uloti → Davomat
        Guruh → Vazifa → Topshiriq (Submission, AI baholash bilan)
        Yozilma → Sertifikat (QR/token bilan ochiq tekshiriladi)

Moliya bilan bog'lanish: yozilmada shartnoma summasi va to'langan summa
yuritiladi — qarzdorlik risk-skoringga signal beradi (core/education.py).
"""
import secrets
from datetime import datetime

from database import db

# O'quvchi yozilmasi holatlari
ENROLLMENT_STATUSES = {
    "active":   "O'qiyapti",
    "frozen":   "Muzlatilgan",
    "finished": "Bitirdi",
    "dropped":  "Tashlab ketdi",
}

# Guruh holatlari
COHORT_STATUSES = {
    "planned": "Rejalashtirilgan",
    "active":  "Davom etmoqda",
    "finished": "Yakunlangan",
}

# Davomat holatlari (dars mashg'uloti bo'yicha)
ATT_STATUSES = {
    "present": "Keldi",
    "late":    "Kechikdi",
    "absent":  "Kelmadi",
    "excused": "Sababli",
}


class Course(db.Model):
    """Kurs katalogi — masalan «Sotuv menejeri», «ROP», «Tadbirkorlar uchun AI»."""
    __tablename__ = "edu_courses"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    duration_weeks = db.Column(db.Integer, default=8)      # davomiyligi (hafta)
    price       = db.Column(db.Float, default=0)           # standart narx (so'm)
    is_active   = db.Column(db.Boolean, nullable=False, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    cohorts = db.relationship("Cohort", backref="course", lazy="dynamic")

    def __repr__(self):
        return f"<Course {self.name}>"


class Cohort(db.Model):
    """Guruh/oqim — kursning muayyan boshlanish sanali to'plami."""
    __tablename__ = "edu_cohorts"

    id         = db.Column(db.Integer, primary_key=True)
    course_id  = db.Column(db.Integer, db.ForeignKey("edu_courses.id"),
                           index=True, nullable=False)
    name       = db.Column(db.String(120), nullable=False)   # «Sotuv-12», «AI-1»
    teacher    = db.Column(db.String(160), default="")       # spiker/o'qituvchi
    start_date = db.Column(db.String(10), default="")        # YYYY-MM-DD
    end_date   = db.Column(db.String(10), default="")
    schedule   = db.Column(db.String(200), default="")       # «Du/Chor/Ju 19:00»
    capacity   = db.Column(db.Integer, default=20)
    status     = db.Column(db.String(20), nullable=False, default="planned")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    enrollments = db.relationship("Enrollment", backref="cohort", lazy="dynamic")
    sessions    = db.relationship("LessonSession", backref="cohort", lazy="dynamic")
    assignments = db.relationship("Assignment", backref="cohort", lazy="dynamic")

    @property
    def status_label(self):
        return COHORT_STATUSES.get(self.status, self.status)

    @property
    def active_count(self):
        return self.enrollments.filter_by(status="active").count()

    def __repr__(self):
        return f"<Cohort {self.name}>"


class Enrollment(db.Model):
    """O'quvchi yozilmasi — «kim, qaysi guruhda, qanday holatda»."""
    __tablename__ = "edu_enrollments"

    id           = db.Column(db.Integer, primary_key=True)
    cohort_id    = db.Column(db.Integer, db.ForeignKey("edu_cohorts.id"),
                             index=True, nullable=False)
    student_name = db.Column(db.String(160), nullable=False)
    phone        = db.Column(db.String(40), default="")
    telegram     = db.Column(db.String(80), default="")
    source       = db.Column(db.String(80), default="")     # qayerdan keldi
    lead_id      = db.Column(db.Integer, index=True)        # CRM lead (ixtiyoriy)
    status       = db.Column(db.String(20), nullable=False, default="active")

    # Moliya ko'prigi (v1 — yozilma darajasida yuritiladi)
    contract_sum = db.Column(db.Float, default=0)   # shartnoma summasi
    paid_sum     = db.Column(db.Float, default=0)   # to'langan
    next_pay_date = db.Column(db.String(10), default="")   # keyingi to'lov sanasi

    # Risk (dropout) — core/education.compute_risk() yangilaydi
    risk_score   = db.Column(db.Integer, default=0)         # 0–100
    risk_reasons = db.Column(db.String(300), default="")    # «3 dars qoldirdi; qarz»

    note         = db.Column(db.Text, default="")
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    attendance  = db.relationship("StudentAttendance", backref="enrollment",
                                  lazy="dynamic")
    submissions = db.relationship("Submission", backref="enrollment",
                                  lazy="dynamic")
    certificate = db.relationship("Certificate", backref="enrollment",
                                  uselist=False)

    @property
    def status_label(self):
        return ENROLLMENT_STATUSES.get(self.status, self.status)

    @property
    def debt(self):
        return max(0.0, (self.contract_sum or 0) - (self.paid_sum or 0))

    def __repr__(self):
        return f"<Enrollment {self.student_name}>"


class LessonSession(db.Model):
    """Dars mashg'uloti — guruhning bitta o'tkazilgan/rejalashtirilgan darsi."""
    __tablename__ = "edu_sessions"

    id         = db.Column(db.Integer, primary_key=True)
    cohort_id  = db.Column(db.Integer, db.ForeignKey("edu_cohorts.id"),
                           index=True, nullable=False)
    date       = db.Column(db.String(10), nullable=False)   # YYYY-MM-DD
    topic      = db.Column(db.String(200), default="")
    held       = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attendance = db.relationship("StudentAttendance", backref="session",
                                 lazy="dynamic")

    def __repr__(self):
        return f"<LessonSession {self.date} {self.topic[:20]}>"


class StudentAttendance(db.Model):
    """O'quvchi davomati — bitta dars bo'yicha bitta o'quvchi holati."""
    __tablename__ = "edu_attendance"
    __table_args__ = (
        db.UniqueConstraint("session_id", "enrollment_id",
                            name="uq_edu_att_session_student"),
    )

    id            = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey("edu_sessions.id"),
                              index=True, nullable=False)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("edu_enrollments.id"),
                              index=True, nullable=False)
    status        = db.Column(db.String(12), nullable=False, default="present")

    @property
    def status_label(self):
        return ATT_STATUSES.get(self.status, self.status)


class Assignment(db.Model):
    """Uy vazifasi — guruhga beriladi, o'quvchilar topshiradi."""
    __tablename__ = "edu_assignments"

    id          = db.Column(db.Integer, primary_key=True)
    cohort_id   = db.Column(db.Integer, db.ForeignKey("edu_cohorts.id"),
                            index=True, nullable=False)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    due_date    = db.Column(db.String(10), default="")     # YYYY-MM-DD
    max_score   = db.Column(db.Integer, default=100)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship("Submission", backref="assignment",
                                  lazy="dynamic")

    def __repr__(self):
        return f"<Assignment {self.title[:30]}>"


class Submission(db.Model):
    """Topshiriq — o'quvchi javobi. AI birinchi qatlam bahosini beradi,
    spiker/kurator tasdiqlaydi (score yakuniy)."""
    __tablename__ = "edu_submissions"
    __table_args__ = (
        db.UniqueConstraint("assignment_id", "enrollment_id",
                            name="uq_edu_sub_assignment_student"),
    )

    id            = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("edu_assignments.id"),
                              index=True, nullable=False)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("edu_enrollments.id"),
                              index=True, nullable=False)
    content       = db.Column(db.Text, default="")          # matnli javob/skript
    submitted_at  = db.Column(db.DateTime, default=datetime.utcnow)

    status        = db.Column(db.String(12), nullable=False, default="pending")
    # pending (tekshirilmagan) / graded (baholangan)
    score         = db.Column(db.Integer)                   # yakuniy ball
    feedback      = db.Column(db.Text, default="")          # kurator izohi
    ai_score      = db.Column(db.Integer)                   # AI taklif qilgan ball
    ai_feedback   = db.Column(db.Text, default="")          # AI tahlili
    graded_by     = db.Column(db.String(120), default="")   # kim tasdiqladi
    graded_at     = db.Column(db.DateTime)


class Certificate(db.Model):
    """Sertifikat — noyob token bilan; /cert/<token> orqali ochiq tekshiriladi."""
    __tablename__ = "edu_certificates"

    id            = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("edu_enrollments.id"),
                              unique=True, index=True, nullable=False)
    token         = db.Column(db.String(48), unique=True, index=True,
                              nullable=False)
    serial        = db.Column(db.String(40), unique=True, nullable=False)
    issued_at     = db.Column(db.DateTime, default=datetime.utcnow)
    issued_by     = db.Column(db.String(120), default="")

    @staticmethod
    def issue(enrollment, issued_by=""):
        """Yozilma uchun sertifikat yaratadi (bor bo'lsa o'shani qaytaradi)."""
        cert = Certificate.query.filter_by(enrollment_id=enrollment.id).first()
        if cert:
            return cert
        n = (Certificate.query.count() or 0) + 1
        cert = Certificate(
            enrollment_id=enrollment.id,
            token=secrets.token_urlsafe(24),
            serial=f"MF-{datetime.utcnow().year}-{n:05d}",
            issued_by=issued_by,
        )
        db.session.add(cert)
        return cert
