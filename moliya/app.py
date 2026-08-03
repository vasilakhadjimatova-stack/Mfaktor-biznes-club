"""
Mfaktor Moliya — ta'lim biznesi uchun moliya dasturi.

Ishga tushirish:
    pip install -r requirements.txt
    python seed.py      # birinchi marta — demo ma'lumot
    python app.py       # http://localhost:5060
"""
import os
from datetime import date, datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for

import automation
import core
import planner
from database import db, init_db
from models import (Budget, Cohort, Contract, Course, EXPENSE_CATS,
                    INCOME_CATS, InstallmentLine, MARKETING_CHANNELS,
                    RecurringPayment, Student, Transaction, Wallet,
                    CONTRACT_STATUSES, income_cat_for_course)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "mfaktor-moliya-dev")
    init_db(app)

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

    @app.context_processor
    def ctx():
        try:
            _, total_cash = core.wallet_balances()
        except Exception:
            total_cash = None
        return {"INCOME_CATS": INCOME_CATS, "EXPENSE_CATS": EXPENSE_CATS,
                "CHANNELS": MARKETING_CHANNELS, "STATUSES": CONTRACT_STATUSES,
                "today": date.today(), "total_cash": total_cash}

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
        return render_template("dashboard.html", d=core.dashboard_data())

    # ── Tranzaksiyalar ───────────────────────────────────────────
    @app.route("/transactions")
    def transactions():
        y, m = _ym()
        q = (Transaction.query
             .filter(db.func.extract("year", Transaction.tdate) == y)
             .filter(db.func.extract("month", Transaction.tdate) == m)
             .order_by(Transaction.tdate.desc(), Transaction.id.desc()))
        wallets = Wallet.query.filter_by(is_active=True).order_by(Wallet.sort).all()
        return render_template("transactions.html", txs=q.all(), y=y, m=m,
                               wallets=wallets,
                               cf=core.month_cashflow(y, m))

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
        # ── ZANJIR: oqim ochildi -> launch tahlili avtomatik ──
        automation.log_event(
            "contract", f"Yangi oqim ochildi: {ch.course.name} — {ch.name}",
            "Oqim yaratildi → launch-tahlil (marja/BEP) tayyorlandi → "
            "kalkulyatorga yo'naltirildi")
        db.session.commit()
        flash("Oqim ochildi — marja va zararsizlik tahlili tayyor", "ok")
        return redirect(url_for(
            "launch_planner", course_id=ch.course_id,
            price=int(ch.course.base_price or 0) or "",
            capacity=ch.capacity,
            duration=(ch.end_date - ch.start_date).days))

    # ── Launch-kalkulyator: yangi kurs marja/BEP tahlili ────────
    @app.route("/planner")
    def launch_planner():
        courses = Course.query.filter_by(is_active=True).all()
        f = request.args
        result = None
        sel = {"course_id": f.get("course_id", ""),
               "price": f.get("price", ""),
               "capacity": f.get("capacity", "30"),
               "duration": f.get("duration", "60"),
               "cac": f.get("cac", "")}
        if f.get("price"):
            course = db.session.get(Course, int(f.get("course_id") or 0))
            cname = course.name if course else f.get("new_name", "Yangi kurs")
            try:
                result = planner.launch_plan(
                    cname,
                    price=float(f.get("price")),
                    capacity=int(f.get("capacity") or 30),
                    duration_days=int(f.get("duration") or 60),
                    cac=float(f["cac"]) if f.get("cac") else None)
                result["course_name"] = cname
            except (ValueError, ZeroDivisionError):
                flash("Kiritilgan qiymatlarni tekshiring", "error")
        return render_template("planner.html", courses=courses,
                               sel=sel, r=result)

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
        return render_template("dds.html", d=core.dds_matrix(year))

    # ── Hisobotlar ───────────────────────────────────────────────
    @app.route("/reports")
    def reports():
        y, m = _ym()
        return render_template("reports.html", y=y, m=m,
                               cf=core.month_cashflow(y, m),
                               acc=core.accrual_summary(),
                               ue=core.unit_economics(y, m),
                               bep=core.break_even(y, m),
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
    @app.route("/settings")
    def settings():
        return render_template(
            "settings.html",
            wallets=Wallet.query.order_by(Wallet.sort).all(),
            recurring=RecurringPayment.query.order_by(
                RecurringPayment.pay_day).all())

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
