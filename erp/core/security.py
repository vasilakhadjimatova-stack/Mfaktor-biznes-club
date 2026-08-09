"""
Xavfsizlik: CSRF himoyasi + asosiy security headerlar.

CSRF: sessiyada token, har POST formada `_csrf` maydoni shu token bilan
kelishi shart. Shablonlarda {{ csrf_token() }} mavjud; base.html'dagi JS
har POST formaga tokenni avtomatik qo'shadi (zaxira qatlam).
"""
import secrets

from flask import session, request, abort

_CSRF_SESSION_KEY = "_csrf_token"
_CSRF_FORM_FIELD = "_csrf"
_EXEMPT_PATHS = set()


def csrf_token():
    tok = session.get(_CSRF_SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = tok
    return tok


def csrf_exempt(path):
    _EXEMPT_PATHS.add(path)


def init_security(app):
    @app.before_request
    def _csrf_check():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if request.path in _EXEMPT_PATHS:
            return
        sent = request.form.get(_CSRF_FORM_FIELD) or \
            request.headers.get("X-CSRF-Token", "")
        good = session.get(_CSRF_SESSION_KEY)
        if not good or not secrets.compare_digest(str(sent), str(good)):
            abort(403)

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": csrf_token}

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp
