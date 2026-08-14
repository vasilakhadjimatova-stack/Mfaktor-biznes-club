"""db obyekti — Impulse andozasi: SQLite lokalda, PostgreSQL bulutda."""
import logging
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
    ("dds_rows", "skip_note", "VARCHAR(200) DEFAULT ''"),
    # O'quv bo'limi: dropout risk-skoring
    ("contracts", "risk_score", "INTEGER DEFAULT 0"),
    ("contracts", "risk_reasons", "VARCHAR(300) DEFAULT ''"),
    # O'quvchi kabineti va dars materiallari
    ("contracts", "portal_token", "VARCHAR(48)"),
    ("assignments", "material_url", "VARCHAR(500) DEFAULT ''"),
    # Bosqichma-bosqich ochilish va Telegram bog'lanishi
    ("video_lessons", "open_day", "INTEGER DEFAULT 0"),
    ("contracts", "tg_chat_id", "VARCHAR(32) DEFAULT ''"),
    # Dars elementlari: test va ko'rish hisobi endi elementga bog'lanadi
    ("quizzes", "item_id", "INTEGER"),
    ("lesson_watch", "item_id", "INTEGER"),
    # Ilova kaliti endi o'quvchida — bitta hisob, ko'p kurs
    ("students", "portal_token", "VARCHAR(48)"),
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
        # Dars mazmuni elementlarga ko'chadi (bir marta, xavfsiz)
        try:
            import education
            education.fix_watch_unique()
            education.migrate_lesson_items()
        except Exception as exc:                       # noqa: BLE001
            db.session.rollback()
            logging.getLogger(__name__).error(
                f"O'quv bo'limi ko'chirishida xato: {exc}")
