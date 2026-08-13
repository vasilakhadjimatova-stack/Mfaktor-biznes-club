"""Moliya ma'lumotlarini to'liq eksport/import qilish.

Nima uchun kerak: lokal (oflayn) nusxada to'g'irlangan ma'lumotni serverga
ko'chirish. Git orqali yuborib bo'lmaydi — repo ochiq, ichida haqiqiy
summalar va ismlar bor. Shuning uchun ma'lumot faylga eksport qilinadi va
serverda /settings sahifasidan yuklanadi (faqat direktor).

Qamrov — FAQAT moliya jadvallari: hamyonlar, ДДС, kassa, kurs/oqim,
o'quvchi, shartnoma, grafik. O'quv bo'limi jadvallari ataylab kirmaydi.

Import ESKISINI O'CHIRIB, faylni yozadi — qo'shib emas. Server bazasida
turgan eski (to'g'irlanmagan) nusxa aynan shuni talab qiladi.
"""
import gzip
import json
from datetime import date, datetime

from database import db
from models import (Cohort, Contract, Course, DdsRow, InstallmentLine,
                    Student, Transaction, Wallet)

FORMAT = "mfaktor-moliya-dump"
VERSION = 2

# Tartib muhim: bog'lanishlar tufayli import shu tartibda, o'chirish
# teskarisida bajariladi.
TABLES = [Wallet, Course, Cohort, Student, Contract, InstallmentLine,
          DdsRow, Transaction]


def _val(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _cols(model):
    return [c.name for c in model.__table__.columns]


def dump_all():
    """Barcha moliya jadvallarini bitta lug'atga yig'adi."""
    out = {"format": FORMAT, "version": VERSION,
           "created": datetime.now().isoformat(timespec="seconds"),
           "tables": {}}
    for m in TABLES:
        cols = _cols(m)
        rows = [{c: _val(getattr(r, c)) for c in cols} for r in m.query.all()]
        out["tables"][m.__tablename__] = rows
    return out


def dump_bytes():
    return gzip.compress(
        json.dumps(dump_all(), ensure_ascii=False).encode("utf-8"))


def _parse(model, row):
    typed = {}
    for c in model.__table__.columns:
        v = row.get(c.name)
        if v is not None and isinstance(c.type, db.Date().__class__):
            v = date.fromisoformat(v[:10])
        elif v is not None and isinstance(c.type, db.DateTime().__class__):
            v = datetime.fromisoformat(v)
        typed[c.name] = v
    return typed


def load_bytes(blob):
    """Eksport faylini o'qib, bazani almashtiradi.

    Qaytaradi: (hisobot_lug'ati, xato_matni)
    """
    try:
        data = json.loads(gzip.decompress(blob).decode("utf-8"))
    except (OSError, ValueError):
        try:
            data = json.loads(blob.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "Fayl o'qilmadi — bu eksport fayli emas"
    if data.get("format") != FORMAT:
        return None, "Bu moliya eksport fayli emas"
    if data.get("version", 0) > VERSION:
        return None, "Fayl yangiroq dastur bilan yaratilgan — avval deploy qiling"

    tables = data.get("tables", {})
    report = {}
    try:
        # eski yozuvlar teskari tartibda o'chiriladi (bog'lanishlar uchun)
        for m in reversed(TABLES):
            m.query.delete(synchronize_session=False)
        db.session.flush()
        for m in TABLES:
            rows = tables.get(m.__tablename__, [])
            for row in rows:
                db.session.add(m(**_parse(m, row)))
            db.session.flush()
            report[m.__tablename__] = len(rows)
        _fix_sequences()
        db.session.commit()
    except Exception as exc:                                # noqa: BLE001
        db.session.rollback()
        return None, f"Import to'xtatildi, hech narsa o'zgarmadi: {exc}"
    return report, ""


def _fix_sequences():
    """PostgreSQL'da id ketma-ketligini yangi maksimumga surish.

    Yozuvlar aniq id bilan kiritildi — ketma-ketlik surilmasa, keyingi
    qo'shilgan yozuv «id band» xatosiga uchraydi. SQLite'da shart emas.
    """
    if db.engine.dialect.name != "postgresql":
        return
    for m in TABLES:
        t = m.__tablename__
        db.session.execute(db.text(
            f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {t}), 1))"))
