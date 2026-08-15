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
from datetime import date

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
    """Varaqdagi uchta avgust ustuni — boshlang'ich namuna."""
    out = []
    for name, price, hayriya in (("Optimistik — 19 mln", 19_000_000, 1),
                                 ("O'rtacha — 15 mln", 15_000_000, 2.5),
                                 ("Ehtiyotkor — 12 mln", 12_000_000, 2.5)):
        out.append({
            "name": name,
            "courses": [{"name": "РОП", "price": price, "qty": 50}],
            "blocks": _blocks(kpi=3, target=10, vozvrat=20_800_000),
            "dist": _dist(hayriya),
        })
    return out


def all_scenarios():
    """Bazadagi stsenariylar; bo'sh bo'lsa namuna bilan to'ldiriladi."""
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
        total, n = 0.0, 0
        for ddate, grp, text, amt in rows:
            if grp != want or q not in text:
                continue
            if d1 and (not ddate or ddate < d1):
                continue
            if d2 and (not ddate or ddate > d2):
                continue
            total += amt
            n += 1
        out.append({"s": round(total), "n": n})
    return out


def save_scenarios(scenarios):
    """Hammasini butunlay almashtirib saqlaydi (sahifadagi holat = baza)."""
    if not isinstance(scenarios, list) or len(scenarios) > 12:
        return False
    for s in scenarios:
        if not isinstance(s, dict) or not isinstance(s.get("courses"), list) \
                or not isinstance(s.get("blocks"), list):
            return False
    LaunchScenario.query.delete(synchronize_session=False)
    for i, s in enumerate(scenarios):
        name = str(s.get("name") or f"Stsenariy {i+1}")[:120]
        db.session.add(LaunchScenario(name=name, sort=i,
                                      data=json.dumps(s, ensure_ascii=False)))
    db.session.commit()
    return True
