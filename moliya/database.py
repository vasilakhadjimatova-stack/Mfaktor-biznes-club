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


# Keyin qo'shilgan ustunlar: create_all() mavjud jadvalga ustun qo'shmaydi,
# shuning uchun yetishmayotganini o'zimiz qo'shamiz.
NEW_COLUMNS = [
    ("transactions", "dds_row_id", "INTEGER"),
    ("dds_rows", "match_status", "VARCHAR(12) DEFAULT 'none'"),
    ("dds_rows", "contract_id", "INTEGER"),
    ("dds_rows", "match_score", "FLOAT DEFAULT 0"),
    # NULL = eski qator (qancha yozilgani noma'lum) — 0 dan farqlanishi shart
    ("dds_rows", "applied_amount", "FLOAT"),
    # O'quv bo'limi: dropout risk-skoring
    ("contracts", "risk_score", "INTEGER DEFAULT 0"),
    ("contracts", "risk_reasons", "VARCHAR(300) DEFAULT ''"),
    # O'quvchi kabineti va dars materiallari
    ("contracts", "portal_token", "VARCHAR(48)"),
    ("assignments", "material_url", "VARCHAR(500) DEFAULT ''"),
]


def ensure_columns(app):
    """Yetishmayotgan ustunlarni qo'shadi (yengil migratsiya)."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    added = []
    for table, col, ddl in NEW_COLUMNS:
        if table not in tables:
            continue
        if col in {c["name"] for c in insp.get_columns(table)}:
            continue
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        added.append(f"{table}.{col}")
    if added:
        app.logger.info("Yangi ustunlar qo'shildi: %s", ", ".join(added))
    return added


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        ensure_columns(app)
