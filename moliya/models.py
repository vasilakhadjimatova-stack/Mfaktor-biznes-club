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
    "Поступление от клиента ТББ",
    "Поступление Б2Б",
    "Мфактор поступления",
    "Доход — долг",
    "Прочие поступления",
]
EXPENSE_CATS = [
    "Возврат клиенту",
    "Зарплата МБМ", "Зарплата СМК", "Зарплата РОП", "Зарплата ТББ",
    "Премия",
    "Аренда",
    "Налог/дивиденд Зп",
    "Дивиденды",
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
    "Хайрия",
    "Корпоративный расход",
    "Прочие расходы",
    "Расход — долг",
]

# Texnik operatsiya (hamyonlar orasi perevod) — hisobotlarda chiqmaydi,
# faqat hamyon qoldig'iga ta'sir qiladi
TRANSFER_CAT = "Перевод между счетами"

# Kurs yo'nalishi → kirim statyasi (kurs nomidan aniqlanadi)
DIRECTION_INCOME = {
    "РОП": "Поступление от клиента РОП",
    "ROP": "Поступление от клиента РОП",
    "СМК": "Поступление от клиента СМК",
    "SMK": "Поступление от клиента СМК",
    "ТББ": "Поступление от клиента ТББ",
    "TBB": "Поступление от клиента ТББ",
    "ТВВ": "Поступление от клиента ТББ",
}
# Kurs yo'nalishi → shu yo'nalish jamoasining ish haqi statyasi
DIRECTION_SALARY = {
    "РОП": "Зарплата РОП", "ROP": "Зарплата РОП",
    "СМК": "Зарплата СМК", "SMK": "Зарплата СМК",
    "ТББ": "Зарплата ТББ", "TBB": "Зарплата ТББ", "ТВВ": "Зарплата ТББ",
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
    # faoliyat turi: operating / finance / tech (perevod — hisobotdan tashqari)
    activity    = db.Column(db.String(20), default="operating", index=True)
    # «ДДС данные» qatoridan avtomat yaratilgan bo'lsa — manbaga bog'lanish.
    # Shu bog'lanish tufayli ДДС qatori tahrirlansa/o'chirilsa, kassa yozuvi
    # ham xuddi shunday yangilanadi (ikki marta hisoblanib ketmaydi).
    dds_row_id  = db.Column(db.Integer, db.ForeignKey("dds_rows.id"),
                            nullable=True, index=True)


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


class AutoEvent(db.Model):
    """Avtomatika jurnali — tizim har bir qadamda nima qilganini yozadi.

    'Bir amal → bir nechta jarayon' zanjirining ko'rinadigan izi:
    foydalanuvchi bitta ish qiladi, jurnal zanjirni ko'rsatadi.
    """
    __tablename__ = "auto_events"
    id         = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    kind       = db.Column(db.String(30), default="info")   # payment/contract/reminder/day/refund
    title      = db.Column(db.String(200), nullable=False)
    detail     = db.Column(db.Text, default="")
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=True)


class ReminderLog(db.Model):
    """Yuborilgan/tayyorlangan eslatmalar — takror bezovta qilmaslik uchun."""
    __tablename__ = "reminder_logs"
    id         = db.Column(db.Integer, primary_key=True)
    line_id    = db.Column(db.Integer, db.ForeignKey("installment_lines.id"), nullable=False)
    sent_date  = db.Column(db.Date, nullable=False)
    channel    = db.Column(db.String(20), default="manual")   # manual/sms/telegram


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


class KpiCard(db.Model):
    """Xodim/lavozim uchun oylik KPI kartasi (MBM KPI jadvalidan)."""
    __tablename__ = "kpi_cards"
    id         = db.Column(db.Integer, primary_key=True)
    year       = db.Column(db.Integer, nullable=False, index=True)
    month      = db.Column(db.Integer, nullable=False, index=True)
    role_key   = db.Column(db.String(40), nullable=False)     # rop/marketolog/kurator/hr
    role_name  = db.Column(db.String(120), nullable=False)
    person     = db.Column(db.String(120), default="")
    garant     = db.Column(db.Float, default=0.0)             # kafolatlangan oylik
    bonus_mode = db.Column(db.String(10), default="fixed")    # pct (tushumdan %) / fixed
    items      = db.relationship("KpiItem", backref="card",
                                 cascade="all, delete-orphan",
                                 order_by="KpiItem.id")


class KpiItem(db.Model):
    """Bitta KPI ko'rsatkichi: reja, fakt, vazn."""
    __tablename__ = "kpi_items"
    id         = db.Column(db.Integer, primary_key=True)
    card_id    = db.Column(db.Integer, db.ForeignKey("kpi_cards.id"), nullable=False)
    name       = db.Column(db.String(200), nullable=False)
    plan_value = db.Column(db.Float)                 # raqamli reja (bo'lsa)
    plan_label = db.Column(db.String(60), default="")  # matnli reja ("<2 hafta")
    unit       = db.Column(db.String(20), default="")  # so'm/ta/%/ball/$/kun
    weight     = db.Column(db.Float, default=0.0)
    fact       = db.Column(db.Float)                 # kiritilgan fakt
    inverse    = db.Column(db.Boolean, default=False)  # kichigi yaxshi (CPL, churn)
    auto_key   = db.Column(db.String(30), default="")  # moliyadan avto: sales_month/new_students


# ══════════════════════════════════════════════════════════════════
#  «ДДС данные» varag'i — 1:1 nusxa
# ══════════════════════════════════════════════════════════════════
# Kошелек ro'yxati (Excel data validation bilan bir xil tartibda)
DDS_WALLETS = ["РС MBM", "Наличные", "UZCARD 2406", "$",
               " РС DAVR BANK MBM", "PC MFAKTOR", "MFAKTOR karta"]
DDS_WALLET2 = ["Depozit", "Debitorka", "Toliq tolov"]

# Справочники: статья → (группа, вид деятельности)
DDS_SPRAVOCHNIK = [
    ("Поступление от клиента РОП", "Поступление", "Операционная"),
    ("Поступление от клиента СМК", "Поступление", "Операционная"),
    (" Поступление Б2Б", "Поступление", "Операционная"),
    ("Поступление от клиента TBB", "Поступление", "Операционная"),
    ("Мфактор поступления", "Поступление", "Операционная"),
    ("возврат поступления/клиент", "Выбытие", "Операционная"),
    ("зарплата ", "Выбытие", "Операционная"),
    ("зарплата  СМК ", "Выбытие", "Операционная"),
    ("зарплата  РОП", "Выбытие", "Операционная"),
    ("зарплата  ТББ", "Выбытие", "Операционная"),
    ("премия", "Выбытие", "Операционная"),
    ("аренда", "Выбытие", "Операционная"),
    ("налог дивиденд/Зп", "Выбытие", "Операционная"),
    ("обед сотрудники", "Выбытие", "Операционная"),
    ("Комиссия Банк", "Выбытие", "Операционная"),
    ("Комунальные услуги", "Выбытие", "Операционная"),
    ("Ремонт ", "Выбытие", "Операционная"),
    ("Таргет", "Выбытие", "Операционная"),
    ("Закуп/Хоз товар", "Выбытие", "Операционная"),
    ("Выпускное расходы", "Выбытие", "Операционная"),
    ("Кофе брейк", "Выбытие", "Операционная"),
    ("СРМ Online PBX", "Выбытие", "Операционная"),
    ("Такси", "Выбытие", "Операционная"),
    ("Интернет/Ip-телефония", "Выбытие", "Операционная"),
    ("Абонентские подписки", "Выбытие", "Операционная"),
    ("Хайрия", "Выбытие", "Операционная"),
    ("Корпоративный расход", "Выбытие", "Операционная"),
    ("прочие расходы", "Выбытие", "Операционная"),
    ("Продажа ОС", "Поступление", "Инвестиционная"),
    ("Покупка ОС", "Выбытие", "Инвестиционная"),
    ("Поступление кредитов и займов", "Поступление", "Финансовая"),
    ("Прочие поступления от фин. операции", "Поступление", "Финансовая"),
    ("Займ от собственника", "Поступление", "Финансовая"),
    ("Погашение тела кредита, займа", "Выбытие", "Финансовая"),
    ("Погашение процентов по кредитам, займам", "Выбытие", "Финансовая"),
    ("Дивиденды", "Выбытие", "Финансовая"),
    ("Доход — Перевод между счетами", "Поступление", "Техническая операция"),
    ("Расход — Перевод между счетами", "Выбытие", "Техническая операция"),
    ("Доход — долг ", "Поступление", "Операционная"),
    ("Расход — долг ", "Выбытие", "Операционная"),
]
DDS_LOOKUP = {a: (g, v) for a, g, v in DDS_SPRAVOCHNIK}


class DdsRow(db.Model):
    """«ДДС данные» varag'idagi bitta qator — 1:1 nusxa."""
    __tablename__ = "dds_rows"
    id       = db.Column(db.Integer, primary_key=True)
    rownum   = db.Column(db.Integer, index=True)          # Excel qator raqami
    ddate    = db.Column(db.Date, index=True)             # Дата (C)
    amount   = db.Column(db.Float, default=0.0)           # Сумма (D)
    wallet   = db.Column(db.String(60), default="")       # Кошелек (E)
    wallet2  = db.Column(db.String(40), default="")       # Кошелек (F)
    purpose  = db.Column(db.String(300), default="")      # Назначение платежа (G)
    article  = db.Column(db.String(120), default="")      # Статья (H)

    # ── Avtomatika maydonlari (Excel'da yo'q, dastur o'zi yuritadi) ──
    # moslash holati: none | auto | manual | skipped | new
    match_status = db.Column(db.String(12), default="none", index=True)
    # topilgan shartnoma (mijoz to'lovi bo'lsa)
    contract_id  = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                             nullable=True, index=True)
    match_score  = db.Column(db.Float, default=0.0)       # o'xshashlik 0..1

    tx = db.relationship("Transaction", backref="dds_row", uselist=False,
                         foreign_keys="Transaction.dds_row_id")
    contract = db.relationship("Contract", foreign_keys=[contract_id])

    # formulали ustunlar — Excel'dagi kabi hisoblanadi
    @property
    def month(self):                       # A: =IF(C=0,"",MONTH(C))
        return self.ddate.month if self.ddate else ""

    @property
    def year(self):                        # B: =IF(C=0,"",YEAR(C))
        return self.ddate.year if self.ddate else ""

    @property
    def flow(self):                        # I: VLOOKUP(Статья → Группа)
        return DDS_LOOKUP.get(self.article, ("", ""))[0]

    @property
    def activity(self):                    # J: VLOOKUP(Статья → Вид д-ти)
        return DDS_LOOKUP.get(self.article, ("", ""))[1]
