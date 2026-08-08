"""
Mfaktor Moliya — ta'lim biznesi uchun moliya dasturi.

Ishga tushirish:
    pip install -r requirements.txt
    python seed.py      # birinchi marta — demo ma'lumot
    python app.py       # http://localhost:5060
"""
import hmac
import os
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from flask import (Flask, Response, flash, redirect, render_template,
                   request, session, url_for)

import analytics
import automation
import core
import ddsflow
import kpi
import matching
import planner
import praytimes
from database import db, init_db
from models import (Budget, Cohort, Contract, Course, DdsRow, DDS_LOOKUP,
                    DDS_SPRAVOCHNIK, DDS_WALLET2, DDS_WALLETS, EXPENSE_CATS, KpiCard,
                    INCOME_CATS, InstallmentLine, MARKETING_CHANNELS,
                    RecurringPayment, Student, Transaction, Wallet,
                    CONTRACT_STATUSES, income_cat_for_course)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "mfaktor-moliya-dev")
    app.permanent_session_lifetime = timedelta(days=30)
    init_db(app)

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
    APP_PIN = os.environ.get("APP_PIN", "").strip()
    _pin_fails = {}                    # ip -> (soni, oxirgi urinish vaqti)
    _PUBLIC = ("/login", "/static/", "/manifest.json", "/sw.js",
               "/offline.html", "/healthz")

    @app.before_request
    def _guard():
        if not APP_PIN:
            return None
        p = request.path
        if any(p == x or p.startswith(x) for x in _PUBLIC):
            return None
        if session.get("auth"):
            return None
        return redirect(url_for("login", next=request.path))

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not APP_PIN or session.get("auth"):
            return redirect("/")
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
                if hmac.compare_digest(pin, APP_PIN):
                    _pin_fails.pop(ip, None)
                    session.permanent = True
                    session["auth"] = True
                    nxt = request.args.get("next", "/")
                    return redirect(nxt if nxt.startswith("/") else "/")
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
        try:
            _, total_cash = core.wallet_balances()
        except Exception:
            total_cash = None
        try:
            inbox_open = matching.open_count()
        except Exception:
            inbox_open = 0
        return {"INCOME_CATS": INCOME_CATS, "EXPENSE_CATS": EXPENSE_CATS,
                "CHANNELS": MARKETING_CHANNELS, "STATUSES": CONTRACT_STATUSES,
                "today": date.today(), "total_cash": total_cash,
                "inbox_open": inbox_open}

    register_routes(app)
    return app


def _parse_date(s, default=None):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return default or date.today()


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
        q = Contract.query
        if status != "all":
            q = q.filter_by(status=status)
        rows = q.order_by(Contract.signed_date.desc()).all()
        return render_template("contracts.html", rows=rows, status=status,
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
        # summa yoki ism o'zgargan bo'lsa — eski bog'lanish endi to'g'ri emas
        matching.unapply(row)
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
        items = matching.inbox(show=show)
        return render_template("inbox.html", items=items, show=show,
                               st=matching.stats(),
                               cohorts=Cohort.query.order_by(
                                   Cohort.start_date.desc()).all())

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
            db.session.commit()
            flash("Navbatdan olib tashlandi", "ok")
        return redirect(request.referrer or url_for("payments_inbox"))

    @app.route("/inbox/<int:rid>/restore", methods=["POST"])
    def inbox_restore(rid):
        row = db.session.get(DdsRow, rid)
        if row:
            row.match_status = "none"
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
        return render_template(
            "settings.html",
            wallets=Wallet.query.order_by(Wallet.sort).all(),
            recurring=RecurringPayment.query.order_by(
                RecurringPayment.pay_day).all())

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
              f"avtomat bog'landi, {res['queued']} navbatda.", "ok")
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


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5060)), debug=True)
