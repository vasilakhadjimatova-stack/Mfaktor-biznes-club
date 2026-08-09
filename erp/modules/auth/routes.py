"""Kirish/chiqish — 6 xonali kod."""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash)

from core.auth import login_by_code, logout, current_user

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("education.index"))
    if request.method == "POST":
        u = login_by_code(request.form.get("code"))
        if u:
            return redirect(url_for("education.index"))
        flash("Kod noto'g'ri", "error")
    return render_template("login.html")


@bp.route("/logout")
def do_logout():
    logout()
    return redirect(url_for("auth.login"))


@bp.route("/no-access")
def no_access():
    return render_template("no_access.html")
