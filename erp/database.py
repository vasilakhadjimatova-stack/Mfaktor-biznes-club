"""Mfaktor ERP — markaziy ma'lumotlar bazasi."""
import logging

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
logger = logging.getLogger(__name__)


def init_db(app):
    """Bazani ulash va jadvallarni yaratish."""
    db.init_app(app)
    with app.app_context():
        from models import user, education  # noqa: F401 — jadvallar uchun
        db.create_all()
