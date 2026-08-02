"""
Mfaktor Moliya — ma'lumot modellari.

Ikki qatlamli moliya (ta'lim biznesining jahon standarti):
  1. KASSA QATLAMI (pul harakati) — Impulse Moliya andozasi:
     Wallet + Transaction (kirim/chiqim/transfer), ochilish qoldiqlari.
  2. HISOBLASH QATLAMI (accrual) — shartnoma asosida:
     Contract (kurs narxi) + InstallmentLine (to'lov grafigi).
     Daromad kurs davomiga taqsimlanadi (revenue recognition) —
     olingan avans darhol "foyda" emas, majburiyat (deferred revenue).

Unit-ekonomika uchun: MarketingSpend (kanal bo'yicha) → CAC, LTV, ARPU.
"""
from datetime import date, datetime

from database import db

# ── Lug'atlar — Mfaktor ДДС jadvali bilan 1:1 mos ────────────────
# (real Google Sheets'dagi statya nomlari saqlangan; Sheets import shunga tayanadi)
INCOME_CATS = [
    "Поступление от клиента РОП",
    "Поступление от клиента СМК",
    "Поступление от клиента ТВВ",
    "Поступление Б2Б",
    "Мфактор поступления",
    "Доход — долг",
    "Прочие поступления",
]
EXPENSE_CATS = [
    "Возврат клиенту",
    "Зарплата МФМ", "Зарплата СМК", "Зарплата РОП", "Зарплата ТВВ",
    "Премия",
    "Аренда",
    "Налог/дивиденд",
    "Обед сотрудников",
    "Комиссия банка",
    "Коммунальные услуги",
    "Ремонт",
    "Таргет (реклама)",
    "Закуп хоз. товаров",
    "Выпускные расходы",
    "Кофе-брейк",
    "CRM OnlinePBX",
    "Такси",
    "Интернет/IP-телефония",
    "Абонентские подписки",
    "Хайринг",
    "Корпоративный расход",
    "Прочие расходы",
    "Расход — долг",
]

# Kurs yo'nalishi → kirim statyasi (kurs nomidan aniqlanadi)
DIRECTION_INCOME = {
    "РОП": "Поступление от клиента РОП",
    "ROP": "Поступление от клиента РОП",
    "СМК": "Поступление от клиента СМК",
    "ТВВ": "Поступление от клиента ТВВ",
}
# Kurs yo'nalishi → shu yo'nalish jamoasining ish haqi statyasi
DIRECTION_SALARY = {
    "РОП": "Зарплата РОП", "ROP": "Зарплата РОП",
    "СМК": "Зарплата СМК", "ТВВ": "Зарплата ТВВ",
}


def income_cat_for_course(course_name):
    up = (course_name or "").upper()
    for key, cat in DIRECTION_INCOME.items():
        if key in up:
            return cat
    return "Мфактор поступления"


def salary_cat_for_course(course_name):
    up = (course_name or "").upper()
    for key, cat in DIRECTION_SALARY.items():
        if key in up:
            return cat
    return None
MARKETING_CHANNELS = [
    "Instagram", "Telegram", "YouTube", "Facebook", "Google",
    "Tavsiya", "Offline/Event", "Boshqa",
]
CONTRACT_STATUSES = {
    "active": "Faol", "completed": "Tugatgan",
    "refunded": "Qaytarilgan", "cancelled": "Bekor qilingan",
}


class Wallet(db.Model):
    """Hamyon: kassa, bank hisobi, Payme/Click, karta."""
    __tablename__ = "wallets"
    id       = db.Column(db.Integer, primary_key=True)
    code     = db.Column(db.String(20), unique=True, nullable=False)
    name     = db.Column(db.String(100), nullable=False)
    opening  = db.Column(db.Float, default=0.0)      # ochilish qoldig'i
    is_active = db.Column(db.Boolean, default=True)
    sort     = db.Column(db.Integer, default=0)


class Transaction(db.Model):
    """Pul harakati — kassa qatlami (Impulse Moliya andozasi)."""
    __tablename__ = "transactions"
    id          = db.Column(db.Integer, primary_key=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    tdate       = db.Column(db.Date, nullable=False, index=True)
    wallet_code = db.Column(db.String(20), nullable=False, index=True)
    operation   = db.Column(db.String(10), nullable=False, index=True)  # kirim/chiqim
    amount      = db.Column(db.Float, nullable=False)
    category    = db.Column(db.String(100), default="", index=True)     # statya
    counterparty = db.Column(db.String(200), default="")
    comment     = db.Column(db.Text, default="")
    # transfer: bitta yozuv, ikki hamyonga ta'sir qiladi
    is_transfer        = db.Column(db.Boolean, default=False)
    transfer_to_wallet = db.Column(db.String(20), default="")
    # shartnomaga bog'lanish (kurs to'lovi bo'lsa)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=True)
    # marketing chiqimi bo'lsa — kanal (CAC hisobi uchun)
    channel     = db.Column(db.String(50), default="")


class Course(db.Model):
    """Kurs (mahsulot): Sotuv menejeri, ROP, Kommersiya direktori..."""
    __tablename__ = "courses"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    base_price = db.Column(db.Float, default=0.0)
    is_active  = db.Column(db.Boolean, default=True)


class Cohort(db.Model):
    """Oqim/guruh — unit-ekonomika shu darajada hisoblanadi."""
    __tablename__ = "cohorts"
    id         = db.Column(db.Integer, primary_key=True)
    course_id  = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    name       = db.Column(db.String(100), nullable=False)   # masalan "SM-14 oqim"
    start_date = db.Column(db.Date, nullable=False)
    end_date   = db.Column(db.Date, nullable=False)
    capacity   = db.Column(db.Integer, default=30)           # o'rinlar (fill rate uchun)
    course     = db.relationship("Course")

    def duration_days(self):
        return max((self.end_date - self.start_date).days, 1)


class Student(db.Model):
    __tablename__ = "students"
    id      = db.Column(db.Integer, primary_key=True)
    name    = db.Column(db.String(200), nullable=False)
    phone   = db.Column(db.String(50), default="")
    source  = db.Column(db.String(50), default="")   # qaysi kanaldan keldi (CAC/LTV)
    note    = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Contract(db.Model):
    """O'quv shartnomasi — hisoblash qatlamining markazi."""
    __tablename__ = "contracts"
    id          = db.Column(db.Integer, primary_key=True)
    student_id  = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    cohort_id   = db.Column(db.Integer, db.ForeignKey("cohorts.id"), nullable=False)
    price       = db.Column(db.Float, nullable=False)        # kelishilgan narx
    discount    = db.Column(db.Float, default=0.0)           # chegirma/grant summasi
    signed_date = db.Column(db.Date, nullable=False)
    status      = db.Column(db.String(20), default="active")
    refund_amount = db.Column(db.Float, default=0.0)         # 1 haftalik kafolat bo'yicha
    note        = db.Column(db.Text, default="")
    student = db.relationship("Student", backref="contracts")
    cohort  = db.relationship("Cohort")
    lines   = db.relationship("InstallmentLine", backref="contract",
                              order_by="InstallmentLine.due_date",
                              cascade="all, delete-orphan")

    @property
    def net_price(self):
        return max(self.price - self.discount, 0.0)

    def paid_total(self):
        return sum(l.paid for l in self.lines)

    def due_total(self):
        return max(self.net_price - self.refund_amount - self.paid_total(), 0.0)


class InstallmentLine(db.Model):
    """Bo'lib to'lash grafigi qatori."""
    __tablename__ = "installment_lines"
    id          = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False)
    due_date    = db.Column(db.Date, nullable=False, index=True)
    amount      = db.Column(db.Float, nullable=False)
    paid        = db.Column(db.Float, default=0.0)

    def overdue_days(self, today=None):
        today = today or date.today()
        if self.paid >= self.amount - 0.01:
            return 0
        return max((today - self.due_date).days, 0)


class Budget(db.Model):
    """Oylik reja (plan-fakt) — statya bo'yicha."""
    __tablename__ = "budgets"
    id       = db.Column(db.Integer, primary_key=True)
    year     = db.Column(db.Integer, nullable=False, index=True)
    month    = db.Column(db.Integer, nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False)
    btype    = db.Column(db.String(10), default="expense")   # income/expense
    planned  = db.Column(db.Float, default=0.0)


class RecurringPayment(db.Model):
    """Takrorlanuvchi to'lov (ijara, oyliklar, obunalar)."""
    __tablename__ = "recurring_payments"
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(200), nullable=False)
    amount   = db.Column(db.Float, nullable=False)
    pay_day  = db.Column(db.Integer, default=1)      # oyning kuni
    category = db.Column(db.String(100), default="")
    is_active = db.Column(db.Boolean, default=True)
