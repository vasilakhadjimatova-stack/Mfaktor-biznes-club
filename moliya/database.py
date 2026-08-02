"""db obyekti — Impulse andozasi: SQLite lokalda, PostgreSQL bulutda."""
import os

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def db_uri():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Railway/Heroku eski formati
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    base = os.path.dirname(os.path.abspath(__file__))
    return "sqlite:///" + os.path.join(base, "mfaktor_moliya.db")


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
