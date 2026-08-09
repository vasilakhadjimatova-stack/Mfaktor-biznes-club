"""
Pytest poydevori — Mfaktor ERP.

Izolyatsiya: vaqtinchalik SQLite baza (app importidan OLDIN DATABASE_URL
o'rnatiladi). AI tokensiz no-op.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_TMPDIR = tempfile.mkdtemp(prefix="mfaktor_test_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    _TMPDIR, "test.db").replace("\\", "/")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.setdefault("SECRET_KEY", "pytest-only-secret-0123456789abcdef")

import pytest  # noqa: E402

from app import app as _flask_app  # noqa: E402
from database import db  # noqa: E402

CSRF = "testtoken"


@pytest.fixture(scope="session")
def app():
    _flask_app.config.update(TESTING=True)
    return _flask_app


def _mk_user(name, code, perm=None, **kw):
    from models.user import User
    u = User.query.filter_by(code=code).first()
    if u:
        return u
    u = User(name=name, code=code, **kw)
    if perm is not None:
        u.perm = perm
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture(scope="session")
def user_ids(app):
    with app.app_context():
        admin = _mk_user("Test Direktor", "900001", position="Direktor",
                         department="Boshqaruv", is_admin=True)
        edu = _mk_user("Test O'quv rahbari", "900002",
                       position="O'quv bo'limi rahbari",
                       department="O'quv bo'limi", perm=["education"])
        regular = _mk_user("Test Xodim", "900003", position="Xodim",
                           department="Marketing", perm=[])
        return {"admin": admin.id, "edu": edu.id, "regular": regular.id}


def _login(client, uid):
    with client.session_transaction() as s:
        s["user_id"] = uid
        s["_csrf_token"] = CSRF


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app, user_ids):
    c = app.test_client()
    _login(c, user_ids["admin"])
    return c


@pytest.fixture
def edu_client(app, user_ids):
    c = app.test_client()
    _login(c, user_ids["edu"])
    return c


@pytest.fixture
def regular_client(app, user_ids):
    c = app.test_client()
    _login(c, user_ids["regular"])
    return c


@pytest.fixture
def post():
    def _post(client, url, follow=False, **data):
        data.setdefault("_csrf", CSRF)
        return client.post(url, data=data, follow_redirects=follow)
    return _post
