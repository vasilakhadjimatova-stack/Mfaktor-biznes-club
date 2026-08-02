"""Demo ma'lumot — tizimni birinchi ochishda 'jonli' ko'rish uchun.

Hamyonlar va statyalar REAL Mfaktor ДДС jadvali bilan 1:1 mos;
summalar esa demo (real raqamlar import_dds.py orqali yuklanadi).

    python seed.py
"""
import random
from datetime import date, timedelta

from app import create_app
from database import db
from models import (Budget, Cohort, Contract, Course, InstallmentLine,
                    RecurringPayment, Student, Transaction, Wallet,
                    income_cat_for_course)

NAMES = ["Aziz Karimov", "Malika Yusupova", "Jasur Toshpulatov", "Dilnoza Rahimova",
         "Sardor Aliyev", "Nilufar Ergasheva", "Bekzod Nazarov", "Gulnora Islomova",
         "Otabek Qodirov", "Zilola Mirzayeva", "Shohruh Berdiyev", "Kamola Saidova",
         "Ulug'bek Hamidov", "Feruza Abdullayeva", "Doston Ravshanov", "Sevara To'rayeva",
         "Islom Yo'ldoshev", "Madina Xolmatova", "Farrux Sobirov", "Nargiza Olimova"]
SOURCES = ["Instagram", "Telegram", "YouTube", "Tavsiya", "Instagram", "Telegram"]
PAY_WALLETS = ["rs_mfm", "nal", "karta_mfaktor", "rs_mfaktor"]


def run():
    app = create_app()
    with app.app_context():
        if Wallet.query.count():
            print("Baza bo'sh emas — seed o'tkazib yuborildi.")
            return
        random.seed(7)
        today = date.today()

        # Hamyonlar — real ДДС jadvalidagi ro'yxat (ochilish qoldiqlari demo)
        wallets = [
            Wallet(code="rs_mfm", name="р.с МФМ", opening=36_000_000, sort=1),
            Wallet(code="nal", name="нал сум", opening=8_000_000, sort=2),
            Wallet(code="rs_mfm_davr", name="р.с МФМ Davr bank", opening=28_000_000, sort=3),
            Wallet(code="usd", name="$ (valyuta)", opening=60_000_000, sort=4),
            Wallet(code="karta2406", name="карта 2406", opening=1_000_000, sort=5),
            Wallet(code="rs_mfaktor", name="РС Mfaktor", opening=16_000_000, sort=6),
            Wallet(code="karta_mfaktor", name="карта MFAKTOR", opening=1_600_000, sort=7),
        ]
        db.session.add_all(wallets)

        smk = Course(name="Sotuv menejerlari kursi (СМК)", base_price=4_000_000)
        rop = Course(name="Sotuv bo'limi rahbari (РОП)", base_price=7_000_000)
        tvv = Course(name="ТВВ yo'nalishi", base_price=5_000_000)
        db.session.add_all([smk, rop, tvv])
        db.session.flush()

        c_old = Cohort(course_id=smk.id, name="СМК-13",
                       start_date=today - timedelta(days=75),
                       end_date=today - timedelta(days=15), capacity=30)
        c_cur = Cohort(course_id=smk.id, name="СМК-14",
                       start_date=today - timedelta(days=25),
                       end_date=today + timedelta(days=35), capacity=30)
        c_rop = Cohort(course_id=rop.id, name="РОП-3",
                       start_date=today - timedelta(days=10),
                       end_date=today + timedelta(days=80), capacity=15)
        c_tvv = Cohort(course_id=tvv.id, name="ТВВ-5",
                       start_date=today - timedelta(days=20),
                       end_date=today + timedelta(days=40), capacity=20)
        db.session.add_all([c_old, c_cur, c_rop, c_tvv])
        db.session.flush()

        plan = [(c_old, 14, "completed"), (c_cur, 18, "active"),
                (c_rop, 6, "active"), (c_tvv, 8, "active")]
        ni = 0
        for cohort, count, status in plan:
            income_cat = income_cat_for_course(cohort.course.name)
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
                        wallet_code=random.choice(PAY_WALLETS),
                        operation="kirim", amount=p, category=income_cat,
                        counterparty=st.name, contract_id=ct.id))

        # oxirgi 2 oy chiqimlari — real statya nomlari bilan
        for back in (1, 0):
            base = today.replace(day=5) - timedelta(days=30 * back)
            db.session.add_all([
                Transaction(tdate=base, wallet_code="rs_mfm", operation="chiqim",
                            amount=22_000_000, category="Зарплата МФМ",
                            counterparty="Admin jamoa"),
                Transaction(tdate=base, wallet_code="rs_mfm", operation="chiqim",
                            amount=6_500_000, category="Зарплата СМК",
                            counterparty="СМК jamoasi"),
                Transaction(tdate=base, wallet_code="rs_mfm", operation="chiqim",
                            amount=8_200_000, category="Зарплата РОП",
                            counterparty="РОП jamoasi"),
                Transaction(tdate=base + timedelta(days=2), wallet_code="rs_mfm",
                            operation="chiqim", amount=14_000_000,
                            category="Премия", counterparty="Jamoa"),
                Transaction(tdate=base, wallet_code="rs_mfm_davr",
                            operation="chiqim", amount=6_000_000,
                            category="Аренда", counterparty="Biznes markaz"),
                Transaction(tdate=base + timedelta(days=3), wallet_code="rs_mfm",
                            operation="chiqim", amount=7_500_000,
                            category="Налог/дивиденд", counterparty="Soliq"),
                Transaction(tdate=base + timedelta(days=1), wallet_code="karta2406",
                            operation="chiqim", amount=9_800_000,
                            category="Таргет (реклама)", channel="Instagram",
                            counterparty="Meta Ads"),
                Transaction(tdate=base + timedelta(days=2), wallet_code="karta2406",
                            operation="chiqim", amount=3_100_000,
                            category="Таргет (реклама)", channel="Telegram",
                            counterparty="Tg kanallar"),
                Transaction(tdate=base + timedelta(days=4), wallet_code="nal",
                            operation="chiqim", amount=4_200_000,
                            category="Кофе-брейк", counterparty="Kofe-breyk"),
                Transaction(tdate=base + timedelta(days=5), wallet_code="nal",
                            operation="chiqim", amount=1_500_000,
                            category="Обед сотрудников", counterparty="Oshxona"),
                Transaction(tdate=base + timedelta(days=6), wallet_code="rs_mfm",
                            operation="chiqim", amount=1_200_000,
                            category="CRM OnlinePBX", counterparty="OnlinePBX"),
                Transaction(tdate=base + timedelta(days=7), wallet_code="rs_mfm",
                            operation="chiqim", amount=900_000,
                            category="Комиссия банка", counterparty="Bank"),
                Transaction(tdate=base + timedelta(days=8), wallet_code="rs_mfm",
                            operation="chiqim", amount=1_100_000,
                            category="Интернет/IP-телефония", counterparty="Provayder"),
            ])

        db.session.add_all([
            RecurringPayment(name="Ofis ijarasi", amount=6_000_000, pay_day=5,
                             category="Аренда"),
            RecurringPayment(name="Admin jamoa ish haqi", amount=22_000_000,
                             pay_day=5, category="Зарплата МФМ"),
            RecurringPayment(name="CRM OnlinePBX", amount=1_200_000,
                             pay_day=10, category="CRM OnlinePBX"),
            RecurringPayment(name="Internet/IP-telefoniya", amount=1_100_000,
                             pay_day=10, category="Интернет/IP-телефония"),
        ])
        for cat, btype, plan_sum in [
            ("Поступление от клиента СМК", "income", 70_000_000),
            ("Поступление от клиента РОП", "income", 40_000_000),
            ("Поступление от клиента ТВВ", "income", 35_000_000),
            ("Таргет (реклама)", "expense", 14_000_000),
            ("Премия", "expense", 15_000_000),
            ("Зарплата МФМ", "expense", 22_000_000),
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
