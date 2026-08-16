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
import unicodedata
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

class LaunchScenario(db.Model):
    """Launch-hisob stsenariysi — tarkibi JSON (launch.py ga qarang)."""
    __tablename__ = "launch_scenarios"
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), default="")
    sort = db.Column(db.Integer, default=0)
    data = db.Column(db.Text, default="{}")


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


class AppSetting(db.Model):
    """Dastur ichki sozlamalari (kalit → qiymat).

    Sessiya imzosi uchun maxfiy kalit shu yerda saqlanadi: SECRET_KEY
    muhit o'zgaruvchisi berilmagan bo'lsa, tasodifiy kalit bir marta
    yaratilib bazaga yoziladi. Shu tufayli kalit kodda ochiq turmaydi,
    server qayta ishga tushganda ham, bir nechta ishchi jarayonda ham
    bir xil bo'ladi (aks holda foydalanuvchi tizimdan chiqib ketardi).
    """
    __tablename__ = "app_settings"
    key   = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.Text, default="")


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
    # Ilova kaliti o'quvchida turadi — u bir nechta kursga yozilsa ham
    # bitta havola bilan hammasini ko'radi.
    portal_token = db.Column(db.String(48), unique=True, index=True)
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
    # O'quv bo'limi: dropout risk (education.py hisoblaydi)
    # O'quvchi kabineti uchun shaxsiy havola kaliti (parolsiz kirish).
    # Faqat kerak bo'lganda yaratiladi — har shartnomada bo'lishi shart emas.
    portal_token = db.Column(db.String(48), unique=True, index=True)
    tg_chat_id   = db.Column(db.String(32), default="")   # Telegram bog'lanishi
    risk_score   = db.Column(db.Integer, default=0)          # 0–100
    risk_reasons = db.Column(db.String(300), default="")
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
    ("Поступление от клиента ТББ", "Поступление", "Операционная"),
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

# Excel spravochnigidagi ba'zi statyalar bosh/oxirgi bo'shliq bilan yozilgan
# (" Поступление Б2Б", "Доход — долг "). Brauzer <option> qiymatini yuborishda
# bo'shliqni olib tashlaydi, ya'ni sayt formasidan kelgan nom lug'atdagi
# kalitga aynan mos kelmaydi. Shu sababli izlash normallashtirilgan holatda
# olib boriladi — aks holda guruh topilmay, kirim chiqim bo'lib yozilardi.
def dds_norm(s):
    return " ".join(unicodedata.normalize("NFKC", str(s or "")).strip().lower().split())


DDS_LOOKUP_N = {dds_norm(a): (g, v) for a, g, v in DDS_SPRAVOCHNIK}


def dds_group(article):
    """Statya → «Поступление»/«Выбытие» (bo'shliq va registrga bardoshli)."""
    return DDS_LOOKUP_N.get(dds_norm(article), ("", ""))[0]


def dds_activity(article):
    """Statya → faoliyat turi (Операционная/Финансовая/...)."""
    return DDS_LOOKUP_N.get(dds_norm(article), ("", ""))[1]


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
    # grafikka haqiqatda yozilgan summa. To'lov shartnoma qoldig'idan katta
    # bo'lsa, uning bir qismi ortib qoladi (avans) — bekor qilishda aynan
    # shu yozilgan qism qaytarilishi kerak, aks holda boshqa to'lovning puli
    # ham yechilib ketardi.
    applied_amount = db.Column(db.Float, default=0.0)
    # chetlatish sababi — «nega bu to'lov navbatda emas» degan savolga
    # keyin ham javob topilsin (masalan: «avvalgi guruhlar, reyestr yo'q»)
    skip_note = db.Column(db.String(200), default="")
    # qator qayerdan: "excel" (import) yoki "app" (dasturda qo'lda kiritilgan).
    # Excel qayta-import faqat "excel" qatorlarni almashtiradi — dasturda
    # kiritilganlar (o'tkazma tuzatishi, kofe-break va h.k.) saqlanadi.
    origin = db.Column(db.String(8), default="excel", index=True)

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
        return dds_group(self.article)

    @property
    def activity(self):                    # J: VLOOKUP(Статья → Вид д-ти)
        return dds_activity(self.article)


# ══════════════════════════════════════════════════════════════════
#  O'QUV BO'LIMI (LMS) — davomat, vazifalar, AI baholash, sertifikat
#  «O'quvchi oqimda» birligi = Contract (shartnoma) — moliya bilan
#  bitta zanjir: davomat/vazifa signallari + to'lov kechikishi →
#  dropout risk-skoring (education.py).
# ══════════════════════════════════════════════════════════════════

ATT_STATUSES = {
    "present": "Keldi",
    "late":    "Kechikdi",
    "absent":  "Kelmadi",
    "excused": "Sababli",
}


class LessonSession(db.Model):
    """Dars mashg'uloti — oqimning bitta darsi."""
    __tablename__ = "lesson_sessions"
    id        = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohorts.id"),
                          nullable=False, index=True)
    date      = db.Column(db.Date, nullable=False)
    topic     = db.Column(db.String(200), default="")
    held      = db.Column(db.Boolean, default=False)   # davomat olindimi
    cohort    = db.relationship("Cohort", backref="sessions")


class LessonAttendance(db.Model):
    """Bitta dars bo'yicha bitta o'quvchi (shartnoma) davomati."""
    __tablename__ = "lesson_attendance"
    __table_args__ = (
        db.UniqueConstraint("session_id", "contract_id",
                            name="uq_att_session_contract"),
    )
    id          = db.Column(db.Integer, primary_key=True)
    session_id  = db.Column(db.Integer, db.ForeignKey("lesson_sessions.id"),
                            nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            nullable=False, index=True)
    status      = db.Column(db.String(12), nullable=False, default="present")
    session     = db.relationship("LessonSession", backref="attendance")
    contract    = db.relationship("Contract")


class Assignment(db.Model):
    """Uy vazifasi — oqimga beriladi."""
    __tablename__ = "assignments"
    id          = db.Column(db.Integer, primary_key=True)
    cohort_id   = db.Column(db.Integer, db.ForeignKey("cohorts.id"),
                            nullable=False, index=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")   # AI baholashda rubrika
    due_date    = db.Column(db.Date)
    max_score   = db.Column(db.Integer, default=100)
    # dars materiali: video yoki fayl havolasi (o'quvchi kabinetida ko'rinadi)
    material_url = db.Column(db.String(500), default="")
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    cohort      = db.relationship("Cohort", backref="assignments")


class Submission(db.Model):
    """Topshiriq — AI birinchi bahoni taklif qiladi, kurator tasdiqlaydi."""
    __tablename__ = "submissions"
    __table_args__ = (
        db.UniqueConstraint("assignment_id", "contract_id",
                            name="uq_sub_assignment_contract"),
    )
    id            = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"),
                              nullable=False, index=True)
    contract_id   = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                              nullable=False, index=True)
    content       = db.Column(db.Text, default="")
    submitted_at  = db.Column(db.DateTime, default=datetime.utcnow)
    status        = db.Column(db.String(12), default="pending")  # pending/graded
    score         = db.Column(db.Integer)          # yakuniy ball
    feedback      = db.Column(db.Text, default="")
    ai_score      = db.Column(db.Integer)          # AI taklifi
    ai_feedback   = db.Column(db.Text, default="")
    graded_at     = db.Column(db.DateTime)
    assignment    = db.relationship("Assignment", backref="submissions")
    contract      = db.relationship("Contract")


class EduCertificate(db.Model):
    """Sertifikat — /cert/<token> orqali login'siz tekshiriladi (QR)."""
    __tablename__ = "edu_certificates"
    id          = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            unique=True, nullable=False, index=True)
    token       = db.Column(db.String(48), unique=True, index=True,
                            nullable=False)
    serial      = db.Column(db.String(40), unique=True, nullable=False)
    issued_at   = db.Column(db.DateTime, default=datetime.utcnow)
    contract    = db.relationship("Contract",
                                  backref=db.backref("certificate",
                                                     uselist=False))

    @staticmethod
    def issue(contract):
        """Shartnoma uchun sertifikat (bor bo'lsa o'shani qaytaradi)."""
        import secrets as _secrets
        cert = EduCertificate.query.filter_by(contract_id=contract.id).first()
        if cert:
            return cert
        n = (EduCertificate.query.count() or 0) + 1
        cert = EduCertificate(
            contract_id=contract.id,
            token=_secrets.token_urlsafe(24),
            serial=f"MF-{datetime.utcnow().year}-{n:05d}")
        db.session.add(cert)
        return cert

# ══════════════════════════════════════════════════════════════════
#  TO'LOV TAQVIMI (платежный календарь) — kunlik xarajat rejasi
# ══════════════════════════════════════════════════════════════════
# Guruhlar Sheets'dagi «Ежедневный календарь расходов» tartibida, lekin
# qatorlar kassa ishlatadigan statyalarning o'zi — shunda FAKT ustuni
# hech qanday qo'lda ko'chirishsiz, to'g'ridan-to'g'ri kassadan olinadi.
CAL_GROUPS = [
    ("Xodimlar mehnati", ["Зарплата МБМ", "Зарплата СМК", "Зарплата РОП",
                          "Зарплата ТББ", "Премия", "Налог/дивиденд Зп"]),
    ("Korporativ xarajatlar", ["Обед сотрудников", "Корпоративный расход",
                               "Хайрия"]),
    ("O'quv jarayoni", ["Кофе-брейк", "Закуп хоз. товаров",
                        "Выпускные расходы"]),
    ("Mijoz jalb qilish", ["Таргет (реклама)", "CRM OnlinePBX"]),
    ("Ma'muriy xarajatlar", ["Аренда", "Коммунальные услуги", "Ремонт",
                             "Интернет/IP-телефония", "Абонентские подписки",
                             "Такси", "Комиссия банка"]),
    ("Moliyaviy", ["Дивиденды", "Расход — долг"]),
    ("Qaytarish va boshqalar", ["Возврат клиенту", "Прочие расходы"]),
]


class PlanCell(db.Model):
    """Taqvimning bitta katagi: shu kunga shu statya bo'yicha reja summasi."""
    __tablename__ = "plan_cells"
    id       = db.Column(db.Integer, primary_key=True)
    year     = db.Column(db.Integer, nullable=False, index=True)
    month    = db.Column(db.Integer, nullable=False, index=True)
    day      = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount   = db.Column(db.Float, default=0.0)
    __table_args__ = (db.UniqueConstraint("year", "month", "day", "category",
                                          name="uq_plan_cell"),)


# ══════════════════════════════════════════════════════════════════
#  VIDEO DARSLIKLAR — o'quvchi ilovasi uchun kontent qatlami
# ══════════════════════════════════════════════════════════════════
# Muhim qaror: videoni O'ZIMIZ saqlamaymiz. Fayl hosting va trafik qimmat
# turadi, buning o'rniga havola (YouTube unlisted / Vimeo / Drive) qo'yiladi
# va ilova ichida o'rnatilgan pleyerda ochiladi. Shunda kontent egasi biz
# bo'lamiz, xarajat esa nolga yaqin.

class VideoModule(db.Model):
    """Kurs moduli — video darslar shu ichida guruhlanadi."""
    __tablename__ = "video_modules"
    id        = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"),
                          nullable=False, index=True)
    title     = db.Column(db.String(200), nullable=False)
    subtitle  = db.Column(db.String(300), default="")
    sort      = db.Column(db.Integer, default=0)
    course    = db.relationship("Course", backref="modules")
    lessons   = db.relationship("VideoLesson", backref="module",
                                order_by="VideoLesson.sort",
                                cascade="all, delete-orphan")


class VideoLesson(db.Model):
    """Bitta video dars: havola + tavsif + davomiyligi."""
    __tablename__ = "video_lessons"
    id        = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("video_modules.id"),
                          nullable=False, index=True)
    title     = db.Column(db.String(200), nullable=False)
    video_url = db.Column(db.String(500), default="")
    body      = db.Column(db.Text, default="")        # matnli konspekt
    file_url  = db.Column(db.String(500), default="")  # qo'shimcha material
    minutes   = db.Column(db.Integer, default=0)
    sort      = db.Column(db.Integer, default=0)
    is_free   = db.Column(db.Boolean, default=False)   # tanishuv darsi
    # Bosqichma-bosqich ochilish: oqim boshlanganidan necha kun keyin
    # ochiladi. 0 — birinchi kundanoq ochiq.
    open_day  = db.Column(db.Integer, default=0)


class LessonView(db.Model):
    """O'quvchi qaysi darsni ko'rib bo'lgani (progress uchun)."""
    __tablename__ = "lesson_views"
    __table_args__ = (db.UniqueConstraint("lesson_id", "contract_id",
                                          name="uq_lesson_view"),)
    id          = db.Column(db.Integer, primary_key=True)
    lesson_id   = db.Column(db.Integer, db.ForeignKey("video_lessons.id"),
                            nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            nullable=False, index=True)
    done        = db.Column(db.Boolean, default=True)
    viewed_at   = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════
#  VIDEO KO'RISH ANALITIKASI
# ══════════════════════════════════════════════════════════════════
# Video boshqa saytda tursa ham, u bizning sahifamiz ichida ochiladi —
# demak pleyerning JS API'si «hozir nechinchi soniyada» deb ayta oladi.
# Ilova har 15 soniyada ko'rilgan ORALIQLARNI yuboradi, biz ularni
# birlashtirib saqlaymiz. Oxirgi nuqtani emas, aynan oraliqlarni:
# aks holda o'quvchi tugmani oxiriga sudrasa 100% bo'lib qolardi.

class LessonWatch(db.Model):
    __tablename__ = "lesson_watch"
    # Noyoblik ELEMENT bo'yicha: bitta darsda bir nechta video bo'lishi mumkin
    __table_args__ = (db.UniqueConstraint("item_id", "contract_id",
                                          name="uq_lesson_watch_item"),)
    id          = db.Column(db.Integer, primary_key=True)
    lesson_id   = db.Column(db.Integer, db.ForeignKey("video_lessons.id"),
                            nullable=False, index=True)
    item_id     = db.Column(db.Integer, db.ForeignKey("lesson_items.id"),
                            index=True)          # qaysi video elementi
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            nullable=False, index=True)
    duration    = db.Column(db.Float, default=0.0)   # video uzunligi, soniya
    covered     = db.Column(db.Text, default="[]")   # JSON: [[a,b], ...]
    seconds     = db.Column(db.Float, default=0.0)   # oraliqlar yig'indisi
    pct         = db.Column(db.Float, default=0.0)   # foiz
    max_pos     = db.Column(db.Float, default=0.0)   # eng uzoq borgan nuqta
    opens       = db.Column(db.Integer, default=0)   # necha marta ochgan
    first_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_at     = db.Column(db.DateTime, default=datetime.utcnow)
    lesson      = db.relationship("VideoLesson")
    contract    = db.relationship("Contract")


# ══════════════════════════════════════════════════════════════════
#  TESTLAR (avtomatik tekshiriladigan)
# ══════════════════════════════════════════════════════════════════
class Quiz(db.Model):
    """Darsga biriktirilgan test."""
    __tablename__ = "quizzes"
    id         = db.Column(db.Integer, primary_key=True)
    lesson_id  = db.Column(db.Integer, db.ForeignKey("video_lessons.id"),
                           nullable=False, index=True)
    item_id    = db.Column(db.Integer, db.ForeignKey("lesson_items.id"),
                           index=True)          # qaysi element sifatida turadi
    title      = db.Column(db.String(200), default="Nazorat testi")
    pass_score = db.Column(db.Integer, default=70)   # o'tish uchun kerak, %
    lesson     = db.relationship("VideoLesson", backref=db.backref(
        "quiz", uselist=False, cascade="all, delete-orphan"))
    item       = db.relationship("LessonItem", backref=db.backref(
        "quiz", uselist=False))
    questions  = db.relationship("QuizQuestion", backref="quiz",
                                 order_by="QuizQuestion.sort",
                                 cascade="all, delete-orphan")


class QuizQuestion(db.Model):
    __tablename__ = "quiz_questions"
    id      = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"),
                        nullable=False, index=True)
    text    = db.Column(db.String(500), nullable=False)
    sort    = db.Column(db.Integer, default=0)
    options = db.relationship("QuizOption", backref="question",
                              order_by="QuizOption.id",
                              cascade="all, delete-orphan")


class QuizOption(db.Model):
    __tablename__ = "quiz_options"
    id          = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("quiz_questions.id"),
                            nullable=False, index=True)
    text        = db.Column(db.String(300), nullable=False)
    is_correct  = db.Column(db.Boolean, default=False)


class QuizAttempt(db.Model):
    """Har urinish alohida saqlanadi — kurator dinamikani ko'ra oladi."""
    __tablename__ = "quiz_attempts"
    id          = db.Column(db.Integer, primary_key=True)
    quiz_id     = db.Column(db.Integer, db.ForeignKey("quizzes.id"),
                            nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            nullable=False, index=True)
    score       = db.Column(db.Integer, default=0)     # foiz
    passed      = db.Column(db.Boolean, default=False)
    answers     = db.Column(db.Text, default="{}")     # JSON: {savol: variant}
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    contract    = db.relationship("Contract")
    quiz        = db.relationship("Quiz")


# ══════════════════════════════════════════════════════════════════
#  TELEGRAM XABARNOMA
# ══════════════════════════════════════════════════════════════════
class TgMessage(db.Model):
    """Yuborilgan xabar tarixi — bir xil eslatma ikki marta ketmasin."""
    __tablename__ = "tg_messages"
    id          = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"),
                            index=True)
    kind        = db.Column(db.String(20), default="")   # qarz/dars/vazifa
    dedup_key   = db.Column(db.String(120), index=True)  # kun bo'yicha kalit
    text        = db.Column(db.Text, default="")
    ok          = db.Column(db.Boolean, default=False)
    error       = db.Column(db.String(300), default="")
    sent_at     = db.Column(db.DateTime, default=datetime.utcnow)
    contract    = db.relationship("Contract")


# ══════════════════════════════════════════════════════════════════
#  DARS ELEMENTLARI
# ══════════════════════════════════════════════════════════════════
# Ilgari dars qat'iy edi: bitta video + bitta matn + bitta fayl + bitta
# test, tartibi ham o'zgarmasdi. Jiddiy platformalarda (Coursera, Udemy,
# Stepik) dars — ELEMENTLAR KETMA-KETLIGI: kurator xohlagan tartibda
# video, matn, fayl va testni terib chiqadi.
#
# VideoLesson endi idish rolini o'ynaydi (nom, modul, tartib, ochilish
# kuni). Ichidagi mazmun — shu jadvalda.

ITEM_KINDS = {
    "video": "Video",
    "matn":  "Matn",
    "fayl":  "Material",
    "test":  "Test",
}


class LessonItem(db.Model):
    __tablename__ = "lesson_items"
    id        = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("video_lessons.id"),
                          nullable=False, index=True)
    kind      = db.Column(db.String(10), nullable=False, default="video")
    sort      = db.Column(db.Integer, default=0)
    title     = db.Column(db.String(200), default="")
    url       = db.Column(db.String(500), default="")   # video yoki fayl
    body      = db.Column(db.Text, default="")          # matn
    minutes   = db.Column(db.Integer, default=0)        # video davomiyligi
    lesson    = db.relationship("VideoLesson", backref=db.backref(
        "items", order_by="LessonItem.sort, LessonItem.id",
        cascade="all, delete-orphan"))

    @property
    def label(self):
        return self.title or ITEM_KINDS.get(self.kind, self.kind)
