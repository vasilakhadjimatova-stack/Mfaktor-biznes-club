"""
Boshlang'ich ma'lumot — birinchi ishga tushirishda: python seed.py

Yaratadi: direktor (admin) + o'quv bo'limi rahbari + namunaviy kurslar.
Idempotent — qayta ishga tushirsa takrorlamaydi.
"""
from app import app
from database import db
from models.user import User
from models.education import Course


def _user(name, code, position, department, is_admin=False, perm=None):
    u = User.query.filter_by(code=code).first()
    if u:
        return u
    u = User(name=name, code=code, position=position,
             department=department, is_admin=is_admin)
    if perm is not None:
        u.perm = perm
    db.session.add(u)
    print(f"  + {name} ({position}) — kod: {code}")
    return u


def _course(name, weeks, price, desc=""):
    if Course.query.filter_by(name=name).first():
        return
    db.session.add(Course(name=name, duration_weeks=weeks,
                          price=price, description=desc))
    print(f"  + Kurs: {name}")


with app.app_context():
    print("Mfaktor ERP — boshlang'ich ma'lumot:")
    _user("Direktor", "100001", "Direktor", "Boshqaruv", is_admin=True)
    _user("O'quv bo'limi rahbari", "200001", "O'quv bo'limi rahbari",
          "O'quv bo'limi", perm=["education"])
    _course("Sotuv menejeri kursi", 8, 0,
            "Asosiy mahsulot — amaliy sotuv ko'nikmalari")
    _course("Sotuv bo'limi rahbari (ROP)", 10, 0, "")
    _course("Tadbirkorlar uchun AI", 6, 0,
            "Yangi yo'nalish — biznes jarayonlariga AI joriy qilish")
    db.session.commit()
    print("Tayyor. Kirish: python app.py → http://localhost:5070")
