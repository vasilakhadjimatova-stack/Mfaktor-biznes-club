"""Launch-hisob: yangi kurs oqimini ishga tushirish stsenariylari.

Manba — direktorning Google Sheets'dagi «MBM EVO ROP» varag'i. U yerdagi
mantiq birma-bir ko'chirildi:

  Tushum = Σ (kurs narxi × o'quvchi soni)
  Xarajat bloklari (Boshqaruv / Marketing / Sotuv / Servis):
     har qator yo qat'iy summa («fix»), yo tushumdan foiz («pct»),
     yo kishi boshiga («per»: narx × o'quvchi soni × dars soni —
     kofe-break kabi o'quvchi bilan o'sadigan xarajatlar uchun)
  Yalpi daromad = tushum − barcha bloklar
  Taqsimot sharsharasi:
     − hayriya (1–2.5%)  → − re-investitsiya (30%)  → − dividend solig'i (5%)
     = Dividend summasi → ta'sischilar 70% · direktor 10% · o'quv 1% ·
       buxgalteriya 2% → Yakuniy qoldiq (17%)

Bir nechta stsenariy yonma-yon turadi (varaqda uchta ustun bo'lgani kabi) —
narx yoki o'quvchi soni o'zgarsa natija qanday o'zgarishi darhol ko'rinadi.
Hisob brauzerda jonli bajariladi; bu modul faqat saqlash va boshlang'ich
namunani beradi.
"""
import json
import re
from datetime import date, timedelta

import localtime

from database import db
from models import (DdsRow, LaunchScenario, dds_activity, dds_group,
                    dds_norm)


def _blocks(kpi, target, vozvrat):
    """Varaqdagi 4 blok. kpi/target foizlari tushumdan olinadi."""
    return [
        {"title": "Boshqaruv", "rows": [
            {"n": "Fiksa (Boshqaruv, Buxgalteriya, Ta'sischilar)", "m": "fix", "v": 40_000_000},
            {"n": "Komunal to'lovlar", "m": "fix", "v": 10_000_000},
            {"n": "Buxgalteriya xonasi arendasi", "m": "fix", "v": 2_772_000},
            {"n": "Komissioniy xarajatlar", "m": "fix", "v": 3_000_000},
            {"n": "Nalog (ish haqi, dividend, QQS...)", "m": "fix", "v": 20_000_000},
            {"n": "Ta'sischilar dividend (fiksa)", "m": "fix", "v": 50_000_000},
            {"n": "Dolg", "m": "fix", "v": 21_692_000},
        ]},
        {"title": "Marketing", "rows": [
            {"n": "Fiksa marketing oyliklari", "m": "fix", "v": 14_200_000},
            {"n": "KPI marketolog", "m": "pct", "v": kpi},
            {"n": "KPI marketing komanda", "m": "pct", "v": kpi},
            {"n": "Target", "m": "pct", "v": target},
            {"n": "Studiya/kamera arenda", "m": "fix", "v": 4_000_000},
        ]},
        {"title": "Sotuv", "rows": [
            {"n": "Fiksa sotuv oyliklari", "m": "fix", "v": 25_000_000},
            {"n": "KPI РОП", "m": "pct", "v": kpi},
            {"n": "KPI sotuv komanda", "m": "pct", "v": kpi},
            {"n": "Telefon abonent to'lovlari", "m": "fix", "v": 1_523_000},
            {"n": "Sotuv programmasi to'lovlari", "m": "fix", "v": 6_500_000},
            {"n": "Vozvrat klient", "m": "fix", "v": vozvrat},
        ]},
        {"title": "Xizmat ko'rsatish (servis)", "rows": [
            {"n": "Fiksa servis", "m": "fix", "v": 13_000_000},
            {"n": "O'quv bo'limi va HR KPI", "m": "fix", "v": 1_000_000},
            # 40 000 so'm × har o'quvchi × 18 dars (varaqda 50 kishiga 36 mln)
            {"n": "Kofe-break", "m": "per", "v": 40_000, "d": 18},
            {"n": "O'qituvchilar gonorari (18 dars)", "m": "fix", "v": 24_000_000},
            {"n": "Xo'jalik tovarlari", "m": "fix", "v": 8_000_000},
            {"n": "Kanstovar", "m": "fix", "v": 3_000_000},
            {"n": "Internet", "m": "fix", "v": 5_477_000},
        ]},
    ]


def _dist(hayriya):
    return {"hayriya": hayriya, "reinvest": 30, "soliq": 5,
            "tasischilar": 70, "direktor": 10, "oquv": 1, "bux": 2}


def default_scenarios():
    """Bitta asosiy oqim + ikkita narx varianti.

    Xarajat tuzilmasi FAQAT birinchi (asosiy) stsenariyda saqlanadi.
    Variantlarda «blocks» yo'q — ular asosiydagi xarajatlarni qayta
    ishlatadi. Shuning uchun arenda yoki oylik o'zgarsa, uni bir joyda
    tuzatish kifoya: uch nusxani qo'lda tenglashtirib yurish kerak emas.
    """
    base = {
        "name": "РОП oqimi — asosiy",
        "courses": [{"name": "РОП", "price": 19_000_000, "qty": 50}],
        "blocks": _blocks(kpi=3, target=10, vozvrat=20_800_000),
        "dist": _dist(1),
    }
    out = [base]
    for name, price, hayriya in (("O'rtacha — 15 mln", 15_000_000, 2.5),
                                 ("Ehtiyotkor — 12 mln", 12_000_000, 2.5)):
        out.append({
            "name": name,
            "courses": [{"name": "РОП", "price": price, "qty": 50}],
            "dist": _dist(hayriya),
        })
    return out


def _same_blocks(a, b):
    """Ikki stsenariyning xarajat qatorlari mazmunan bir xilmi."""
    def flat(s):
        return [(bl.get("title"), r.get("n"), r.get("m"),
                 str(r.get("v")), str(r.get("d") or ""))
                for bl in (s.get("blocks") or []) for r in (bl.get("rows") or [])]
    return flat(a) == flat(b)


def all_scenarios():
    """Bazadagi stsenariylar; bo'sh bo'lsa namuna bilan to'ldiriladi.

    Eski nusxalarda har bir stsenariy o'z xarajat ro'yxatini olib yurardi.
    Agar ular asosiynikidan farq qilmasa — ortiqcha nusxa deb hisoblanadi
    va olib tashlanadi (variant asosiydan oladi). Farq qiladigan
    stsenariy o'z ro'yxatini saqlab qoladi.
    """
    rows = LaunchScenario.query.order_by(LaunchScenario.sort,
                                         LaunchScenario.id).all()
    if not rows:
        save_scenarios(default_scenarios())
        rows = LaunchScenario.query.order_by(LaunchScenario.sort,
                                             LaunchScenario.id).all()
    out = []
    for r in rows:
        try:
            d = json.loads(r.data)
        except ValueError:
            continue
        d["name"] = r.name
        _upgrade(d)
        if out and d.get("blocks") and _same_blocks(d, out[0]):
            d.pop("blocks")
        out.append(d)
    return out


def _upgrade(s):
    """Eski saqlangan stsenariylarda kofe-break qat'iy 36 mln bo'lib qolgan.

    Bu aynan namunadan kelgan qiymat (40 000 × 50 kishi × 18 dars), shuning
    uchun uni xavfsiz «per» rejimga o'tkazamiz — o'quvchi soni o'zgarsa
    xarajat ham o'zgaradigan bo'ladi. Qo'lda o'zgartirilgan boshqa
    summalarga tegilmaydi.
    """
    for b in s.get("blocks", []):
        for r in b.get("rows", []):
            if (r.get("n") == "Kofe-break" and r.get("m") == "fix"
                    and r.get("v") == 36_000_000):
                r.update({"m": "per", "v": 40_000, "d": 18})


def _parse_d(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def fakt_sums(items):
    """Jonli rejim: reja qatorlarini ДДСdagi haqiqiy yozuvlarga bog'lash.

    items = [{"q": "кофе", "dir": "out", "start": "2026-08-01", "end": ""}]
    Har element uchun {s: yig'indi, n: nechta yozuv} qaytadi.

    q — statya yoki naznacheniye ichida qidiriladigan so'z (registrsiz,
    dds_norm bilan). Yo'nalish statyaning spravochnikdagi guruhidan olinadi
    (Поступление/Выбытие) — hamyonlar orasidagi o'tkazmalar (texnik
    operatsiyalar) hisobga kirmaydi.
    """
    rows = []
    for r in DdsRow.query.all():
        if dds_activity(r.article) == "Техническая операция":
            continue
        rows.append((r.ddate, dds_group(r.article),
                     dds_norm(r.article) + " " + dds_norm(r.purpose),
                     float(r.amount or 0)))
    out = []
    for it in items:
        it = it if isinstance(it, dict) else {}
        q = dds_norm(it.get("q") or "")
        if not q:
            out.append({"s": 0, "n": 0})
            continue
        want = "Поступление" if it.get("dir") == "in" else "Выбытие"
        d1, d2 = _parse_d(it.get("start")), _parse_d(it.get("end"))
        # So'z boshidan moslash: «аренд» → «аренда» topiladi, lekin «роп»
        # «пропуск» ichidan topilib qolmaydi (oddiy substring shunday qilardi)
        q_re = re.compile(r"(?<!\w)" + re.escape(q))
        total, n = 0.0, 0
        for ddate, grp, text, amt in rows:
            if grp != want or not q_re.search(text):
                continue
            if d1 and (not ddate or ddate < d1):
                continue
            if d2 and (not ddate or ddate > d2):
                continue
            total += amt
            n += 1
        out.append({"s": round(total), "n": n})
    return out


# (?<!\d) — «125-dars»dan «25-dars»ni ushlab olmaslik uchun
_DARS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–]?\s*dars", re.IGNORECASE)


def _matched_rows(queries, d1, d2):
    """Qidiruv so'zlariga mos chiqim qatorlari (davr ichida)."""
    qs = [dds_norm(q) for q in queries if dds_norm(str(q or ""))]
    if not qs:
        return []
    out = []
    for r in DdsRow.query.all():
        if dds_activity(r.article) == "Техническая операция":
            continue
        if dds_group(r.article) != "Выбытие" or not r.ddate:
            continue
        text = dds_norm(r.article) + " " + dds_norm(r.purpose)
        if not any(q in text for q in qs):
            continue
        if d1 and r.ddate < d1:
            continue
        if d2 and r.ddate > d2:
            continue
        out.append(r)
    return out


def dars_journal(queries, start, end, kunlar=None):
    """Dars kunlari kesimi: xarajatlar darslarga biriktiriladi.

    kunlar — hafta kunlari (0=du .. 6=yak). Berilsa dars jadvali quriladi:
    davr boshidan (oxirigacha yoki bugungacha) o'sha kunlar = darslar.
    Xarajat darsga uch qoida bilan biriktiriladi:
      1) izohda «5-dars» bo'lsa — aynan o'sha darsga;
      2) aks holda sanasi bo'yicha ENG YAQIN dars kuniga (juma kofesi
         shanba darsiga, dushanba yozuvi yakshanba darsiga);
      3) jadval berilmasa — eski usul: har sana o'zi bir dars.

    Qaytadi: {"days": [{"d","i","s","n","items"}], "total": jadvaldagi
    jami dars soni (davr oxiri berilgan bo'lsa), "past": o'tgan darslar}
    """
    d1, d2 = _parse_d(start), _parse_d(end)
    rows = _matched_rows(queries, d1, d2)
    today = localtime.today()

    wd = set()
    for k in kunlar or []:
        try:
            k = int(k)
        except (TypeError, ValueError):
            continue
        if 0 <= k <= 6:
            wd.add(k)
    if wd and d1:
        horizon = d2 or today
        sched, d = [], d1
        while d <= horizon and len(sched) < 400:
            if d.weekday() in wd:
                sched.append(d)
            d += timedelta(days=1)
        if not sched:
            return {"days": [], "total": 0, "past": 0}
        lessons = {i: {"d": ld.isoformat(), "i": i + 1, "s": 0.0, "n": 0,
                       "items": []} for i, ld in enumerate(sched)}
        for r in rows:
            m = _DARS_RE.search(r.purpose or "")
            if m and 1 <= int(m.group(1)) <= len(sched):
                idx = int(m.group(1)) - 1
            else:
                idx = min(range(len(sched)),
                          key=lambda k: (abs((sched[k] - r.ddate).days), k))
            amt = float(r.amount or 0)
            L = lessons[idx]
            L["s"] += amt
            L["n"] += 1
            item = {"p": (r.purpose or r.article or "").strip()[:60],
                    "a": round(amt)}
            if r.ddate != sched[idx]:
                item["dd"] = r.ddate.strftime("%d.%m")
            L["items"].append(item)
        past = sum(1 for ld in sched if ld <= today)
        # ko'rsatiladiganlar: o'tgan darslar + xarajati bor kelgusilar
        days = [L for i, L in sorted(lessons.items())
                if sched[i] <= today or L["n"]]
        for L in days:
            L["s"] = round(L["s"])
        return {"days": days, "total": len(sched) if d2 else 0, "past": past}

    # jadvalsiz eski usul: har sana = bitta dars
    days = {}
    for r in rows:
        day = days.setdefault(r.ddate.isoformat(),
                              {"s": 0.0, "n": 0, "items": []})
        amt = float(r.amount or 0)
        day["s"] += amt
        day["n"] += 1
        day["items"].append({"p": (r.purpose or r.article or "").strip()[:60],
                             "a": round(amt)})
    out = [{"d": k, "i": i + 1, "s": round(v["s"]), "n": v["n"],
            "items": v["items"]}
           for i, (k, v) in enumerate(sorted(days.items()))]
    return {"days": out, "total": 0, "past": len(out)}


def save_scenarios(scenarios):
    """Hammasini butunlay almashtirib saqlaydi (sahifadagi holat = baza)."""
    if not isinstance(scenarios, list) or len(scenarios) > 12:
        return False
    for i, s in enumerate(scenarios):
        if not isinstance(s, dict) or not isinstance(s.get("courses"), list):
            return False
        # birinchisi — asosiy, xarajat ro'yxati unda bo'lishi shart;
        # variantlar uni qayta ishlatadi («blocks» bo'lmasligi mumkin)
        if i == 0:
            if not isinstance(s.get("blocks"), list):
                return False
        elif s.get("blocks") is not None and not isinstance(s["blocks"], list):
            return False
    LaunchScenario.query.delete(synchronize_session=False)
    for i, s in enumerate(scenarios):
        name = str(s.get("name") or f"Stsenariy {i+1}")[:120]
        db.session.add(LaunchScenario(name=name, sort=i,
                                      data=json.dumps(s, ensure_ascii=False)))
    db.session.commit()
    return True
