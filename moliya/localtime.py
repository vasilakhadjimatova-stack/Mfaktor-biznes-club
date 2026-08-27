"""Toshkent vaqti (UTC+5, mavsumiy o'tish yo'q).

Server qaysi mintaqada turishidan qat'i nazar «bugun» va «hozir» doim
Toshkent bo'yicha bo'lishi kerak: aks holda 00:00–05:00 orasida kunni
yopish, kechikkan to'lovlar va "bugun kirim" kechagi kunga yozilardi,
jurnal vaqtlari esa 5 soat orqada ko'rinardi.
"""
from datetime import datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5), "Asia/Tashkent")


def now():
    """Toshkent bo'yicha joriy vaqt (naive — bazaga shu holda yoziladi)."""
    return datetime.now(TASHKENT).replace(tzinfo=None)


def today():
    """Toshkent bo'yicha bugungi sana."""
    return now().date()
