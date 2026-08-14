"""
Mfaktor Moliya — ta'lim biznesi uchun moliya dasturi.

Ishga tushirish:
    pip install -r requirements.txt
    python seed.py      # birinchi marta — demo ma'lumot
    python app.py       # http://localhost:5060
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, session, url_for)

import analytics
import automation
import core
import ddsflow
import education
import kpi
import matching
import notify
import planner
import praytimes
import recover
import roles
import transfers
from database import db, init_db
from models import (AppSetting, Budget, Cohort, Contract, Course, DdsRow, DDS_LOOKUP,
                    DDS_SPRAVOCHNIK, DDS_WALLET2, DDS_WALLETS, EXPENSE_CATS, KpiCard,
                    INCOME_CATS, InstallmentLine, MARKETING_CHANNELS,
                    RecurringPayment, Student, Transaction, Wallet,
                    CONTRACT_STATUSES, income_cat_for_course,
                    ATT_STATUSES, LessonSession, LessonAttendance,
                    Assignment, Submission, EduCertificate,
                    VideoModule, VideoLesson, LessonView, LessonWatch,
                    LessonItem, ITEM_KINDS,
                    Quiz, QuizQuestion, QuizOption, QuizAttempt)


def _session_secret(app):
    """Sessiya imzosi uchun kalit.

    Kod ochiq repoda turgani uchun kalitni faylga yozib qo'yib bo'lmaydi —
    uni bilgan har kim «kirilgan» cookie'sini yasab, 6 xonali koddan
    o'tib ketardi. Shuning uchun: avval SECRET_KEY muhit o'zgaruvchisi,
    bo'lmasa — bazada bir marta yaratiladigan tasodifiy kalit.
    """
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    with app.app_context():
        try:
            row = db.session.get(AppSetting, "secret_key")
            if row and row.value:
                return row.value
            key = secrets.token_urlsafe(48)
            db.session.merge(AppSetting(key="secret_key", value=key))
            db.session.commit()
            app.logger.warning(
                "SECRET_KEY o'rnatilmagan — bazada tasodifiy kalit yaratildi")
            return key
        except Exception:                              # noqa: BLE001
            db.session.rollback()
            # baza hali tayyor emas: jarayon uchun vaqtincha kalit
            return secrets.token_urlsafe(48)


def _tg_secret():
    """Webhook manzilining maxfiy qismi — sessiya kalitidan hosil bo'ladi."""
    from flask import current_app
    return hashlib.sha256(
        f"tg:{current_app.secret_key}".encode()).hexdigest()[:24]


def _current_role():
    """Sessiyadagi rol. Kod almashtirilgan bo'lsa sessiyani uzadi."""
    if not session.get("auth"):
        return None
    role = session.get("role") or roles.DIREKTOR
    stamp = session.get("rv")
    if stamp is None:
        # Rollar qo'shilishidan oldingi sessiya — o'shanda faqat bitta kod,
        # ya'ni direktorniki bor edi.
        return roles.DIREKTOR
    if stamp != roles.role_stamp(role):
        session.clear()                # kod almashtirilgan — qayta kirsin
        return None
    return role


def create_app():
    app = Flask(__name__)
    app.permanent_session_lifetime = timedelta(days=30)
    init_db(app)
    app.secret_key = _session_secret(app)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,      # JS cookie'ni o'qiy olmaydi
        SESSION_COOKIE_SAMESITE="Lax",     # boshqa saytdan yuborilmaydi
        # Railway HTTPS'da ishlaydi; lokal ishlab chiqishda o'chiq bo'ladi
        SESSION_COOKIE_SECURE=bool(os.environ.get("APP_PIN", "").strip()),
    )

    # Bo'sh bazada standart kurslar o'zi paydo bo'ladi — «Oqim» ro'yxati
    # hech qachon bo'm-bo'sh qolmasin (yangi deploy/baza holati uchun).
    _DEFAULT_COURSES = [
        ("Sotuv menejerlari kursi (СМК)", 3_450_000),
        ("СМК Online", 3_000_000),
        ("Sotuv bo'limi rahbari (РОП)", 12_000_000),
        ("ТББ yo'nalishi", 15_000_000),
    ]
    with app.app_context():
        try:
            if Course.query.count() == 0:
                for n, p in _DEFAULT_COURSES:
                    db.session.add(Course(name=n, base_price=p))
                db.session.commit()
        except Exception:                              # noqa: BLE001
            db.session.rollback()

    # ── 6 xonali kirish kodi ─────────────────────────────────────
    # APP_PIN o'rnatilgan bo'lsa butun dastur qulflanadi (Railway'da shart).
    # O'rnatilmagan bo'lsa (lokal ishlab chiqish) — himoya o'chiq.
    APP_PIN = roles.app_pin()
    _pin_fails = {}                    # ip -> (soni, oxirgi urinish vaqti)
    # Endpoint'i yo'q fayl manzillari (marshrutga tushmaydi)
    _PUBLIC_PATHS = ("/static/", "/manifest.json", "/offline.html")

    @app.before_request
    def _guard():
        if not APP_PIN:
            return None
        p = request.path
        if any(p.startswith(x) for x in _PUBLIC_PATHS):
            return None
        ep = request.endpoint
        if ep is None:
            return None            # bunday manzil yo'q — Flask 404 bersin
        if ep in roles.PUBLIC:
            return None
        role = _current_role()
        if role is None:
            return redirect(url_for("login", next=request.path))
        if not roles.can(role, ep):
            return render_template("403.html", role=role,
                                   home=roles.home_for(role)), 403
        return None

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not APP_PIN:
            return redirect("/")
        if session.get("auth"):
            return redirect(roles.home_for(_current_role()))
        err = wait = None
        ip = request.headers.get("X-Forwarded-For",
                                 request.remote_addr or "?").split(",")[0]
        fails, last = _pin_fails.get(ip, (0, 0))
        if request.method == "POST":
            # 5 marta xato — 60 soniya kutish (qo'pol kuchga qarshi)
            if fails >= 5 and time.time() - last < 60:
                wait = int(60 - (time.time() - last))
            else:
                pin = "".join(ch for ch in request.form.get("pin", "")
                              if ch.isdigit())
                role = roles.match_role(pin) if pin else None
                if role:
                    _pin_fails.pop(ip, None)
                    session.permanent = True
                    session["auth"] = True
                    session["role"] = role
                    session["rv"] = roles.role_stamp(role)
                    home = roles.home_for(role)
                    nxt = request.args.get("next", "")
                    # so'ralgan sahifa bu rolga yopiq bo'lsa — o'z uyiga
                    if nxt.startswith("/") and not nxt.startswith("//"):
                        adapter = app.url_map.bind("localhost")
                        try:
                            ep, _ = adapter.match(nxt.split("?")[0])
                        except Exception:              # noqa: BLE001
                            ep = None
                        return redirect(nxt if roles.can(role, ep) else home)
                    return redirect(home)
                _pin_fails[ip] = (fails + 1, time.time())
                err = "Kod noto'g'ri"
                if fails + 1 >= 5:
                    wait = 60
        return render_template("login.html", err=err, wait=wait)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.template_filter("grp")
    def grp(v):
        """1 234 567 — so'm formatlash."""
        try:
            return f"{float(v):,.0f}".replace(",", " ")
        except (TypeError, ValueError):
            return v

    @app.template_filter("dmy")
    def dmy(d):
        return d.strftime("%d.%m.%Y") if d else ""

    @app.template_global("qs")
    def qs(**kw):
        """Joriy URL query'sini saqlab, faqat berilgan kalitlarni almashtiradi.

        qs(sort='date')   -> ?...&sort=date
        qs(a=None)        -> «a» filtrini olib tashlaydi
        """
        args = request.args.to_dict(flat=False)
        for k, v in kw.items():
            if v is None:
                args.pop(k, None)
            elif isinstance(v, (list, tuple)):
                args[k] = list(v)
            else:
                args[k] = [v]
        pairs = [(k, x) for k, vs in args.items() for x in vs if x != ""]
        return (request.path + "?" + urlencode(pairs)) if pairs else request.path

    @app.context_processor
    def ctx():
        # Qulf o'chiq bo'lsa (lokal ishlab chiqish) — hamma narsa ko'rinadi
        role = _current_role() if APP_PIN else roles.DIREKTOR
        bad_transfers = 0
        try:
            wrows, total_cash = core.wallet_balances()
            # Manfiy qoldiq — deyarli har doim juftlanmagan o'tkazma belgisi.
            # To'liq juftlashni bu yerda qilmaymiz: u qimmat, sahifasida
            # hisoblanadi. Bu yerda faqat arzon signal.
            bad_transfers = sum(1 for r in wrows if r["balance"] < 0)
        except Exception:
            total_cash = None
        if not roles.sees_cash(role):
            total_cash = None          # kurator kompaniya pulini ko'rmaydi
        try:
            inbox_open = matching.open_count()
        except Exception:
            inbox_open = 0
        return {"INCOME_CATS": INCOME_CATS, "EXPENSE_CATS": EXPENSE_CATS,
                "CHANNELS": MARKETING_CHANNELS, "STATUSES": CONTRACT_STATUSES,
                "today": date.today(), "total_cash": total_cash,
                "inbox_open": inbox_open, "bad_transfers": bad_transfers,
                "role": role, "role_label": roles.ROLE_LABELS.get(role, ""),
                "can": (lambda ep: roles.can(role, ep))}

    register_routes(app)
    return app


def _parse_date(s, default=None):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return default or date.today()


def _num(s):
    """«12 500 000» / «12500000,5» → son. Bo'sh bo'lsa None."""
    s = (s or "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _ym():
    """?y=&m= parametrlari yoki joriy oy."""
    t = date.today()
    try:
        y = int(request.args.get("y", t.year))
        m = int(request.args.get("m", t.month))
    except ValueError:
        y, m = t.year, t.month
    return y, m


def register_routes(app):

    # ── PWA: service worker root scope'da bo'lishi shart ────────
    @app.route("/sw.js")
    def sw():
        from flask import send_from_directory
        resp = send_from_directory(app.static_folder, "sw.js",
                                   mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ── Dashboard ────────────────────────────────────────────────
    @app.route("/")
    def dashboard():
        return render_template("dashboard.html", d=core.dashboard_data(),
                               pray=praytimes.today_with_next())

    # ── Tranzaksiyalar ───────────────────────────────────────────
    def _tx_filters():
        """URL parametrlaridan filtr yig'adi: (query, ctx)."""
        today = date.today()
        args = request.args
        preset = args.get("p", "")
        d_from = args.get("from", "")
        d_to = args.get("to", "")

        # tez tanlovlar sanalarni belgilaydi
        if preset == "today":
            d_from = d_to = today.isoformat()
        elif preset == "week":
            d_from = (today - timedelta(days=today.weekday())).isoformat()
            d_to = today.isoformat()
        elif preset == "month":
            d_from = today.replace(day=1).isoformat()
            d_to = today.isoformat()
        elif preset == "prev":
            first = today.replace(day=1)
            last_prev = first - timedelta(days=1)
            d_from = last_prev.replace(day=1).isoformat()
            d_to = last_prev.isoformat()
        elif preset == "year":
            d_from = date(today.year, 1, 1).isoformat()
            d_to = today.isoformat()
        elif not d_from and not d_to:
            # standart: joriy oy
            d_from = today.replace(day=1).isoformat()
            d_to = today.isoformat()

        def _d(v):
            try:
                return date.fromisoformat(v)
            except (ValueError, TypeError):
                return None

        q = Transaction.query
        df, dt = _d(d_from), _d(d_to)
        if df:
            q = q.filter(Transaction.tdate >= df)
        if dt:
            q = q.filter(Transaction.tdate <= dt)
        d_from, d_to = (df.isoformat() if df else ""), (dt.isoformat() if dt else "")

        w = args.get("w", "")
        if w:
            q = q.filter(db.or_(Transaction.wallet_code == w,
                                Transaction.transfer_to_wallet == w))
        op = args.get("op", "")
        if op == "transfer":
            q = q.filter(db.or_(Transaction.is_transfer.is_(True),
                                Transaction.activity == "tech"))
        elif op in ("kirim", "chiqim"):
            q = q.filter(Transaction.operation == op,
                         Transaction.is_transfer.is_(False),
                         Transaction.activity != "tech")
        cat = args.get("cat", "")
        if cat:
            q = q.filter(Transaction.category == cat)
        ch = args.get("ch", "")
        if ch:
            q = q.filter(Transaction.channel == ch)
        text = args.get("q", "").strip()
        if text:
            like = f"%{text}%"
            q = q.filter(db.or_(Transaction.counterparty.ilike(like),
                                Transaction.comment.ilike(like),
                                Transaction.category.ilike(like)))
        amin, amax = args.get("amin", ""), args.get("amax", "")
        def _f(v):
            try:
                return float(str(v).replace(" ", "").replace("\u00a0", "")
                             .replace(",", "."))
            except (ValueError, TypeError):
                return None
        if _f(amin) is not None:
            q = q.filter(Transaction.amount >= _f(amin))
        if _f(amax) is not None:
            q = q.filter(Transaction.amount <= _f(amax))

        sort = args.get("sort", "date_desc")
        order = {
            "date_desc": (Transaction.tdate.desc(), Transaction.id.desc()),
            "date_asc": (Transaction.tdate.asc(), Transaction.id.asc()),
            "amount_desc": (Transaction.amount.desc(),),
            "amount_asc": (Transaction.amount.asc(),),
        }.get(sort, (Transaction.tdate.desc(), Transaction.id.desc()))
        q = q.order_by(*order)

        ctx = {"d_from": d_from, "d_to": d_to, "w": w, "op": op, "cat": cat,
               "ch": ch, "q": text, "amin": amin, "amax": amax,
               "sort": sort, "preset": preset}
        return q, ctx

    @app.route("/transactions")
    def transactions():
        q, ctx = _tx_filters()
        rows = q.all()
        # filtrlangan natija bo'yicha jamlama (transferlar hisobga olinmaydi)
        real = [t for t in rows if not t.is_transfer and t.activity != "tech"]
        inc = sum(t.amount for t in real if t.operation == "kirim")
        exp = sum(t.amount for t in real if t.operation == "chiqim")
        # sahifalash
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        per = 60
        pages = max(1, (len(rows) + per - 1) // per)
        page = min(page, pages)
        chunk = rows[(page - 1) * per: page * per]

        wallets = Wallet.query.filter_by(is_active=True).order_by(Wallet.sort).all()
        cats = sorted({t.category for t in Transaction.query
                       .with_entities(Transaction.category).distinct()
                       if t.category})
        return render_template("transactions.html", txs=chunk, f=ctx,
                               wallets=wallets, cats=cats,
                               total=len(rows), page=page, pages=pages,
                               sum_inc=inc, sum_exp=exp, sum_net=inc - exp)

    @app.route("/transactions/export")
    def transactions_export():
        q, ctx = _tx_filters()
        out = ["Sana;Amal;Hamyon;Summa;Statya;Kanal;Kontragent;Izoh"]
        for t in q.all():
            op = "Transfer" if t.is_transfer else ("Kirim" if t.operation == "kirim" else "Chiqim")
            row = [t.tdate.strftime("%d.%m.%Y"), op,
                   t.wallet_code + (f"→{t.transfer_to_wallet}" if t.is_transfer else ""),
                   f"{t.amount:.0f}", t.category or "", t.channel or "",
                   (t.counterparty or "").replace(";", ","),
                   (t.comment or "").replace(";", ",")]
            out.append(";".join(row))
        csv = "\ufeff" + "\r\n".join(out)
        name = f"kassa_{ctx['d_from']}_{ctx['d_to']}.csv"
        return Response(csv, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.route("/transactions/add", methods=["POST"])
    def add_transaction():
        f = request.form
        t = Transaction(
            tdate=_parse_date(f.get("tdate")),
            wallet_code=f.get("wallet_code", ""),
            operation=f.get("operation", "kirim"),
            amount=float(f.get("amount") or 0),
            category=f.get("category", ""),
            counterparty=f.get("counterparty", ""),
            comment=f.get("comment", ""),
            channel=f.get("channel", ""),
        )
        if f.get("operation") == "transfer":
            t.operation, t.is_transfer = "chiqim", True
            t.transfer_to_wallet = f.get("transfer_to", "")
            t.category = "Transfer"
        if t.amount <= 0:
            flash("Summa noto'g'ri", "error")
            return redirect(url_for("transactions"))
        db.session.add(t)
        db.session.commit()
        flash("Yozildi", "ok")
        return redirect(url_for("transactions"))

    @app.route("/transactions/<int:tid>/delete", methods=["POST"])
    def delete_transaction(tid):
        t = db.session.get(Transaction, tid)
        if t:
            db.session.delete(t)
            db.session.commit()
            flash("O'chirildi", "ok")
        return redirect(url_for("transactions"))

    # ── Kurslar / oqimlar ────────────────────────────────────────
    @app.route("/cohorts")
    def cohorts():
        return render_template("cohorts.html", rows=core.cohort_report(),
                               courses=Course.query.filter_by(is_active=True).all())

    @app.route("/cohorts/add", methods=["POST"])
    def add_cohort():
        f = request.form
        course_id = f.get("course_id")
        if course_id == "_new" and f.get("new_course"):
            c = Course(name=f["new_course"],
                       base_price=float(f.get("base_price") or 0))
            db.session.add(c)
            db.session.flush()
            course_id = c.id
        ch = Cohort(
            course_id=int(course_id),
            name=f.get("name", "Yangi oqim"),
            start_date=_parse_date(f.get("start_date")),
            end_date=_parse_date(f.get("end_date"),
                                 date.today() + timedelta(days=60)),
            capacity=int(f.get("capacity") or 30),
        )
        db.session.add(ch)
        db.session.flush()
        automation.log_event(
            "contract", f"Yangi oqim ochildi: {ch.course.name} — {ch.name}",
            "Oqim yaratildi — kartada Launch-hisob havolasi tayyor")
        db.session.commit()
        # foydalanuvchi shu sahifada qoladi — yangi oqim kartasi darhol
        # ko'rinadi; Launch-hisob kartadagi tugma orqali ochiladi
        flash(f"«{ch.name}» oqimi ochildi — quyida kartasi ko'rinib turibdi. "
              "Zararsizlik tahlili kartadagi «Launch-hisob →» tugmasida.", "ok")
        return redirect(url_for("cohorts"))

    # ── Launch-kalkulyator: yangi kurs marja/BEP tahlili ────────
    @app.route("/planner")
    def launch_planner():
        courses = Course.query.filter_by(is_active=True).all()
        f = request.args

        def num(key, default=0.0):
            v = ((f.get(key, "") or "").replace(" ", "")
                 .replace("\u00a0", "").replace(",", "."))
            try:
                return float(v)
            except ValueError:
                return default

        sel = {k: f.get(k, v) for k, v in [
            ("course_id", ""), ("new_name", ""), ("price", ""),
            ("capacity", "40"), ("duration", "60"),
            ("discount", "0"), ("sales", "10"), ("material", "150000"),
            ("teacher_mode", "hourly"), ("hours", "24"), ("cat", "A"),
            ("teacher_fix", ""), ("extra", "0"),
            ("cac_mode", "funnel"), ("cpl", "35000"), ("cac", ""),
            ("cr1", "50"), ("cr2", "48"), ("cr3", "33"),
            ("share", ""), ("target", "0")]}

        result = None
        if f.get("price"):
            course = db.session.get(Course, int(f.get("course_id") or 0))
            cname = course.name if course else (f.get("new_name") or "Yangi kurs")
            # o'qituvchi to'lovi: soatbay yoki qat'iy
            if sel["teacher_mode"] == "hourly":
                rate = planner.MENTOR_RATES.get(sel["cat"], 150_000)
                teacher = num("hours", 24) * rate
            else:
                teacher = num("teacher_fix", 0)
            share = num("share", -1)
            try:
                result = planner.plan_v2(
                    price=num("price"), capacity=int(num("capacity", 40)),
                    duration_days=int(num("duration", 60)),
                    discount_pct=num("discount") / 100,
                    sales_pct=num("sales") / 100,
                    material_per_student=num("material"),
                    teacher_cost=teacher, extra_fixed=num("extra"),
                    fixed_share=(share / 100) if share >= 0 else None,
                    cac=(num("cac") if sel["cac_mode"] == "direct" and f.get("cac") else None),
                    cpl=(num("cpl") if sel["cac_mode"] == "funnel" else None),
                    funnel={"cr_quality": num("cr1", 50) / 100,
                            "cr_demo": num("cr2", 48) / 100,
                            "cr_sale": num("cr3", 33) / 100},
                    target_profit=num("target"),
                    course_name=cname)
                result["course_name"] = cname
                result["teacher_cost_calc"] = teacher
            except (ValueError, ZeroDivisionError) as e:
                flash(f"Kiritilgan qiymatlarni tekshiring: {e}", "err")
        return render_template("planner.html", courses=courses, sel=sel,
                               r=result, rates=planner.MENTOR_RATES)

    # ── Shartnomalar ─────────────────────────────────────────────
    @app.route("/contracts")
    def contracts():
        status = request.args.get("status", "active")
        board = core.contracts_board(status)
        tot = {
            "cohorts": len([r for r in board if r["count"]]),
            "students": sum(r["count"] for r in board),
            "price": sum(r["price"] for r in board),
            "paid": sum(r["paid"] for r in board),
            "overdue": sum(r["overdue"] for r in board),
            "overdue_n": sum(r["overdue_n"] for r in board),
        }
        tot["paid_pct"] = (tot["paid"] / tot["price"] * 100) if tot["price"] else 0
        return render_template("contracts.html", board=board, tot=tot,
                               status=status,
                               cohorts=Cohort.query.order_by(
                                   Cohort.start_date.desc()).all())

    @app.route("/contracts/add", methods=["POST"])
    def add_contract():
        f = request.form
        student = Student(name=f.get("student_name", "").strip(),
                          phone=f.get("phone", ""),
                          source=f.get("source", ""))
        if not student.name:
            flash("O'quvchi ismi kerak", "error")
            return redirect(url_for("contracts"))
        db.session.add(student)
        db.session.flush()
        cohort = db.session.get(Cohort, int(f.get("cohort_id") or 0))
        if not cohort:
            flash("Oqim tanlanmagan — avval Oqimlar sahifasida oqim oching", "error")
            return redirect(url_for("contracts"))
        price = float(f.get("price") or 0)
        c = Contract(student_id=student.id,
                     cohort_id=cohort.id,
                     price=price,
                     discount=float(f.get("discount") or 0),
                     signed_date=_parse_date(f.get("signed_date")))
        db.session.add(c)
        db.session.flush()
        # Bo'lib to'lash grafigi: N oyga teng taqsim, imzo kunidan boshlab
        n = max(int(f.get("installments") or 1), 1)
        per = c.net_price / n
        for i in range(n):
            due = c.signed_date + timedelta(days=30 * i)
            db.session.add(InstallmentLine(contract_id=c.id,
                                           due_date=due, amount=per))
        steps, welcome = automation.on_contract_created(c, n)
        db.session.commit()
        flash(f"Shartnoma yaratildi — {len(steps)} jarayon avtomatik bajarildi", "ok")
        return redirect(url_for("contract_detail", cid=c.id, welcome=1))

    @app.route("/contracts/<int:cid>")
    def contract_detail(cid):
        c = db.session.get(Contract, cid)
        if not c:
            return redirect(url_for("contracts"))
        recognized = core.contract_recognized(c)
        txs = Transaction.query.filter_by(contract_id=cid).order_by(
            Transaction.tdate.desc()).all()
        wallets = Wallet.query.filter_by(is_active=True).order_by(Wallet.sort).all()
        receipt = welcome = None
        if request.args.get("receipt") and txs:
            receipt = automation.receipt_text(c, txs[0].amount)
        if request.args.get("welcome"):
            welcome = automation.welcome_text(c)
        return render_template("contract_detail.html", c=c,
                               recognized=recognized, txs=txs, wallets=wallets,
                               receipt=receipt, welcome=welcome)

    @app.route("/contracts/<int:cid>/pay", methods=["POST"])
    def contract_pay(cid):
        """To'lov qabul qilish: kassaga yoziladi + grafikka taqsimlanadi."""
        c = db.session.get(Contract, cid)
        f = request.form
        amount = float(f.get("amount") or 0)
        if not c or amount <= 0:
            flash("Summa noto'g'ri", "error")
            return redirect(url_for("contract_detail", cid=cid))
        db.session.add(Transaction(
            tdate=_parse_date(f.get("tdate")),
            wallet_code=f.get("wallet_code", ""),
            operation="kirim", amount=amount,
            category=income_cat_for_course(c.cohort.course.name),
            counterparty=c.student.name,
            contract_id=c.id,
            comment=f.get("comment", "")))
        # FIFO: eng eski to'lanmagan grafik qatoridan boshlab yopiladi
        rest = amount
        for line in c.lines:
            need = line.amount - line.paid
            if need <= 0.01 or rest <= 0:
                continue
            pay = min(need, rest)
            line.paid += pay
            rest -= pay
        # ── AVTOMATIKA ZANJIRI: bir amal -> bir nechta jarayon ──
        steps, receipt = automation.on_payment(c, amount, f.get("wallet_code", ""))
        db.session.commit()
        flash(f"To'lov qabul qilindi — {len(steps)} jarayon avtomatik bajarildi", "ok")
        return redirect(url_for("contract_detail", cid=cid, receipt=1))

    @app.route("/contracts/<int:cid>/status", methods=["POST"])
    def contract_status(cid):
        c = db.session.get(Contract, cid)
        f = request.form
        if c:
            c.status = f.get("status", c.status)
            if c.status == "refunded":
                refund = float(f.get("refund_amount") or c.paid_total())
                c.refund_amount = refund
                wallet = f.get("wallet_code", "")
                if refund > 0 and wallet:
                    db.session.add(Transaction(
                        tdate=date.today(), wallet_code=wallet,
                        operation="chiqim", amount=refund,
                        category="Возврат клиенту",
                        counterparty=c.student.name,
                        contract_id=c.id,
                        comment="Pul qaytarish (kafolat)"))
                    automation.on_refund(c, refund)
            db.session.commit()
            flash("Holat yangilandi", "ok")
        return redirect(url_for("contract_detail", cid=cid))

    # ── Qarzdorlik ───────────────────────────────────────────────
    @app.route("/debtors")
    def debtors():
        return render_template("debtors.html",
                               overdue=core.overdue_lines(),
                               upcoming=core.upcoming_lines(14))

    # ── Yillik ДДС (Sheets formati) ─────────────────────────────
    # ── To'lov taqvimi (платежный календарь) ─────────────────────
    @app.route("/taqvim")
    def taqvim():
        import paycal
        y, m = _ym()
        view = request.args.get("view", "month")
        oy = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
              "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]
        if view == "year":
            data = paycal.year_data(y)
            return render_template("taqvim.html", view="year", y=y, m=m,
                                   d=data, oy=oy)
        data = paycal.month_data(y, m)
        return render_template("taqvim.html", view="month", y=y, m=m,
                               d=data, oy=oy)

    @app.route("/taqvim/set", methods=["POST"])
    def taqvim_set():
        import paycal
        f = request.form
        try:
            y, m, day = int(f["y"]), int(f["m"]), int(f["d"])
            raw = (f.get("amount") or "0").replace(" ", "") \
                .replace(" ", "").replace(",", ".")
            amount = float(raw or 0)
            cat = f["cat"]
        except (KeyError, ValueError):
            return {"ok": False}, 400
        res = paycal.set_cell(y, m, day, cat, amount)
        res["ok"] = True
        return res

    @app.route("/taqvim/fill", methods=["POST"])
    def taqvim_fill():
        import paycal
        y, m = _ym()
        r = paycal.fill_from_recurring(y, m)
        flash(f"Takrorlanuvchi to'lovlardan {r['made']} katak to'ldirildi"
              + (f", {r['skipped']} tasi allaqachon band edi" if r['skipped']
                 else "") + ".", "ok")
        return redirect(url_for("taqvim", y=y, m=m))

    @app.route("/taqvim/copy", methods=["POST"])
    def taqvim_copy():
        import paycal
        y, m = _ym()
        r = paycal.copy_from_prev(y, m)
        flash(f"{r['pm']:02d}.{r['py']} rejasidan {r['made']} katak "
              f"ko'chirildi" + (f", {r['skipped']} tasi band edi"
                                if r['skipped'] else "") + ".", "ok")
        return redirect(url_for("taqvim", y=y, m=m))

    @app.route("/taqvim/clear", methods=["POST"])
    def taqvim_clear():
        import paycal
        y, m = _ym()
        n = paycal.clear_month(y, m)
        flash(f"{n} ta reja katagi o'chirildi.", "ok")
        return redirect(url_for("taqvim", y=y, m=m))

    @app.route("/dds")
    def dds():
        try:
            year = int(request.args.get("year", date.today().year))
        except ValueError:
            year = date.today().year
        view = request.args.get("view", "xl")     # xl — Sheets ko'rinishi
        if view == "xl":
            return render_template("dds_excel.html", x=core.dds_excel(year),
                                   year=year)
        return render_template("dds.html", d=core.dds_matrix(year))

    # ── Shartnomalarni to'lovlardan tiklash ───────────────────────
    @app.route("/contracts/tiklash")
    def recover_page():
        cands = recover.candidates()
        groups = []
        for tag in sorted({c["tag"] for c in cands}):
            rows = [c for c in cands if c["tag"] == tag]
            groups.append({"tag": tag, "rows": rows,
                           "paid": sum(r["paid"] for r in rows),
                           "cohorts": recover.cohorts_for(tag)})
        groups.sort(key=lambda g: -g["paid"])
        return render_template(
            "recover.html", groups=groups, skipped=recover.skipped(),
            made=Contract.query.filter(
                Contract.note.like(f"%{recover.MARK}%")).count(),
            courses=Course.query.order_by(Course.name).all())

    @app.route("/contracts/tiklash/yaratish", methods=["POST"])
    def recover_create():
        f = request.form
        keys = f.getlist("pick")
        ok, errs = 0, []
        for k in keys:
            ids = [int(x) for x in (f.get(f"ids_{k}") or "").split(",") if x]
            _, err = recover.create(
                ids, int(f.get(f"cohort_{k}") or 0),
                f.get(f"name_{k}", ""),
                price=_num(f.get(f"price_{k}")))
            if err:
                errs.append(f"{f.get(f'name_{k}', k)}: {err}")
            else:
                ok += 1
        if ok:
            flash(f"{ok} ta shartnoma yaratildi va to'lovlari bog'landi", "ok")
        for e in errs[:4]:
            flash(e, "err")
        return redirect(url_for("recover_page"))

    @app.route("/contracts/tiklash/oqim", methods=["POST"])
    def recover_cohort():
        f = request.form
        cid = int(f.get("course_id") or 0)
        if not db.session.get(Course, cid):
            flash("Kurs tanlanmagan", "err")
            return redirect(url_for("recover_page"))
        ch = Cohort(course_id=cid, name=f.get("name", "").strip() or "Yangi oqim",
                    start_date=_parse_date(f.get("start_date")),
                    end_date=_parse_date(f.get("end_date")),
                    capacity=int(f.get("capacity") or 30))
        db.session.add(ch)
        db.session.commit()
        flash(f"«{ch.name}» oqimi ochildi", "ok")
        return redirect(url_for("recover_page"))

    @app.route("/contracts/tiklash/bekor", methods=["POST"])
    def recover_undo():
        n = recover.undo_all()
        flash(f"{n} ta tiklangan shartnoma olib tashlandi, "
              f"to'lovlar bog'lanmagan holatga qaytdi", "ok")
        return redirect(url_for("recover_page"))

    # ── Juftlanmagan o'tkazmalar ──────────────────────────────────
    # Hamyon qoldig'i manfiy chiqsa deyarli har doim sababi shu: o'tkazmaning
    # bir tomoni ДДС ga yozilgan, ikkinchisi yozilmagan.
    @app.route("/transfers")
    def transfers_page():
        return render_template("transfers.html", d=transfers.report(),
                               wallets=transfers.wallet_names())

    @app.route("/transfers/<int:rid>/juft", methods=["POST"])
    def transfer_fix(rid):
        row = db.session.get(DdsRow, rid)
        if row is None:
            abort(404)
        f = request.form
        amt = (f.get("amount") or "").replace(" ", "").replace(" ", "")
        try:
            amt = float(amt.replace(",", ".")) if amt else None
        except ValueError:
            amt = None
        try:
            dd = date.fromisoformat(f.get("ddate")) if f.get("ddate") else None
        except ValueError:
            dd = None
        new, err = transfers.add_counterpart(
            row, f.get("wallet", "").strip(), amount=amt, ddate=dd,
            purpose=(f.get("purpose") or "").strip() or None)
        if err:
            flash(err, "err")
        else:
            flash(f"Juft qator qo'shildi (#{new.rownum}) — "
                  f"hamyon qoldig'i yangilandi", "ok")
        return redirect(url_for("transfers_page"))

    # ── «ДДС данные» — Excel varag'ining 1:1 nusxasi ──────────────
    @app.route("/ddsdata")
    def ddsdata():
        a = request.args
        q = DdsRow.query
        # ustun filtrlari (Google Sheets filtrlari kabi)
        fm = a.getlist("m")            # Мсц
        fy = a.getlist("y")            # Год
        fw = a.getlist("w")            # Кошелек
        fw2 = a.getlist("w2")          # Кошелек 2
        fa = a.getlist("a")            # Статья
        ff = a.getlist("f")            # Платеж/поступл
        fv = a.getlist("v")            # Вид д-ти
        txt = (a.get("q") or "").strip()
        d1, d2 = a.get("d1", ""), a.get("d2", "")
        s1, s2 = a.get("s1", ""), a.get("s2", "")

        if fw:
            q = q.filter(DdsRow.wallet.in_(fw))
        if fw2:
            q = q.filter(DdsRow.wallet2.in_(fw2))
        if fa:
            q = q.filter(DdsRow.article.in_(fa))
        if txt:
            like = f"%{txt}%"
            q = q.filter(db.or_(DdsRow.purpose.ilike(like),
                                DdsRow.article.ilike(like)))

        def _d(v):
            try:
                return date.fromisoformat(v)
            except (ValueError, TypeError):
                return None
        if _d(d1):
            q = q.filter(DdsRow.ddate >= _d(d1))
        if _d(d2):
            q = q.filter(DdsRow.ddate <= _d(d2))

        def _f(v):
            try:
                return float(str(v).replace(" ", "").replace("\u00a0", "")
                             .replace(",", "."))
            except (ValueError, TypeError):
                return None
        if _f(s1) is not None:
            q = q.filter(DdsRow.amount >= _f(s1))
        if _f(s2) is not None:
            q = q.filter(DdsRow.amount <= _f(s2))

        # saralash — ustun sarlavhasidagi «А→Я / Я→А» (Sheets kabi)
        sort = a.get("sort", "row")
        order = {
            "row": DdsRow.rownum.asc(),
            "row_d": DdsRow.rownum.desc(),
            "date": DdsRow.ddate.asc(),
            "date_d": DdsRow.ddate.desc(),
            "sum": DdsRow.amount.asc(),
            "sum_d": DdsRow.amount.desc(),
            "w": DdsRow.wallet.asc(),
            "w_d": DdsRow.wallet.desc(),
            "w2": DdsRow.wallet2.asc(),
            "w2_d": DdsRow.wallet2.desc(),
            "purpose": DdsRow.purpose.asc(),
            "purpose_d": DdsRow.purpose.desc(),
            "a": DdsRow.article.asc(),
            "a_d": DdsRow.article.desc(),
        }.get(sort, DdsRow.rownum.asc())
        rows = q.order_by(order).all()

        # formula ustunlari bo'yicha filtrlash (Python tomonda)
        if fm:
            rows = [r for r in rows if str(r.month) in fm]
        if fy:
            rows = [r for r in rows if str(r.year) in fy]
        if ff:
            rows = [r for r in rows if r.flow in ff]
        if fv:
            rows = [r for r in rows if r.activity in fv]

        # formula ustunlari — saralash ham Python tomonda
        _pysort = {
            "m": (lambda r: r.month or 0, False),
            "m_d": (lambda r: r.month or 0, True),
            "y": (lambda r: r.year or 0, False),
            "y_d": (lambda r: r.year or 0, True),
            "f": (lambda r: r.flow, False),
            "f_d": (lambda r: r.flow, True),
            "v": (lambda r: r.activity, False),
            "v_d": (lambda r: r.activity, True),
        }.get(sort)
        if _pysort:
            rows.sort(key=_pysort[0], reverse=_pysort[1])

        inc = sum(r.amount for r in rows if r.flow == "Поступление")
        exp = sum(r.amount for r in rows if r.flow == "Выбытие")

        # filtr ro'yxatlari uchun noyob qiymatlar (butun jadvaldan)
        allr = DdsRow.query.all()
        uniq = {
            "m": sorted({str(r.month) for r in allr if r.month != ""},
                        key=lambda x: int(x)),
            "y": sorted({str(r.year) for r in allr if r.year != ""}),
            "w": [w for w in DDS_WALLETS if any(r.wallet == w for r in allr)],
            "w2": [w for w in DDS_WALLET2 if any(r.wallet2 == w for r in allr)],
            "a": sorted({r.article for r in allr if r.article}),
            "f": ["Поступление", "Выбытие"],
            "v": ["Операционная", "Техническая операция", "Финансовая",
                  "Инвестиционная"],
        }
        sel = {"m": fm, "y": fy, "w": fw, "w2": fw2, "a": fa, "f": ff, "v": fv,
               "q": txt, "d1": d1, "d2": d2, "s1": s1, "s2": s2, "sort": sort}
        return render_template("ddsdata.html", rows=rows, uniq=uniq, sel=sel,
                               total=len(rows), all_total=len(allr),
                               inc=inc, exp=exp,
                               wallets=DDS_WALLETS, wallets2=DDS_WALLET2,
                               articles=[a for a, _, _ in DDS_SPRAVOCHNIK],
                               lookup=DDS_LOOKUP)

    @app.route("/ddsdata/add", methods=["POST"])
    def ddsdata_add():
        f = request.form
        try:
            d = date.fromisoformat(f.get("ddate"))
        except (ValueError, TypeError):
            flash("Sanani tekshiring", "err")
            return redirect(url_for("ddsdata"))
        amt = (f.get("amount") or "0").replace(" ", "").replace("\u00a0", "")
        try:
            amt = float(amt.replace(",", "."))
        except ValueError:
            amt = 0.0
        last = db.session.query(db.func.max(DdsRow.rownum)).scalar() or 2
        row = DdsRow(rownum=last + 1, ddate=d, amount=amt,
                     wallet=f.get("wallet", ""),
                     wallet2=f.get("wallet2", ""),
                     purpose=f.get("purpose", "").strip(),
                     article=f.get("article", ""))
        db.session.add(row)
        db.session.flush()

        # ── ZANJIR: bitta qator → kassa → moslash ──
        steps = []
        tx = ddsflow.sync_row(row)
        if tx:
            steps.append("kassaga yozildi")
            steps.append("hamyon qoldig'i yangilandi")
        else:
            _, why = ddsflow.check_row(row)
            flash(f"Kassaga tushmadi: {why}", "err")
        res = matching.auto_match(row)
        if res == "auto":
            steps.append(f"shartnomaga bog'landi ({row.contract.student.name})")
            steps.append("to'lov grafigi yopildi")
        elif res == "none":
            steps.append("«Tanilmagan to'lovlar» navbatiga qo'yildi")
        db.session.commit()
        if steps:
            flash("Qator qo'shildi — " + ", ".join(steps), "ok")
        return redirect(url_for("ddsdata"))

    @app.route("/ddsdata/<int:rid>/delete", methods=["POST"])
    def ddsdata_delete(rid):
        row = db.session.get(DdsRow, rid)
        if row:
            # avval ta'sirini qaytaramiz (kassa yozuvi + grafik), keyin o'chiramiz
            ddsflow.unsync_row(row)
            db.session.delete(row)
            db.session.commit()
            flash("Qator o'chirildi — kassa yozuvi va grafikdagi ta'siri "
                  "ham qaytarildi", "ok")
        return redirect(request.referrer or url_for("ddsdata"))

    @app.route("/ddsdata/<int:rid>/edit", methods=["POST"])
    def ddsdata_edit(rid):
        """Qatorni tahrirlash — kassa yozuvi ham o'zi yangilanadi."""
        row = db.session.get(DdsRow, rid)
        if not row:
            return redirect(url_for("ddsdata"))
        f = request.form
        # Avval eski bog'lanishni yechamiz — hali eski summa/ism o'rnida
        # turganda. Keyin tahrirlaymiz va qaytadan moslaymiz.
        matching.unapply(row)
        try:
            row.ddate = date.fromisoformat(f.get("ddate"))
        except (ValueError, TypeError):
            pass
        amt = (f.get("amount") or "").replace(" ", "").replace("\u00a0", "")
        try:
            row.amount = float(amt.replace(",", "."))
        except ValueError:
            pass
        for k in ("wallet", "wallet2", "purpose", "article"):
            if k in f:
                setattr(row, k, f.get(k, "").strip())
        ddsflow.sync_row(row)
        matching.auto_match(row)
        db.session.commit()
        flash("Qator yangilandi — kassa va grafik qayta hisoblandi", "ok")
        return redirect(request.referrer or url_for("ddsdata"))

    @app.route("/ddsdata/rebuild", methods=["POST"])
    def ddsdata_rebuild():
        """Butun ДДС'ni kassaga qayta yozish + moslashni qayta ishga tushirish."""
        r = ddsflow.rebuild_all()
        m = matching.run_all()
        flash(f"Kassa qayta qurildi: {r['made']} yozuv "
              f"({r['skipped']} o'tkazildi). Moslash: {m['auto']} avtomat, "
              f"{m['queued']} navbatda.", "ok")
        return redirect(request.referrer or url_for("ddsdata"))

    @app.route("/ddsdata/export")
    def ddsdata_export():
        rows = DdsRow.query.order_by(DdsRow.rownum).all()
        out = ["Мсц (цифрой);Год (цифрой);Дата;Сумма;Кошелек;Кошелек;"
               "Назначение платежа;Статья;Платеж/поступл;Вид д-ти"]
        for r in rows:
            out.append(";".join([
                str(r.month), str(r.year),
                r.ddate.strftime("%d.%m.%Y") if r.ddate else "",
                f"{r.amount:.2f}".replace(".", ","),
                r.wallet, r.wallet2,
                (r.purpose or "").replace(";", ","),
                r.article, r.flow, r.activity]))
        csv = "\ufeff" + "\r\n".join(out)
        return Response(csv, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="DDS_dannie.csv"'})

    # ── To'lovlar navbati («Tanilmagan to'lovlar») ────────────────
    @app.route("/inbox")
    def payments_inbox():
        show = request.args.get("show", "open")
        art = request.args.get("art", "")
        month = request.args.get("oy", "")
        items = matching.inbox(show=show, art=art, month=month)
        return render_template("inbox.html", items=items, show=show,
                               art=art, month=month,
                               months=matching.inbox_months(show),
                               st=matching.stats(),
                               cohorts=Cohort.query.order_by(
                                   Cohort.start_date.desc()).all())

    @app.route("/inbox/bulk", methods=["POST"])
    def inbox_bulk():
        """Belgilangan qatorlarni birdan chetlatish yoki qaytarish."""
        ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
        if not ids:
            flash("Hech narsa belgilanmagan", "err")
            return redirect(request.referrer or url_for("payments_inbox"))
        if request.form.get("act") == "restore":
            n = matching.bulk_restore(ids)
            flash(f"{n} ta to'lov navbatga qaytarildi", "ok")
        else:
            n = matching.bulk_skip(ids, request.form.get("reason", ""))
            flash(f"{n} ta to'lov chetlatildi", "ok")
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/link", methods=["POST"])
    def inbox_link(rid):
        """Taklif qilingan shartnomaga bog'lash (bir bosish)."""
        row = db.session.get(DdsRow, rid)
        c = db.session.get(Contract, int(request.form.get("contract_id") or 0))
        if not row or not c:
            flash("Qator yoki shartnoma topilmadi", "err")
            return redirect(url_for("payments_inbox"))
        left = matching.apply(row, c, status="manual")
        automation.log_event(
            "payment",
            f"To'lov bog'landi: {c.student.name} — "
            + f"{row.amount:,.0f}".replace(",", " ") + " so'm",
            f"ДДС qatori #{row.rownum} → shartnoma #{c.id}", c.id)
        db.session.commit()
        msg = f"Bog'landi: {c.student.name}"
        if left > 0.01:
            msg += f" · {left:,.0f} so'm avans bo'lib qoldi".replace(",", " ")
        flash(msg, "ok")
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/unlink", methods=["POST"])
    def inbox_unlink(rid):
        row = db.session.get(DdsRow, rid)
        if row:
            matching.unapply(row)
            db.session.commit()
            flash("Bog'lanish bekor qilindi — grafik qaytarildi", "ok")
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/skip", methods=["POST"])
    def inbox_skip(rid):
        """«Bu shartnomaga tegishli emas» — navbatdan olib tashlash."""
        row = db.session.get(DdsRow, rid)
        if row:
            matching.unapply(row)
            row.match_status = "skipped"
            row.skip_note = (request.form.get("reason") or "").strip()[:200]
            db.session.commit()
            flash("Navbatdan olib tashlandi", "ok")
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/restore", methods=["POST"])
    def inbox_restore(rid):
        row = db.session.get(DdsRow, rid)
        if row:
            row.match_status = "none"
            row.skip_note = ""
            db.session.commit()
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/contract", methods=["POST"])
    def inbox_new_contract(rid):
        """3-BOSQICH: navbatdan turib shartnoma ochish.

        O'quvchi ismi, yo'nalish va birinchi to'lov summasi allaqachon
        ma'lum — ROP faqat narx, oqim va bo'lib to'lash sonini kiritadi.
        """
        row = db.session.get(DdsRow, rid)
        if not row:
            return redirect(url_for("payments_inbox"))
        f = request.form
        cohort = db.session.get(Cohort, int(f.get("cohort_id") or 0))
        if not cohort:
            flash("Oqim tanlanmagan — avval Oqimlar sahifasida oqim oching",
                  "err")
            return redirect(url_for("payments_inbox"))
        name = (f.get("student_name") or row.purpose or "").strip()
        if not name:
            flash("O'quvchi ismi kerak", "err")
            return redirect(url_for("payments_inbox"))
        student, is_new = matching.find_or_create_student(
            name, source=f.get("source", ""))
        if f.get("phone"):
            student.phone = f.get("phone")

        price = float(f.get("price") or 0) or cohort.course.base_price
        c = Contract(student_id=student.id, cohort_id=cohort.id,
                     price=price, discount=float(f.get("discount") or 0),
                     signed_date=row.ddate or date.today())
        db.session.add(c)
        db.session.flush()
        n = max(int(f.get("installments") or 1), 1)
        per = c.net_price / n
        for i in range(n):
            db.session.add(InstallmentLine(
                contract_id=c.id,
                due_date=c.signed_date + timedelta(days=30 * i), amount=per))
        db.session.flush()
        automation.on_contract_created(c, n)
        matching.apply(row, c, status="manual")
        db.session.commit()
        flash(f"Shartnoma ochildi va to'lov bog'landi — {student.name}"
              + (" (yangi o'quvchi)" if is_new else ""), "ok")
        return redirect(url_for("contract_detail", cid=c.id, welcome=1))

    @app.route("/inbox/rerun", methods=["POST"])
    def inbox_rerun():
        r = matching.run_all()
        flash(f"Qayta ko'rildi: {r['auto']} avtomat bog'landi, "
              f"{r['queued']} navbatda qoldi", "ok")
        return redirect(url_for("payments_inbox"))

    # ── Hisobotlar ───────────────────────────────────────────────
    @app.route("/reports")
    def reports():
        y, m = _ym()
        an = {
            "pnl": analytics.pnl(y, m),
            "trend": analytics.trend(y, m),
            "cast": analytics.cash_forecast(y, m),
            "runway": analytics.runway(y, m),
            "dirs": analytics.directions(y, m),
            "dirs_year": analytics.directions(y),
            "aging": analytics.aging(),
            "refunds": analytics.refunds(y),
            "mix": analytics.expense_mix(y, m),
            "insights": analytics.insights(y, m),
        }
        chart_json = {
            "pnl": an["pnl"]["steps"],
            "trend": an["trend"],
            "cast": {"labels": an["cast"]["labels"], "cash": an["cast"]["cash"],
                     "bal": an["cast"]["bal"], "sched": an["cast"]["sched"]},
            "dirs": [{"name": d["name"], "income": round(d["income"]),
                      "margin": round(d["margin"]),
                      "margin_pct": round(d["margin_pct"], 1)}
                     for d in an["dirs_year"]],
            "mix": [{"cat": r["cat"], "val": round(r["val"])} for r in an["mix"]],
            "aging": [{"label": k, "val": round(v["sum"]), "n": v["n"]}
                      for k, v in an["aging"]["buckets"].items()],
            "refunds": an["refunds"]["by_month"],
        }
        return render_template("reports.html", y=y, m=m, an=an, cj=chart_json,
                               cf=core.month_cashflow(y, m),
                               acc=core.accrual_summary(),
                               ue=core.unit_economics(y, m),
                               bep=core.break_even(y, m),
                               cohorts=core.cohort_report(),
                               planfact=core.budget_planfact(y, m))

    @app.route("/budget/add", methods=["POST"])
    def add_budget():
        f = request.form
        y, m = int(f.get("year")), int(f.get("month"))
        b = Budget.query.filter_by(year=y, month=m,
                                   category=f.get("category"),
                                   btype=f.get("btype")).first()
        if not b:
            b = Budget(year=y, month=m, category=f.get("category"),
                       btype=f.get("btype"))
            db.session.add(b)
        b.planned = float(f.get("planned") or 0)
        db.session.commit()
        flash("Reja saqlandi", "ok")
        return redirect(url_for("reports", y=y, m=m))

    # ── Avtomatika markazi ──────────────────────────────────────
    @app.route("/automation")
    def automation_page():
        day = None
        if request.args.get("closed"):
            day = automation.close_day()
            db.session.commit()
        wallets = Wallet.query.filter_by(is_active=True).order_by(Wallet.sort).all()
        return render_template("automation.html", feed=automation.feed(),
                               day=day, wallets=wallets)

    @app.route("/automation/close-day", methods=["POST"])
    def close_day():
        return redirect(url_for("automation_page", closed=1))

    @app.route("/automation/reminded/<int:line_id>", methods=["POST"])
    def mark_reminded(line_id):
        automation.mark_reminded(line_id, request.form.get("channel", "manual"))
        db.session.commit()
        flash("Eslatma belgilandi — bugun qayta chiqmaydi", "ok")
        return redirect(url_for("automation_page", closed=1))

    @app.route("/automation/recurring/<int:rec_id>", methods=["POST"])
    def book_recurring(rec_id):
        r = automation.book_recurring(rec_id, request.form.get("wallet_code", ""))
        db.session.commit()
        flash(f"«{r.name}» kassaga yozildi" if r else "Topilmadi", "ok" if r else "error")
        return redirect(url_for("automation_page", closed=1))

    # ── Sozlamalar ───────────────────────────────────────────────
    # ── KPI ──
    @app.route("/kpi")
    def kpi_page():
        today = date.today()
        y = int(request.args.get("y", today.year))
        m = int(request.args.get("m", today.month))
        cards = kpi.ensure_month(y, m)
        data = [(c, kpi.compute(c)) for c in cards]
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        oy = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
              "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]
        return render_template("kpi.html", data=data, y=y, m=m,
                               py=py, pm=pm, ny=ny, nm=nm, oy_nomi=oy[m])

    @app.route("/kpi/<int:cid>/save", methods=["POST"])
    def kpi_save(cid):
        card = db.session.get(KpiCard, cid)
        if not card:
            flash("KPI kartasi topilmadi", "err")
            return redirect(url_for("kpi_page"))
        card.person = request.form.get("person", card.person).strip()
        for it in card.items:
            v = request.form.get(f"fact_{it.id}", "").strip()
            v = v.replace(" ", "").replace("\u00a0", "").replace(",", ".")
            it.fact = float(v) if v else None
        db.session.commit()
        flash(f"{card.role_name} — faktlar saqlandi", "ok")
        return redirect(url_for("kpi_page", y=card.year, m=card.month))

    @app.route("/kpi/<int:cid>/autofill", methods=["POST"])
    def kpi_autofill(cid):
        card = db.session.get(KpiCard, cid)
        if not card:
            flash("KPI kartasi topilmadi", "err")
            return redirect(url_for("kpi_page"))
        filled = kpi.autofill(card)
        if filled:
            flash("Moliyadan olindi: " + ", ".join(filled), "ok")
        else:
            flash("Bu kartada avtomatik ko'rsatkich yo'q", "err")
        return redirect(url_for("kpi_page", y=card.year, m=card.month))

    @app.route("/settings")
    def settings():
        import demo_data
        pins = {r: bool(roles.stored_pin(r)) for r in roles.ROLES}
        # O'quv bo'limi o'chiq nusxada kurator rolining ma'nosi qolmaydi
        shown = [r for r in roles.ROLES
                 if r != roles.KURATOR or roles.edu_enabled()]
        return render_template(
            "settings.html",
            wallets=Wallet.query.order_by(Wallet.sort).all(),
            demo=demo_data.count_demo(),
            locked=bool(roles.app_pin()), pins=pins,
            ROLES=shown, ROLE_LABELS=roles.ROLE_LABELS,
            ROLE_HINTS=roles.ROLE_HINTS, edu=roles.edu_enabled(),
            recurring=RecurringPayment.query.order_by(
                RecurringPayment.pay_day).all())

    @app.route("/settings/kod", methods=["POST"])
    def settings_pin():
        """Rol uchun kirish kodini o'rnatish yoki bekor qilish (direktor)."""
        role = request.form.get("role", "")
        if role not in roles.ROLES:
            flash("Noma'lum rol", "err")
            return redirect(url_for("settings"))
        if role == roles.DIREKTOR and roles.app_pin():
            flash("Direktor kodi APP_PIN muhit o'zgaruvchisidan olinadi — "
                  "uni Railway sozlamalaridan almashtiring.", "err")
            return redirect(url_for("settings"))

        key = f"pin_{role}"
        if request.form.get("act") == "clear":
            row = db.session.get(AppSetting, key)
            if row:
                db.session.delete(row)
                db.session.commit()
            flash(f"{roles.ROLE_LABELS[role]} kodi bekor qilindi — "
                  f"bu rol endi tizimga kira olmaydi.", "ok")
            return redirect(url_for("settings"))

        pin = "".join(ch for ch in request.form.get("pin", "") if ch.isdigit())
        if len(pin) < 6:
            flash("Kod kamida 6 raqam bo'lishi kerak", "err")
            return redirect(url_for("settings"))
        # Ikki rolda bir xil kod bo'lsa, kim kirgani aniqlanmay qoladi
        taken = roles.match_role(pin)
        if taken and taken != role:
            flash(f"Bu kod «{roles.ROLE_LABELS[taken]}» rolida ishlatilgan. "
                  f"Boshqa kod tanlang.", "err")
            return redirect(url_for("settings"))

        row = db.session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key)
            db.session.add(row)
        row.value = roles.hash_pin(pin)
        db.session.commit()
        flash(f"{roles.ROLE_LABELS[role]} kodi o'rnatildi. Kodni faqat shu "
              f"odamga bering — u boshqa bo'limlarni ko'rmaydi.", "ok")
        return redirect(url_for("settings"))

    @app.route("/settings/demo", methods=["POST"])
    def settings_demo():
        """Namunaviy shartnomalarni qo'shish yoki butunlay o'chirish."""
        import demo_data
        if request.form.get("act") == "clear":
            r = demo_data.clear_demo()
            flash(f"Namunaviy ma'lumot o'chirildi: {r['contracts']} shartnoma, "
                  f"{r['cohorts']} oqim. Haqiqiy ma'lumotga tegilmadi.", "ok")
        else:
            r = demo_data.seed_demo()
            flash(f"Namunaviy ma'lumot qo'shildi: {r['cohorts']} oqim, "
                  f"{r['contracts']} shartnoma. Kassa va ДДС o'zgarmadi — "
                  f"tugatgach shu yerdan o'chirib tashlang.", "ok")
        return redirect(url_for("settings"))

    # ── Moliya bazasini to'liq ko'chirish (oflayn nusxa <-> server) ──
    @app.route("/settings/eksport")
    def settings_export():
        """Barcha moliya jadvallari bitta faylga — serverga ko'chirish uchun."""
        import fulldump
        blob = fulldump.dump_bytes()
        name = f"mfaktor-moliya-{date.today().isoformat()}.dump.gz"
        return Response(blob, mimetype="application/gzip", headers={
            "Content-Disposition": f"attachment; filename={name}"})

    @app.route("/settings/toliq-import", methods=["POST"])
    def settings_full_import():
        """Eksport faylini yuklab, moliya bazasini butunlay almashtirish."""
        import fulldump
        f = request.files.get("dump")
        if not f or not f.filename:
            flash("Fayl tanlanmagan", "err")
            return redirect(url_for("settings"))
        report, err = fulldump.load_bytes(f.read())
        if err:
            flash(err, "err")
            return redirect(url_for("settings"))
        parts = ", ".join(f"{k}: {v}" for k, v in report.items())
        flash(f"Moliya bazasi almashtirildi — {parts}", "ok")
        return redirect(url_for("settings"))

    @app.route("/settings/import", methods=["POST"])
    def settings_import():
        """Mbm_2026.xlsx ni sayt orqali yuklab, butun zanjirni ishga tushirish."""
        import importer
        f = request.files.get("xlsx")
        if not f or not f.filename:
            flash("Fayl tanlanmagan", "err")
            return redirect(url_for("settings"))
        if not f.filename.lower().endswith((".xlsx", ".xlsm")):
            flash("Faqat .xlsx fayl qabul qilinadi", "err")
            return redirect(url_for("settings"))
        try:
            res = importer.import_workbook(f.stream)
        except Exception as e:                          # noqa: BLE001
            db.session.rollback()
            flash(f"Import xatosi: {e}", "err")
            return redirect(url_for("settings"))
        if res.get("error"):
            flash(res["error"], "err")
            return redirect(url_for("settings"))
        flash(f"Import tayyor: {res['added']} qator yuklandi "
              f"(eski {res['old']} almashtirildi), {res['openings']} hamyon "
              f"qoldig'i, kassada {res['tx']} yozuv, {res['auto']} to'lov "
              f"avtomat bog'landi, {res['queued']} navbatda"
              + (f", {res['restored']} qo'lda qilingan qaror saqlandi"
                 if res.get("restored") else "") + ".", "ok")
        return redirect(url_for("settings"))

    @app.route("/settings/wallet", methods=["POST"])
    def add_wallet():
        f = request.form
        code = f.get("code", "").strip()
        if code and not Wallet.query.filter_by(code=code).first():
            db.session.add(Wallet(code=code, name=f.get("name", code),
                                  opening=float(f.get("opening") or 0),
                                  sort=int(f.get("sort") or 0)))
            db.session.commit()
            flash("Hamyon qo'shildi", "ok")
        else:
            flash("Kod band yoki bo'sh", "error")
        return redirect(url_for("settings"))

    @app.route("/settings/recurring", methods=["POST"])
    def add_recurring():
        f = request.form
        db.session.add(RecurringPayment(
            name=f.get("name", ""), amount=float(f.get("amount") or 0),
            pay_day=int(f.get("pay_day") or 1),
            category=f.get("category", "")))
        db.session.commit()
        flash("Qo'shildi", "ok")
        return redirect(url_for("settings"))

    # O'quv bo'limi alohida yoqiladi. Railway'dagi ochiq nusxada u
    # o'chiq turadi — marshrutlari umuman ro'yxatdan o'tmaydi.
    if roles.edu_enabled():
        register_edu_routes(app)


def register_edu_routes(app):
    """O'quv bo'limi, o'quvchi ilovasi va sertifikat marshrutlari.

    Faqat OQUV_BOLIMI yoqilgan nusxada chaqiriladi (roles.edu_enabled).
    Chaqirilmasa bu manzillar serverda umuman mavjud bo'lmaydi.
    """
    # ══════════════════════════════════════════════════════════════
    #  O'QUV BO'LIMI — davomat, vazifalar, AI baholash, risk, sertifikat
    #  «O'quvchi oqimda» = Contract: moliya bilan bitta zanjir.
    # ══════════════════════════════════════════════════════════════
    @app.route("/oquv")
    def oquv():
        today = date.today()
        # Risk to'lov kechikishiga ham bog'liq — u har kuni o'zgaradi.
        # Sahifa ochilganda davom etayotgan oqimlarniki yangilanadi.
        try:
            education.refresh_all_risk(only_running=True)
        except Exception:                              # noqa: BLE001
            db.session.rollback()
        return render_template(
            "oquv.html", stats=education.edu_stats(), today=today,
            queue=education.curator_queue(today),
            rows=education.cohort_rows(today),
            risk=education.risk_students(),
            rlevel=education.risk_level,
            courses=Course.query.order_by(Course.name).all(),
            tg=notify.enabled(),
            msg=education.contact_message)

    @app.route("/oquv/cohort/<int:chid>")
    def oquv_cohort(chid):
        ch = Cohort.query.get_or_404(chid)
        contracts = (Contract.query.filter_by(cohort_id=ch.id)
                     .order_by(Contract.status.asc(),
                               Contract.risk_score.desc()).all())
        sessions = (LessonSession.query.filter_by(cohort_id=ch.id)
                    .order_by(LessonSession.date).all())
        assignments = (Assignment.query.filter_by(cohort_id=ch.id)
                       .order_by(Assignment.created_at.desc()).all())
        att = {}
        if sessions:
            for a in LessonAttendance.query.filter(
                    LessonAttendance.session_id.in_(
                        [s.id for s in sessions])).all():
                att[(a.session_id, a.contract_id)] = a.status
        sub_stats = {}
        for a in assignments:
            subs = a.submissions
            sub_stats[a.id] = (len(subs),
                               sum(1 for s in subs if s.status == "pending"))
        # har o'quvchi bo'yicha davomat va vazifa holati (bitta o'tishda)
        prog = {c.id: education.student_progress(c, sessions, att, assignments)
                for c in contracts}
        return render_template("oquv_cohort.html", ch=ch,
                               board=education.leaderboard(ch.id),
                               contracts=contracts, sessions=sessions,
                               assignments=assignments, att=att, prog=prog,
                               sub_stats=sub_stats, msg=education.contact_message,
                               att_statuses=ATT_STATUSES, today=date.today(),
                               rlevel=education.risk_level,
                               tg=notify.enabled(),
                               tglink=notify.link_url)

    @app.route("/oquv/cohort/<int:chid>/session/add", methods=["POST"])
    def oquv_session_add(chid):
        ch = Cohort.query.get_or_404(chid)
        d = _parse_date(request.form.get("date"))
        if not d:
            flash("Dars sanasi majburiy", "error")
            return redirect(url_for("oquv_cohort", chid=ch.id))
        db.session.add(LessonSession(
            cohort_id=ch.id, date=d,
            topic=(request.form.get("topic") or "").strip()[:200]))
        db.session.commit()
        flash("Dars qo'shildi", "ok")
        return redirect(url_for("oquv_cohort", chid=ch.id))

    @app.route("/oquv/cohort/<int:chid>/schedule", methods=["POST"])
    def oquv_schedule(chid):
        """Butun kurs jadvalini bir marta yaratish.

        Darslar odatda haftaning ma'lum kunlarida bo'ladi. Bittalab qo'shish
        20 ta dars uchun 20 marta forma to'ldirish demakdir — shuning uchun
        kunlar + darslar soni berilsa, tizim sanalarni o'zi chiqaradi.
        """
        ch = Cohort.query.get_or_404(chid)
        days = {int(d) for d in request.form.getlist("wd") if d.isdigit()}
        if not days:
            flash("Kamida bitta hafta kunini tanlang", "error")
            return redirect(url_for("oquv_cohort", chid=ch.id))
        try:
            count = max(1, min(int(request.form.get("count") or 12), 60))
        except ValueError:
            count = 12
        start = _parse_date(request.form.get("start"), ch.start_date)
        topic = (request.form.get("topic") or "").strip()[:180]
        exists = {s.date for s in LessonSession.query.filter_by(
            cohort_id=ch.id).all()}
        made, d, guard = 0, start, 0
        while made < count and guard < 400:
            guard += 1
            if d.weekday() in days and d not in exists:
                db.session.add(LessonSession(
                    cohort_id=ch.id, date=d,
                    topic=f"{topic} {made + 1}".strip() if topic else ""))
                exists.add(d)
                made += 1
            d += timedelta(days=1)
        db.session.commit()
        flash(f"{made} ta dars jadvalga qo'shildi", "ok")
        return redirect(url_for("oquv_cohort", chid=ch.id))

    @app.route("/oquv/refresh-risk", methods=["POST"])
    def oquv_refresh_risk():
        n = education.refresh_all_risk(only_running=False)
        flash(f"Risk qayta hisoblandi: {n} ta o'quvchi", "ok")
        return redirect(request.referrer or url_for("oquv"))

    @app.route("/oquv/session/<int:sid>/attendance", methods=["POST"])
    def oquv_attendance(sid):
        s = LessonSession.query.get_or_404(sid)
        s.held = True
        for c in Contract.query.filter_by(cohort_id=s.cohort_id,
                                          status="active").all():
            st = request.form.get(f"st_{c.id}", "")
            if st not in ATT_STATUSES:
                continue
            row = LessonAttendance.query.filter_by(
                session_id=s.id, contract_id=c.id).first()
            if row is None:
                row = LessonAttendance(session_id=s.id, contract_id=c.id)
                db.session.add(row)
            row.status = st
        db.session.commit()
        # Riskni yangilash; YANGI yuqori riskka chiqqanlar (oldin past edi)
        # avtomatika lentasiga tushadi — takror shovqin bo'lmaydi
        actives = Contract.query.filter_by(cohort_id=s.cohort_id,
                                           status="active").all()
        before = {c.id: (c.risk_score or 0) for c in actives}
        education.refresh_cohort_risk(s.cohort_id)
        for c in actives:
            if (c.risk_score >= education.RISK_HIGH
                    and before.get(c.id, 0) < education.RISK_HIGH):
                automation.log_event(
                    "risk", f"⚠️ Dropout xavfi: {c.student.name}",
                    c.risk_reasons, contract_id=c.id)
        db.session.commit()
        flash("Davomat saqlandi — risk yangilandi", "ok")
        return redirect(url_for("oquv_cohort", chid=s.cohort_id))

    @app.route("/oquv/cohort/<int:chid>/assignment/add", methods=["POST"])
    def oquv_assignment_add(chid):
        ch = Cohort.query.get_or_404(chid)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Vazifa sarlavhasi majburiy", "error")
            return redirect(url_for("oquv_cohort", chid=ch.id))
        db.session.add(Assignment(
            cohort_id=ch.id, title=title[:200],
            description=(request.form.get("description") or "")[:8000],
            material_url=(request.form.get("material_url") or "").strip()[:500],
            due_date=_parse_date(request.form.get("due_date")),
            max_score=int(request.form.get("max_score") or 100)))
        db.session.commit()
        flash("Vazifa berildi", "ok")
        return redirect(url_for("oquv_cohort", chid=ch.id))

    @app.route("/oquv/assignment/<int:aid>")
    def oquv_assignment(aid):
        a = Assignment.query.get_or_404(aid)
        subs = sorted(a.submissions,
                      key=lambda s: (s.status != "pending",
                                     -(s.submitted_at.timestamp()
                                       if s.submitted_at else 0)))
        submitted = {s.contract_id for s in subs}
        not_submitted = [c for c in Contract.query.filter_by(
            cohort_id=a.cohort_id, status="active").all()
            if c.id not in submitted]
        return render_template("oquv_assignment.html", a=a,
                               subs=subs, not_submitted=not_submitted)

    @app.route("/oquv/assignment/<int:aid>/submit", methods=["POST"])
    def oquv_submit(aid):
        """Topshiriqni qayd etish (v1: kurator kiritadi; v2: o'quvchi boti)."""
        a = Assignment.query.get_or_404(aid)
        try:
            cid = int(request.form.get("contract_id") or 0)
        except ValueError:
            cid = 0
        c = db.session.get(Contract, cid)
        if c is None or c.cohort_id != a.cohort_id:
            flash("O'quvchi tanlanmadi", "error")
            return redirect(url_for("oquv_assignment", aid=a.id))
        sub = Submission.query.filter_by(assignment_id=a.id,
                                         contract_id=c.id).first()
        if sub is None:
            sub = Submission(assignment_id=a.id, contract_id=c.id)
            db.session.add(sub)
        sub.content = (request.form.get("content") or "")[:20000]
        sub.status = "pending"
        db.session.commit()
        score, feedback = education.ai_grade(a, sub.content, a.max_score)
        if score is not None:
            sub.ai_score = score
            sub.ai_feedback = feedback
            db.session.commit()
        education.refresh_cohort_risk(a.cohort_id)
        flash("Topshiriq qabul qilindi" +
              (" · AI bahosi tayyor" if score is not None else ""), "ok")
        return redirect(url_for("oquv_assignment", aid=a.id))

    @app.route("/oquv/submission/<int:sid>/grade", methods=["POST"])
    def oquv_grade(sid):
        sub = Submission.query.get_or_404(sid)
        a = sub.assignment
        if request.form.get("use_ai") == "1" and sub.ai_score is not None:
            sub.score = sub.ai_score
            if not (request.form.get("feedback") or "").strip():
                sub.feedback = sub.ai_feedback
        else:
            try:
                score = int(request.form.get("score") or 0)
            except ValueError:
                score = 0
            sub.score = max(0, min(a.max_score or 100, score))
        fb = (request.form.get("feedback") or "").strip()
        if fb:
            sub.feedback = fb[:4000]
        sub.status = "graded"
        sub.graded_at = datetime.utcnow()
        db.session.commit()
        flash(f"Baholandi: {sub.score} ball", "ok")
        return redirect(url_for("oquv_assignment", aid=sub.assignment_id))

    @app.route("/oquv/contract/<int:cid>/certificate", methods=["POST"])
    def oquv_certificate(cid):
        c = Contract.query.get_or_404(cid)
        c.status = "completed"
        cert = EduCertificate.issue(c)
        automation.log_event(
            "cert", f"🎓 Sertifikat: {c.student.name} — {cert.serial}",
            f"{c.cohort.course.name} · {c.cohort.name}", contract_id=c.id)
        db.session.commit()
        flash(f"Sertifikat berildi: {cert.serial}", "ok")
        return redirect(url_for("oquv_cohort", chid=c.cohort_id))

    # PUBLIC: sertifikat tekshiruvi (login'siz — QR uchun)
    # ── O'quvchi kabineti (parolsiz shaxsiy havola) ──────────────
    @app.route("/oquv/contract/<int:cid>/link", methods=["POST"])
    def oquv_portal_link(cid):
        """Kurator o'quvchiga kabinet havolasini beradi."""
        c = Contract.query.get_or_404(cid)
        education.ensure_portal_token(c)
        flash(f"{c.student.name} uchun kabinet havolasi tayyor — "
              f"ro'yxatdagi «Kabinet» tugmasidan nusxa oling.", "ok")
        return redirect(request.referrer or url_for("oquv_cohort",
                                                    chid=c.cohort_id))

    @app.route("/oquv/cohort/<int:chid>/links", methods=["POST"])
    def oquv_portal_links(chid):
        """Butun oqimga bir marta havola tarqatish."""
        ch = Cohort.query.get_or_404(chid)
        n = 0
        for c in Contract.query.filter_by(cohort_id=ch.id,
                                          status="active").all():
            if not c.portal_token:
                education.ensure_portal_token(c)
                n += 1
        flash(f"{n} ta yangi kabinet havolasi yaratildi "
              f"(oldin berilganlari o'zgarmadi).", "ok")
        return redirect(url_for("oquv_cohort", chid=ch.id))


    # ── Video darsliklar (kurator tomoni) ────────────────────────
    @app.route("/oquv/kurs/<int:cid>/darsliklar")
    def oquv_content(cid):
        course = Course.query.get_or_404(cid)
        mods = (VideoModule.query.filter_by(course_id=cid)
                .order_by(VideoModule.sort, VideoModule.id).all())
        return render_template("oquv_content.html", course=course, mods=mods,
                               courses=Course.query.order_by(Course.name).all(),
                               watch=education.course_watch_summary(cid),
                               KINDS=ITEM_KINDS,
                               embed=education.embed_url)

    @app.route("/oquv/kurs/<int:cid>/modul", methods=["POST"])
    def oquv_module_add(cid):
        Course.query.get_or_404(cid)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Modul nomi majburiy", "err")
            return redirect(url_for("oquv_content", cid=cid))
        last = (db.session.query(db.func.max(VideoModule.sort))
                .filter_by(course_id=cid).scalar() or 0)
        db.session.add(VideoModule(
            course_id=cid, title=title[:200], sort=last + 1,
            subtitle=(request.form.get("subtitle") or "").strip()[:300]))
        db.session.commit()
        flash("Modul qo'shildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    @app.route("/oquv/modul/<int:mid>/dars", methods=["POST"])
    def oquv_lesson_add(mid):
        m = VideoModule.query.get_or_404(mid)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Dars nomi majburiy", "err")
            return redirect(url_for("oquv_content", cid=m.course_id))
        last = (db.session.query(db.func.max(VideoLesson.sort))
                .filter_by(module_id=mid).scalar() or 0)
        try:
            oday = max(0, int(request.form.get("open_day") or 0))
        except ValueError:
            oday = 0
        les = VideoLesson(module_id=mid, title=title[:200], sort=last + 1,
                          open_day=oday)
        db.session.add(les)
        db.session.flush()
        # Boshlang'ich mazmun — element bo'lib qo'shiladi
        url = (request.form.get("video_url") or "").strip()[:500]
        if url:
            try:
                mins = max(0, int(request.form.get("minutes") or 0))
            except ValueError:
                mins = 0
            db.session.add(LessonItem(lesson_id=les.id, kind="video", sort=1,
                                      url=url, minutes=mins))
        db.session.commit()
        flash("Dars qo'shildi — endi ichiga element qo'shing", "ok")
        return redirect(url_for("oquv_content", cid=m.course_id))

    @app.route("/oquv/dars/<int:lid>/ochirish", methods=["POST"])
    def oquv_lesson_del(lid):
        l = VideoLesson.query.get_or_404(lid)
        cid = l.module.course_id
        for it in list(l.items):
            LessonWatch.query.filter_by(item_id=it.id).delete(
                synchronize_session=False)
        LessonWatch.query.filter_by(lesson_id=l.id).delete(
            synchronize_session=False)
        for q in Quiz.query.filter_by(lesson_id=l.id).all():
            QuizAttempt.query.filter_by(quiz_id=q.id).delete(
                synchronize_session=False)
            db.session.delete(q)
        LessonView.query.filter_by(lesson_id=l.id).delete()
        db.session.delete(l)
        db.session.commit()
        flash("Dars o'chirildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    @app.route("/oquv/modul/<int:mid>/ochirish", methods=["POST"])
    def oquv_module_del(mid):
        m = VideoModule.query.get_or_404(mid)
        cid = m.course_id
        for l in list(m.lessons):
            LessonView.query.filter_by(lesson_id=l.id).delete()
        db.session.delete(m)
        db.session.commit()
        flash("Modul va uning darslari o'chirildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    @app.route("/oquv/modul/<int:mid>/tahrir", methods=["POST"])
    def oquv_module_edit(mid):
        m = VideoModule.query.get_or_404(mid)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Modul nomi bo'sh bo'lmasligi kerak", "err")
            return redirect(url_for("oquv_content", cid=m.course_id))
        m.title = title[:200]
        m.subtitle = (request.form.get("subtitle") or "").strip()[:300]
        db.session.commit()
        flash("Modul yangilandi", "ok")
        return redirect(url_for("oquv_content", cid=m.course_id))

    @app.route("/oquv/dars/<int:lid>/tahrir", methods=["POST"])
    def oquv_lesson_edit(lid):
        les = VideoLesson.query.get_or_404(lid)
        cid = les.module.course_id
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Dars nomi bo'sh bo'lmasligi kerak", "err")
            return redirect(url_for("oquv_content", cid=cid))
        tgt = request.form.get("module_id") or ""
        if tgt.isdigit() and int(tgt) != les.module_id:
            dst = db.session.get(VideoModule, int(tgt))
            if dst and dst.course_id == cid:
                les.module_id = dst.id
                les.sort = (db.session.query(db.func.max(VideoLesson.sort))
                            .filter_by(module_id=dst.id).scalar() or 0) + 1
        try:
            les.open_day = max(0, int(request.form.get("open_day") or 0))
        except ValueError:
            pass
        les.title = title[:200]
        db.session.commit()
        flash("Dars yangilandi — o'quvchilarning ko'rish tarixi saqlanib qoldi",
              "ok")
        return redirect(url_for("oquv_content", cid=cid))

    def _swap_sort(rows, obj, direction):
        """Ro'yxatdagi obyektni bir pog'ona yuqori/pastga suradi.

        Avval tartib raqamlari 1..N qilib tekislanadi (eski yozuvlarda
        hammasi 0 bo'lishi mumkin), keyin qo'shnisi bilan almashtiriladi.
        """
        rows = sorted(rows, key=lambda x: (x.sort or 0, x.id))
        for i, r in enumerate(rows, 1):
            r.sort = i
        i = next((i for i, r in enumerate(rows) if r.id == obj.id), None)
        j = i - 1 if direction == "up" else i + 1
        if i is None or j < 0 or j >= len(rows):
            return False
        rows[i].sort, rows[j].sort = rows[j].sort, rows[i].sort
        return True

    @app.route("/oquv/dars/<int:lid>/kochirish", methods=["POST"])
    def oquv_lesson_move(lid):
        les = VideoLesson.query.get_or_404(lid)
        _swap_sort(list(les.module.lessons), les,
                   request.form.get("dir", "up"))
        db.session.commit()
        return redirect(url_for("oquv_content", cid=les.module.course_id))

    @app.route("/oquv/modul/<int:mid>/kochirish", methods=["POST"])
    def oquv_module_move(mid):
        m = VideoModule.query.get_or_404(mid)
        _swap_sort(VideoModule.query.filter_by(course_id=m.course_id).all(),
                   m, request.form.get("dir", "up"))
        db.session.commit()
        return redirect(url_for("oquv_content", cid=m.course_id))

    # ── Ko'rish analitikasi ──────────────────────────────────────
    @app.route("/oquv/element/<int:iid>/analitika")
    def oquv_item_stats(iid):
        it = LessonItem.query.get_or_404(iid)
        if it.kind != "video" or it.lesson.module is None:
            abort(404)
        q = Quiz.query.filter_by(lesson_id=it.lesson_id).first()
        return render_template("oquv_lesson_stats.html", it=it, les=it.lesson,
                               st=education.lesson_watch_stats(it),
                               qs=education.quiz_stats(q) if q else None,
                               fmt=education.fmt_sec)

    # ── Dars elementlari ─────────────────────────────────────────
    def _item_form(it):
        """Shakldan kelgan qiymatlarni elementga yozadi."""
        it.title = (request.form.get("title") or "").strip()[:200]
        it.url = (request.form.get("url") or "").strip()[:500]
        it.body = (request.form.get("body") or "").strip()[:12000]
        try:
            it.minutes = max(0, int(request.form.get("minutes") or 0))
        except ValueError:
            it.minutes = 0

    @app.route("/oquv/dars/<int:lid>/element", methods=["POST"])
    def oquv_item_add(lid):
        les = VideoLesson.query.get_or_404(lid)
        kind = request.form.get("kind", "video")
        if kind not in ITEM_KINDS:
            flash("Noma'lum element turi", "err")
            return redirect(url_for("oquv_content", cid=les.module.course_id))
        last = (db.session.query(db.func.max(LessonItem.sort))
                .filter_by(lesson_id=lid).scalar() or 0)
        it = LessonItem(lesson_id=lid, kind=kind, sort=last + 1)
        _item_form(it)
        if kind in ("video", "fayl") and not it.url:
            flash("Havola kiritilmadi", "err")
            return redirect(url_for("oquv_content", cid=les.module.course_id))
        if kind == "matn" and not it.body:
            flash("Matn bo'sh", "err")
            return redirect(url_for("oquv_content", cid=les.module.course_id))
        db.session.add(it)
        db.session.flush()
        if kind == "test":
            db.session.add(Quiz(lesson_id=lid, item_id=it.id,
                                title=it.title or "Nazorat testi",
                                pass_score=70))
        db.session.commit()
        flash(f"«{ITEM_KINDS[kind]}» qo'shildi", "ok")
        return redirect(url_for("oquv_content", cid=les.module.course_id))

    @app.route("/oquv/element/<int:iid>/tahrir", methods=["POST"])
    def oquv_item_edit(iid):
        it = LessonItem.query.get_or_404(iid)
        cid = it.lesson.module.course_id
        _item_form(it)
        q = Quiz.query.filter_by(item_id=it.id).first()
        if q is not None and it.title:
            q.title = it.title
        db.session.commit()
        flash("Element yangilandi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    @app.route("/oquv/element/<int:iid>/kochirish", methods=["POST"])
    def oquv_item_move(iid):
        it = LessonItem.query.get_or_404(iid)
        _swap_sort(list(it.lesson.items), it, request.form.get("dir", "up"))
        db.session.commit()
        return redirect(url_for("oquv_content", cid=it.lesson.module.course_id))

    @app.route("/oquv/element/<int:iid>/ochirish", methods=["POST"])
    def oquv_item_del(iid):
        it = LessonItem.query.get_or_404(iid)
        cid = it.lesson.module.course_id
        LessonWatch.query.filter_by(item_id=it.id).delete(
            synchronize_session=False)
        for q in Quiz.query.filter_by(item_id=it.id).all():
            QuizAttempt.query.filter_by(quiz_id=q.id).delete(
                synchronize_session=False)
            db.session.delete(q)
        db.session.delete(it)
        db.session.commit()
        flash("Element o'chirildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    # ── Testlar (kurator tomoni) ─────────────────────────────────
    @app.route("/oquv/test/<int:qid>/sozlama", methods=["POST"])
    def oquv_quiz_save(qid):
        q = Quiz.query.get_or_404(qid)
        q.title = (request.form.get("title") or "Nazorat testi").strip()[:200]
        try:
            q.pass_score = max(0, min(100, int(request.form.get("pass") or 70)))
        except ValueError:
            q.pass_score = 70
        if q.item is not None:
            q.item.title = q.title
        db.session.commit()
        flash("Test sozlamasi saqlandi", "ok")
        return redirect(url_for("oquv_content",
                                cid=q.lesson.module.course_id))

    @app.route("/oquv/test/<int:qid>/savol", methods=["POST"])
    def oquv_quiz_question_add(qid):
        q = Quiz.query.get_or_404(qid)
        text = (request.form.get("text") or "").strip()
        opts = [(request.form.get(f"opt{i}") or "").strip() for i in range(1, 5)]
        opts = [o for o in opts if o]
        try:
            right = int(request.form.get("right") or 1)
        except ValueError:
            right = 1
        if not text or len(opts) < 2:
            flash("Savol matni va kamida 2 ta variant kerak", "err")
            return redirect(url_for("oquv_content", cid=q.lesson.module.course_id))
        last = (db.session.query(db.func.max(QuizQuestion.sort))
                .filter_by(quiz_id=q.id).scalar() or 0)
        qq = QuizQuestion(quiz_id=q.id, text=text[:500], sort=last + 1)
        db.session.add(qq)
        db.session.flush()
        for i, o in enumerate(opts, 1):
            db.session.add(QuizOption(question_id=qq.id, text=o[:300],
                                      is_correct=(i == right)))
        db.session.commit()
        flash("Savol qo'shildi", "ok")
        return redirect(url_for("oquv_content", cid=q.lesson.module.course_id))

    @app.route("/oquv/savol/<int:qqid>/ochirish", methods=["POST"])
    def oquv_quiz_question_del(qqid):
        qq = QuizQuestion.query.get_or_404(qqid)
        cid = qq.quiz.lesson.module.course_id
        db.session.delete(qq)
        db.session.commit()
        flash("Savol o'chirildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    @app.route("/oquv/test/<int:qid>/ochirish", methods=["POST"])
    def oquv_quiz_del(qid):
        q = Quiz.query.get_or_404(qid)
        cid = q.lesson.module.course_id
        QuizAttempt.query.filter_by(quiz_id=q.id).delete(
            synchronize_session=False)
        db.session.delete(q)
        db.session.commit()
        flash("Test va uning natijalari o'chirildi", "ok")
        return redirect(url_for("oquv_content", cid=cid))

    # ── Telegram xabarnoma ───────────────────────────────────────
    @app.route("/oquv/xabarnoma")
    def oquv_notify():
        items = notify.pending() if notify.enabled() else []
        from models import TgMessage
        return render_template(
            "oquv_notify.html", items=items, on=notify.enabled(),
            bot=notify.bot_username(), KINDS=notify.KINDS,
            hook=url_for("tg_webhook", secret=_tg_secret(), _external=True),
            log=(TgMessage.query.order_by(TgMessage.sent_at.desc())
                 .limit(30).all()))

    @app.route("/oquv/xabarnoma/bot", methods=["POST"])
    def oquv_notify_bot():
        notify.set_bot(request.form.get("token", ""),
                       request.form.get("username", ""))
        if notify.bot_token():
            ok, res = notify.check_bot()
            flash(f"Bot ulandi: @{res}" if ok else f"Bot javob bermadi: {res}",
                  "ok" if ok else "err")
        else:
            flash("Bot tokeni tozalandi — xabarnoma o'chdi", "ok")
        return redirect(url_for("oquv_notify"))

    @app.route("/oquv/xabarnoma/yuborish", methods=["POST"])
    def oquv_notify_send():
        if not notify.enabled():
            flash("Avval bot tokenini kiriting", "err")
            return redirect(url_for("oquv_notify"))
        want = request.form.getlist("key")
        items = [i for i in notify.pending() if i["key"] in set(want)]
        sent, skipped, failed = notify.send_pending(items)
        flash(f"Yuborildi: {sent} ta"
              + (f" · o'tkazildi (takror): {skipped}" if skipped else "")
              + (f" · yetmadi: {failed}" if failed else ""),
              "err" if failed and not sent else "ok")
        return redirect(url_for("oquv_notify"))

    @app.route("/oquv/contract/<int:cid>/tg", methods=["POST"])
    def oquv_tg_link(cid):
        c = Contract.query.get_or_404(cid)
        c.tg_chat_id = "".join(ch for ch in request.form.get("chat_id", "")
                               if ch.isdigit() or ch == "-")[:32]
        db.session.commit()
        flash("Telegram bog'lanishi yangilandi", "ok")
        return redirect(url_for("oquv_cohort", chid=c.cohort_id))

    @app.route("/tg/webhook/<secret>", methods=["POST"])
    def tg_webhook(secret):
        """Telegram shu manzilga xabar tashlaydi — o'quvchini bog'laymiz."""
        if not hmac.compare_digest(secret, _tg_secret()):
            return {"ok": False}, 404
        try:
            notify.handle_update(request.get_json(silent=True) or {})
        except Exception:                              # noqa: BLE001
            db.session.rollback()
        return {"ok": True}

    # ── O'quvchi ilovasi (alohida PWA, /app/<kalit>) ─────────────
    def _student(token, cid=None):
        """Kalit bo'yicha shartnomani topadi.

        Kalit endi O'QUVCHIDA turadi — u bir nechta kursga yozilsa ham
        bitta havola bilan hammasini ko'radi. Eski, shartnomaga berilgan
        havolalar ham ishlashda davom etadi.
        """
        st = Student.query.filter_by(portal_token=token).first()
        if st is not None:
            cs = _my_courses(st)
            if not cs:
                return None
            if cid:
                m = next((c for c in cs if c.id == cid), None)
                if m is not None:
                    return m
            return cs[0]
        return Contract.query.filter_by(portal_token=token).first()

    def _my_courses(student):
        """O'quvchining kurslari — faol birinchi, keyin eskilari."""
        rows = list(student.contracts)
        rows.sort(key=lambda c: (c.status != "active",
                                 -(c.cohort.start_date.toordinal()
                                   if c.cohort and c.cohort.start_date else 0)))
        return rows

    def _picked(token):
        """Manzildagi ?k= bo'yicha tanlangan kurs."""
        try:
            return int(request.args.get("k") or 0) or None
        except ValueError:
            return None

    def _link(token, path="", c=None):
        """Ichki havola — tanlangan kursni saqlab qoladi."""
        base = f"/app/{token}{path}"
        k = _picked(token)
        return f"{base}?k={k}" if k else base

    app.jinja_env.globals["applink"] = _link

    def _ctx(token):
        """(shartnoma, kurslar ro'yxati) — har sahifada kerak."""
        c = _student(token, _picked(token))
        if c is None:
            return None, []
        st = Student.query.filter_by(portal_token=token).first()
        return c, (_my_courses(st) if st else [c])

    @app.route("/kabinet/<token>")
    def kabinet(token):
        return redirect(url_for("app_home", token=token))

    @app.route("/app/<token>")
    def app_home(token):
        c, courses = _ctx(token)
        if not c:
            return render_template("app_base.html", d=None), 404
        return render_template("app_home.html", tab="home", token=token,
                               d=education.portal_data(c), courses=courses,
                               cur=c, cc=education.course_content(c))

    @app.route("/app/<token>/darslar")
    def app_lessons(token):
        c, courses = _ctx(token)
        if not c:
            return render_template("app_base.html", d=None), 404
        return render_template("app_lessons.html", tab="lessons", token=token,
                               d=education.portal_data(c), courses=courses,
                               cur=c, cc=education.course_content(c))

    @app.route("/app/<token>/dars/<int:lid>")
    def app_lesson(token, lid):
        c, courses = _ctx(token)
        les = db.session.get(VideoLesson, lid)
        if not c or not les or les.module is None:
            return render_template("app_base.html", d=None), 404
        if les.module.course_id != c.cohort.course_id:
            return redirect(_link(token, "/darslar"))
        lock, odate = education.lesson_locked(les, c.cohort)
        if lock:
            flash(f"Bu dars {odate.strftime('%d.%m.%Y')} dan ochiladi.", "err")
            return redirect(_link(token, "/darslar"))

        cc = education.course_content(c)
        flat = [r["l"] for g in cc["modules"] for r in g["lessons"]
                if not r["locked"]]
        idx = next((i for i, x in enumerate(flat) if x.id == les.id), 0)
        return render_template(
            "app_lesson.html", tab="lessons", token=token, les=les,
            d=education.portal_data(c), cc=cc, courses=courses, cur=c,
            st=education.lesson_state(c, les), embed=education.embed_url,
            done=les.id in cc["seen"], fmt=education.fmt_sec,
            prev=flat[idx - 1] if idx > 0 else None,
            nxt=flat[idx + 1] if idx + 1 < len(flat) else None)

    @app.route("/app/<token>/element/<int:iid>/vaqt", methods=["POST"])
    def app_item_beat(token, iid):
        """Ilova har 15 soniyada ko'rilgan oraliqlarni shu yerga yuboradi."""
        c = _student(token, _picked(token))
        it = db.session.get(LessonItem, iid)
        if (not c or it is None or it.kind != "video"
                or it.lesson.module is None
                or it.lesson.module.course_id != c.cohort.course_id):
            return {"ok": False}, 404
        if education.lesson_locked(it.lesson, c.cohort)[0]:
            return {"ok": False, "locked": True}, 403
        data = request.get_json(silent=True) or {}
        spans = data.get("spans") or []
        if not isinstance(spans, list):
            spans = []
        row = education.record_watch(
            c, it, spans[:200], data.get("duration") or 0,
            data.get("pos") or 0, bool(data.get("opened")))
        return {"ok": True, "pct": row.pct}

    @app.route("/app/<token>/test/<int:qid>", methods=["POST"])
    def app_quiz_submit(token, qid):
        c = _student(token, _picked(token))
        q = db.session.get(Quiz, qid)
        if not c or q is None or q.lesson is None or q.lesson.module is None:
            return redirect(_link(token, "/darslar"))
        if q.lesson.module.course_id != c.cohort.course_id:
            return redirect(_link(token, "/darslar"))
        if education.lesson_locked(q.lesson, c.cohort)[0] or not q.questions:
            return redirect(_link(token, "/darslar"))
        chosen = {k[1:]: v for k, v in request.form.items()
                  if k.startswith("q") and k[1:].isdigit()}
        att = education.grade_quiz(q, c, chosen)
        if att is None:
            return redirect(_link(token, f"/dars/{q.lesson_id}"))
        if att.passed:
            flash(f"Test topshirildi — {att.score} ball. Tabriklaymiz!", "ok")
            education.sync_lesson_done(c, q.lesson)
        else:
            flash(f"Natija: {att.score} ball. O'tish uchun "
                  f"{q.pass_score} kerak — qayta urinib ko'ring.", "err")
        return redirect(_link(token, f"/dars/{q.lesson_id}") + "#t" + str(qid))

    @app.route("/app/<token>/dars/<int:lid>/belgilash", methods=["POST"])
    def app_lesson_done(token, lid):
        c = _student(token, _picked(token))
        les = db.session.get(VideoLesson, lid)
        if (not c or not les or les.module is None
                or les.module.course_id != c.cohort.course_id):
            return redirect(_link(token, "/darslar"))
        education.mark_view(c, les, request.form.get("undo") != "1")
        nxt = request.form.get("next")
        if nxt and nxt.isdigit():
            return redirect(_link(token, f"/dars/{int(nxt)}"))
        return redirect(_link(token, f"/dars/{lid}"))

    @app.route("/app/<token>/vazifalar")
    def app_tasks(token):
        c, courses = _ctx(token)
        if not c:
            return render_template("app_base.html", d=None), 404
        return render_template("app_tasks.html", tab="tasks", token=token,
                               d=education.portal_data(c), courses=courses,
                               cur=c)

    @app.route("/app/<token>/reyting")
    def app_rank(token):
        c, courses = _ctx(token)
        if not c:
            return render_template("app_base.html", d=None), 404
        return render_template("app_rank.html", tab="rank", token=token,
                               d=education.portal_data(c), courses=courses,
                               cur=c, me=c.id,
                               board=education.leaderboard(c.cohort_id))

    @app.route("/app/<token>/manifest.webmanifest")
    def app_manifest(token):
        """Har o'quvchiga o'z manifesti — ilova o'z kalitidan ochiladi."""
        return Response(json.dumps({
            "name": "Mfaktor O'quvchi", "short_name": "Mfaktor",
            "start_url": f"/app/{token}", "scope": f"/app/{token}",
            "display": "standalone", "background_color": "#faf7f0",
            "theme_color": "#14161f", "lang": "uz",
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192",
                 "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512",
                 "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-maskable-512.png",
                 "sizes": "512x512",
                 "type": "image/png", "purpose": "maskable"},
            ],
        }, ensure_ascii=False), mimetype="application/manifest+json")

    @app.route("/kabinet/<token>/topshirish/<int:aid>", methods=["POST"])
    def kabinet_submit(token, aid):
        """O'quvchi vazifasini o'zi topshiradi — AI birinchi bahoni beradi."""
        c = Contract.query.filter_by(portal_token=token).first()
        a = db.session.get(Assignment, aid)
        if not c or not a or a.cohort_id != c.cohort_id:
            return redirect(url_for("kabinet", token=token))
        text = (request.form.get("content") or "").strip()
        if not text:
            flash("Javob bo'sh — matn yozing", "err")
            return redirect(url_for("kabinet", token=token) + f"#v{aid}")
        sub = Submission.query.filter_by(assignment_id=a.id,
                                         contract_id=c.id).first()
        if sub and sub.status == "graded":
            flash("Bu vazifa allaqachon baholangan — o'zgartirib bo'lmaydi.",
                  "err")
            return redirect(url_for("kabinet", token=token) + f"#v{aid}")
        if sub is None:
            sub = Submission(assignment_id=a.id, contract_id=c.id)
            db.session.add(sub)
        sub.content = text[:8000]
        sub.submitted_at = datetime.utcnow()
        sub.status = "pending"
        # AI birinchi qatlam bahosi (kalit bo'lmasa — jim o'tadi)
        score, fb = education.ai_grade(a, sub.content, a.max_score or 100)
        if score is not None:
            sub.ai_score, sub.ai_feedback = score, fb
        db.session.commit()
        # topshirgani riskni pasaytiradi — darhol qayta hisoblaymiz
        try:
            education.refresh_cohort_risk(c.cohort_id)
        except Exception:                              # noqa: BLE001
            db.session.rollback()
        flash("Javobingiz qabul qilindi. Kurator tekshirib, bahoni qo'yadi.",
              "ok")
        return redirect(url_for("kabinet", token=token) + f"#v{aid}")

    @app.route("/cert/<token>")
    def cert_verify(token):
        cert = EduCertificate.query.filter_by(token=token).first()
        if not cert:
            return render_template("cert_verify.html", cert=None), 404
        return render_template("cert_verify.html", cert=cert,
                               c=cert.contract)


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5060)), debug=True)
