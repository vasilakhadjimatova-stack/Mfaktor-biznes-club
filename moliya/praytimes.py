"""
Namoz vaqtlari — lokal astronomik hisob (tashqi API'siz, oflaynda ham ishlaydi).

Usul: Muslim World League (Bomdod 18°, Xufton 17°) + Hanafiy Asr (soya 2x)
— O'zbekiston amaliyotiga mos. Standart PrayTimes algoritmi asosida.

Eslatma: rasmiy taqvim bilan 1-3 daqiqa farq bo'lishi mumkin (muftiyat
jadvali qo'lda tuziladi) — interfeysda "taxminiy" deb belgilangan.
"""
import math
from datetime import date, datetime, timedelta

# Toshkent (standart); keyin sozlamalardan o'zgartirsa bo'ladi
LAT, LON, TZ = 41.2995, 69.2401, 5.0
FAJR_ANGLE, ISHA_ANGLE = 18.0, 17.0
ASR_FACTOR = 2  # Hanafiy

NAMES = [("bomdod", "Bomdod"), ("quyosh", "Quyosh"), ("peshin", "Peshin"),
         ("asr", "Asr"), ("shom", "Shom"), ("xufton", "Xufton")]


def _sun_position(jd):
    d = jd - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = (280.459 + 0.98564736 * d) % 360
    L = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    e = math.radians(23.439 - 0.00000036 * d)
    decl = math.asin(math.sin(e) * math.sin(L))
    ra = math.degrees(math.atan2(math.cos(e) * math.sin(L), math.cos(L))) / 15
    eqt = q / 15 - (ra % 24)
    return decl, eqt


def _julian(y, m, d):
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + d + b - 1524.5)


def _hour_angle(angle, decl):
    lat = math.radians(LAT)
    cos_h = ((-math.sin(math.radians(angle)) - math.sin(lat) * math.sin(decl))
             / (math.cos(lat) * math.cos(decl)))
    cos_h = max(-1.0, min(1.0, cos_h))
    return math.degrees(math.acos(cos_h)) / 15


def _asr_angle(decl):
    lat = math.radians(LAT)
    return -math.degrees(math.atan(1 / (ASR_FACTOR + math.tan(abs(lat - decl)))))


def times_for(day=None):
    """Kun uchun vaqtlar: [{'key','name','time','minutes'}] (mahalliy vaqt)."""
    day = day or date.today()
    jd = _julian(day.year, day.month, day.day)
    decl, eqt = _sun_position(jd + 0.5 - LON / (15 * 24))
    noon = (12 - eqt) % 24 - LON / 15 + TZ   # quyosh eng balandda

    fajr = noon - _hour_angle(FAJR_ANGLE, decl)
    sunrise = noon - _hour_angle(0.833, decl)
    asr = noon + _hour_angle(_asr_angle(decl), decl)
    maghrib = noon + _hour_angle(0.833, decl)
    isha = noon + _hour_angle(ISHA_ANGLE, decl)

    raw = {"bomdod": fajr, "quyosh": sunrise, "peshin": noon + 2 / 60,
           "asr": asr, "shom": maghrib, "xufton": isha}
    out = []
    for key, name in NAMES:
        h = raw[key] % 24
        minutes = int(round(h * 60))
        out.append({"key": key, "name": name,
                    "time": f"{minutes // 60:02d}:{minutes % 60:02d}",
                    "minutes": minutes})
    return out


def today_with_next(now=None):
    """Bugungi vaqtlar + keyingi namoz belgilangan holda."""
    now = now or datetime.now()
    times = times_for(now.date())
    cur = now.hour * 60 + now.minute
    # "Quyosh" namoz emas — keyingi hisobida o'tkaziladi
    prayer_keys = ("bomdod", "peshin", "asr", "shom", "xufton")
    nxt = None
    for t in times:
        if t["key"] in prayer_keys and t["minutes"] > cur:
            nxt = t
            break
    if nxt is None:  # bugungi hammasi o'tdi — ertangi bomdod
        tomorrow = times_for(now.date() + timedelta(days=1))
        nxt = dict(tomorrow[0])
        nxt["minutes"] += 24 * 60
    left = nxt["minutes"] - cur
    for t in times:
        t["is_next"] = (t["key"] == nxt["key"] and t["minutes"] % (24 * 60) == nxt["minutes"] % (24 * 60))
    return {"times": times, "next": nxt,
            "left_h": left // 60, "left_m": left % 60,
            "date_str": now.strftime("%d.%m.%Y")}
