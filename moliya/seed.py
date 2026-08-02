"""Demo ma'lumot — tizimni birinchi ochishda 'jonli' ko'rish uchun.

    python seed.py
"""
import random
from datetime import date, timedelta

from app import create_app
from database import db
from models import (Budget, Cohort, Contract, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction, Wallet)

NAMES = ["Aziz Karimov", "Malika Yusupova", "Jasur Toshpulatov", "Dilnoza Rahimova",
         "Sardor Aliyev", "Nilufar Ergasheva", "Bekzod Nazarov", "Gulnora Islomova",
         "Otabek Qodirov", "Zilola Mirzayeva", "Shohruh Berdiyev", "Kamola Saidova",
         "Ulug'bek Hamidov", "Feruza Abdullayeva", "Doston Ravshanov", "Sevara To'rayeva",
         "Islom Yo'ldoshev", "Madina Xolmatova", "Farrux Sobirov", "Nargiza Olimova"]
SOURCES = ["Instagram", "Telegram", "YouTube", "Tavsiya", "Instagram", "Telegram"]


def run():
    app = create_app()
    with app.app_context():
        if Wallet.query.count():
            print("Baza bo'sh emas — seed o'tkazib yuborildi.")
            return
        random.seed(7)
        today = date.today()

        wallets = [
            Wallet(code="kassa", name="Naqd kassa", opening=8_500_000, sort=1),
            Wallet(code="bank", name="Bank hisobi (asosiy)", opening=42_000_000, sort=2),
            Wallet(code="payme", name="Payme merchant", opening=5_200_000, sort=3),
            Wallet(code="click", name="Click merchant", opening=3_100_000, sort=4),
        ]
        db.session.add_all(wallets)

        sm = Course(name="Sotuv menejeri kursi", base_price=4_000_000)
        rop = Course(name="Sotuv bo'limi rahbari (ROP)", base_price=7_000_000)
        db.session.add_all([sm, rop])
        db.session.flush()

        c_old = Cohort(course_id=sm.id, name="SM-13",
                       start_date=today - timedelta(days=75),
                       end_date=today - timedelta(days=15), capacity=30)
        c_cur = Cohort(course_id=sm.id, name="SM-14",
                       start_date=today - timedelta(days=25),
                       end_date=today + timedelta(days=35), capacity=30)
        c_rop = Cohort(course_id=rop.id, name="ROP-3",
                       start_date=today - timedelta(days=10),
                       end_date=today + timedelta(days=80), capacity=15)
        db.session.add_all([c_old, c_cur, c_rop])
        db.session.flush()

        plan = [(c_old, 14, "completed"), (c_cur, 18, "active"), (c_rop, 6, "active")]
        ni = 0
        for cohort, count, status in plan:
            for _ in range(count):
                st = Student(name=NAMES[ni % len(NAMES)],
                             phone=f"+99890{random.randint(1000000, 9999999)}",
                             source=random.choice(SOURCES))
                ni += 1
                db.session.add(st)
                db.session.flush()
                price = cohort.course.base_price
                disc = random.choice([0, 0, 0, 400_000])
                signed = cohort.start_date - timedelta(days=random.randint(3, 20))
                ct = Contract(student_id=st.id, cohort_id=cohort.id,
                              price=price, discount=disc,
                              signed_date=signed, status=status)
                db.session.add(ct)
                db.session.flush()
                n = random.choice([1, 2, 2, 3])
                per = ct.net_price / n
                for i in range(n):
                    db.session.add(InstallmentLine(
                        contract_id=ct.id,
                        due_date=signed + timedelta(days=30 * i), amount=per))
                db.session.flush()
                # to'lovlar: tugatganlar to'liq, faollar qisman
                pay_ratio = 1.0 if status == "completed" else random.choice([1.0, 0.66, 0.5, 0.34])
                topay = ct.net_price * pay_ratio
                for line in ct.lines:
                    if topay <= 0:
                        break
                    p = min(line.amount, topay)
                    line.paid = p
                    topay -= p
                    db.session.add(Transaction(
                        tdate=min(line.due_date, today),
                        wallet_code=random.choice(["payme", "click", "bank", "kassa"]),
                        operation="kirim", amount=p, category="Kurs to'lovi",
                        counterparty=st.name, contract_id=ct.id))

        # oxirgi 2 oy chiqimlari
        for back in (1, 0):
            base = today.replace(day=5) - timedelta(days=30 * back)
            db.session.add_all([
                Transaction(tdate=base, wallet_code="bank", operation="chiqim",
                            amount=18_000_000, category="Ish haqi (admin)",
                            counterparty="Jamoa"),
                Transaction(tdate=base, wallet_code="bank", operation="chiqim",
                            amount=9_000_000, category="Ijara",
                            counterparty="Biznes markaz"),
                Transaction(tdate=base + timedelta(days=3), wallet_code="bank",
                            operation="chiqim", amount=14_500_000,
                            category="Spiker gonorari", counterparty="Spikerlar"),
                Transaction(tdate=base + timedelta(days=1), wallet_code="click",
                            operation="chiqim", amount=6_200_000,
                            category="Marketing/Reklama", channel="Instagram",
                            counterparty="Meta Ads"),
                Transaction(tdate=base + timedelta(days=2), wallet_code="payme",
                            operation="chiqim", amount=2_800_000,
                            category="Marketing/Reklama", channel="Telegram",
                            counterparty="Tg kanallar"),
                Transaction(tdate=base + timedelta(days=6), wallet_code="bank",
                            operation="chiqim", amount=1_900_000,
                            category="Kontent ishlab chiqarish",
                            counterparty="Video studiya"),
                Transaction(tdate=base + timedelta(days=8), wallet_code="bank",
                            operation="chiqim", amount=1_200_000,
                            category="Texnik platforma/IT", counterparty="Servislar"),
            ])

        db.session.add_all([
            RecurringPayment(name="Ofis ijarasi", amount=9_000_000, pay_day=5,
                             category="Ijara"),
            RecurringPayment(name="Admin jamoa ish haqi", amount=18_000_000,
                             pay_day=5, category="Ish haqi (admin)"),
            RecurringPayment(name="IT servislar (LMS, CRM)", amount=1_200_000,
                             pay_day=10, category="Texnik platforma/IT"),
        ])
        for cat, btype, plan_sum in [
            ("Kurs to'lovi", "income", 80_000_000),
            ("Korporativ xizmat", "income", 25_000_000),
            ("Marketing/Reklama", "expense", 10_000_000),
            ("Spiker gonorari", "expense", 16_000_000),
            ("Ish haqi (admin)", "expense", 18_000_000),
        ]:
            db.session.add(Budget(year=today.year, month=today.month,
                                  category=cat, btype=btype, planned=plan_sum))
        db.session.commit()
        print("Demo ma'lumot yozildi:",
              Student.query.count(), "o'quvchi,",
              Contract.query.count(), "shartnoma,",
              Transaction.query.count(), "tranzaksiya.")


if __name__ == "__main__":
    run()
