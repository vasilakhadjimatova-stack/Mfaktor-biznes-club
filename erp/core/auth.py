"""
Kirish — 6 xonali kod bilan (parolsiz, xodimlar uchun qulay).
"""
from functools import wraps

from flask import session, redirect, url_for

from models.user import User


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    u = User.query.get(uid)
    if u is None or not u.is_active:
        session.pop("user_id", None)
        return None
    return u


def login_by_code(code):
    code = (code or "").strip()
    if not code:
        return None
    u = User.query.filter_by(code=code, is_active=True).first()
    if u:
        session["user_id"] = u.id
        session.permanent = True
    return u


def logout():
    session.pop("user_id", None)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper
