"""
O'quv bo'limi — to'liq oqim testi.

Oqim: kurs → guruh → o'quvchi → dars+davomat → vazifa → topshiriq →
      baholash → sertifikat → public tekshiruv → risk-skoring.
AI testda o'chirilgan (ANTHROPIC_API_KEY="") — modul AI'siz to'liq ishlashi shart.
"""


def _get_ids(app):
    from models.education import Course, Cohort, Enrollment
    with app.app_context():
        c = Course.query.filter_by(name="Test Sotuv kursi").first()
        g = Cohort.query.filter_by(name="TST-1").first()
        e = Enrollment.query.filter_by(student_name="Test O'quvchi").first()
        return (c.id if c else None, g.id if g else None, e.id if e else None)


def test_education_page_admin(admin_client):
    r = admin_client.get("/education")
    assert r.status_code == 200
    assert "O'quv bo'limi".encode() in r.data


def test_education_blocked_for_regular(regular_client):
    r = regular_client.get("/education", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" not in r.headers.get("Location", "")


def test_full_flow(app, admin_client, post):
    # 1) Kurs
    r = post(admin_client, "/education/course/save",
             name="Test Sotuv kursi", duration_weeks="8",
             price="5000000", follow=True)
    assert r.status_code == 200
    cid, _, _ = _get_ids(app)
    assert cid

    # 2) Guruh
    r = post(admin_client, "/education/cohort/save",
             name="TST-1", course_id=str(cid), teacher="Test Spiker",
             start_date="2026-08-01", schedule="Du/Chor 19:00",
             capacity="15", status="active", follow=True)
    assert r.status_code == 200
    _, gid, _ = _get_ids(app)
    assert gid

    # 3) O'quvchi (shartnoma 5 mln, to'lagan 2 mln → qarz signal)
    r = post(admin_client, f"/education/cohort/{gid}/enroll",
             student_name="Test O'quvchi", phone="+998901112233",
             contract_sum="5000000", paid_sum="2000000", follow=True)
    assert r.status_code == 200
    _, _, eid = _get_ids(app)
    assert eid

    # 4) Ikkita dars: birinchisiga kelmadi, ikkinchisiga ham kelmadi
    for d in ("2026-08-04", "2026-08-06"):
        r = post(admin_client, f"/education/cohort/{gid}/session/add",
                 date=d, topic="Mavzu", follow=True)
        assert r.status_code == 200
    from models.education import LessonSession
    with app.app_context():
        sessions = (LessonSession.query.filter_by(cohort_id=gid)
                    .order_by(LessonSession.date).all())
        sids = [s.id for s in sessions]
    for sid in sids:
        r = post(admin_client, f"/education/session/{sid}/attendance",
                 **{f"st_{eid}": "absent"}, follow=True)
        assert r.status_code == 200

    # Davomat → risk oshgan bo'lishi kerak (100% qoldirgan + qarz)
    from models.education import Enrollment
    with app.app_context():
        e = Enrollment.query.get(eid)
        assert e.risk_score >= 60, e.risk_reasons
        assert "qarz" in e.risk_reasons or "kelmagan" in e.risk_reasons

    # 5) Vazifa + topshiriq (AI o'chiq — pending holatda qoladi)
    r = post(admin_client, f"/education/cohort/{gid}/assignment/add",
             title="Skript yozish", description="Sovuq qo'ng'iroq skripti",
             max_score="100", follow=True)
    assert r.status_code == 200
    from models.education import Assignment
    with app.app_context():
        aid = Assignment.query.filter_by(cohort_id=gid).first().id
    r = post(admin_client, f"/education/assignment/{aid}/submit",
             enrollment_id=str(eid), content="Assalomu alaykum, men ...",
             follow=True)
    assert r.status_code == 200
    from models.education import Submission
    with app.app_context():
        sub = Submission.query.filter_by(assignment_id=aid,
                                         enrollment_id=eid).first()
        assert sub is not None
        assert sub.status == "pending"
        assert sub.ai_score is None   # AI o'chiq
        sub_id = sub.id

    # 6) Qo'lda baholash
    r = post(admin_client, f"/education/submission/{sub_id}/grade",
             score="85", feedback="Yaxshi boshlanish", follow=True)
    assert r.status_code == 200
    with app.app_context():
        sub = Submission.query.get(sub_id)
        assert sub.status == "graded"
        assert sub.score == 85

    # 7) Sertifikat + public tekshiruv
    r = post(admin_client, f"/education/enrollment/{eid}/certificate",
             follow=True)
    assert r.status_code == 200
    from models.education import Certificate
    with app.app_context():
        cert = Certificate.query.filter_by(enrollment_id=eid).first()
        assert cert is not None
        assert cert.serial.startswith("MF-")
        token = cert.token
        e = Enrollment.query.get(eid)
        assert e.status == "finished"

    # Public sahifa login'siz ochiladi
    import re
    anon = app.test_client()
    r = anon.get(f"/cert/{token}")
    assert r.status_code == 200
    assert "haqiqiy" in r.data.decode()
    assert re.search(r"MF-\d{4}-\d{5}", r.data.decode())

    # Noto'g'ri token → 404
    r = anon.get("/cert/notarealtoken")
    assert r.status_code == 404


def test_cohort_page_renders(app, admin_client):
    _, gid, _ = _get_ids(app)
    if gid:
        r = admin_client.get(f"/education/cohort/{gid}")
        assert r.status_code == 200
        assert b"TST-1" in r.data


def test_assignment_page_renders(app, admin_client):
    from models.education import Assignment
    with app.app_context():
        a = Assignment.query.first()
    if a:
        r = admin_client.get(f"/education/assignment/{a.id}")
        assert r.status_code == 200


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200


def test_root_redirects_anon(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers.get("Location", "")


def test_education_allowed_for_edu_role(edu_client):
    r = edu_client.get("/education")
    assert r.status_code == 200
