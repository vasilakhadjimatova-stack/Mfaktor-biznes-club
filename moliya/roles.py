"""
Rollar va ruxsatlar.

Uch rol bor. Har biriga alohida kirish kodi beriladi, shunda kuratorga
o'quv bo'limi uchun kod berganda u kompaniya kassasini ko'rmaydi.

  direktor  — hamma narsa
  buxgalter — moliya (kassa, ДДС, taqvim, hisobot, shartnoma to'lovlari)
  kurator   — o'quv bo'limi + o'quvchilarning to'lov holati

Ruxsat marshrut manzili bo'yicha emas, ENDPOINT nomi bo'yicha beriladi:
manzil o'zgarsa ham ruxsat joyida qoladi. Direktordan boshqa rollar uchun
ro'yxat OCHIQ sanab chiqilgan — yangi sahifa qo'shilsa, u avtomatik faqat
direktorga ochiq bo'ladi. Ya'ni xato tomon — qulflash tomoni.
"""
import hashlib
import hmac
import os
import secrets

DIREKTOR = "direktor"
BUXGALTER = "buxgalter"
KURATOR = "kurator"

ROLE_LABELS = {
    DIREKTOR: "Direktor",
    BUXGALTER: "Buxgalter",
    KURATOR: "Kurator",
}
ROLE_HINTS = {
    DIREKTOR: "Hamma bo'lim: moliya, o'quv, KPI, sozlamalar",
    BUXGALTER: "Kassa, ДДС, to'lov taqvimi, hisobot, shartnoma to'lovlari. "
               "KPI va sozlamalarni ko'rmaydi",
    KURATOR: "O'quv bo'limi, oqimlar, o'quvchilar va ularning qarzi. "
             "Kassa va hisobotlarni ko'rmaydi",
}
ROLES = (DIREKTOR, BUXGALTER, KURATOR)

# Kodsiz ochiladigan endpoint'lar (o'quvchi ilovasi, sertifikat, tizim)
PUBLIC = {
    "login", "logout", "healthz", "sw", "static", "cert_verify",
    "kabinet", "kabinet_submit",
    "app_home", "app_lessons", "app_lesson", "app_lesson_done",
    "app_tasks", "app_rank", "app_manifest",
}

# Moliya — buxgalter va direktor
_FINANCE = {
    "dashboard",
    "transactions", "add_transaction", "delete_transaction",
    "transactions_export",
    "automation_page", "book_recurring", "close_day", "mark_reminded",
    "payments_inbox", "inbox_link", "inbox_new_contract", "inbox_rerun",
    "inbox_restore", "inbox_skip", "inbox_unlink",
    "ddsdata", "ddsdata_add", "ddsdata_delete", "ddsdata_edit",
    "ddsdata_export", "ddsdata_rebuild", "dds",
    "taqvim", "taqvim_set", "taqvim_fill", "taqvim_copy", "taqvim_clear",
    "reports", "launch_planner", "add_budget",
    "add_contract", "contract_pay",
}

# O'quv bo'limining o'z sahifalari — bo'lim o'chirilsa bular yo'qoladi
_EDU_ROUTES = {
    "oquv", "oquv_cohort", "oquv_assignment", "oquv_assignment_add",
    "oquv_attendance", "oquv_certificate", "oquv_grade", "oquv_submit",
    "oquv_portal_link", "oquv_portal_links", "oquv_refresh_risk",
    "oquv_schedule", "oquv_session_add",
    "oquv_content", "oquv_module_add", "oquv_module_del", "oquv_module_edit",
    "oquv_module_move", "oquv_lesson_add", "oquv_lesson_del",
    "oquv_lesson_edit", "oquv_lesson_move",
    "oquv_item_add", "oquv_item_edit", "oquv_item_move",
    "oquv_item_del", "oquv_item_stats",
    # ko'rish analitikasi, testlar, xabarnoma
        "oquv_quiz_save", "oquv_quiz_del",
    "oquv_quiz_question_add", "oquv_quiz_question_del",
    "oquv_notify", "oquv_notify_send", "oquv_tg_link",
}

# Kuratorga ochiq: o'z sahifalari + shartnoma holatini o'zgartirish
# («contract_status» moliya tomonida ham kerak — u bo'lim bilan o'chmaydi)
_EDU = _EDU_ROUTES | {"contract_status"}

# O'quvchi ilovasi va sertifikat — o'quv bo'limi bilan birga yoqiladi
_EDU_PUBLIC = {
    "cert_verify", "kabinet", "kabinet_submit",
    "app_home", "app_lessons", "app_lesson", "app_lesson_done",
    "app_tasks", "app_rank", "app_manifest",
    "app_item_beat", "app_quiz_submit", "tg_webhook",
}

# Ikkalasiga ham kerak: o'quvchi ro'yxati va kim qarzdorligi
_SHARED = {"contracts", "contract_detail", "debtors", "cohorts", "add_cohort"}

ALLOWED = {
    BUXGALTER: _FINANCE | _SHARED,
    KURATOR: _EDU | _SHARED,
}

def home_for(role):
    """Kirgandan keyin qaysi sahifa ochiladi."""
    if role == KURATOR:
        return "/oquv" if edu_enabled() else "/contracts"
    return "/"


def edu_enabled():
    """O'quv bo'limi shu nusxada yoqilganmi.

    Railway'dagi ochiq nusxada faqat MOLIYA turadi. O'quv bo'limi va
    o'quvchi ilovasi offline (lokal) nusxada ishlaydi — uni yoqish uchun
    ishga tushirishda OQUV_BOLIMI=1 berish kerak:

        OQUV_BOLIMI=1 python3 app.py

    O'zgaruvchi berilmasa bo'lim butunlay o'chiq: marshrutlari ham
    ro'yxatdan o'tmaydi, menyuda ham ko'rinmaydi.
    """
    return os.environ.get("OQUV_BOLIMI", "").strip().lower() in (
        "1", "on", "true", "ha")


def can(role, endpoint):
    """Shu rol shu endpoint'ni ocha oladimi."""
    if not endpoint:
        return False
    if not edu_enabled() and (endpoint in _EDU_ROUTES
                              or endpoint in _EDU_PUBLIC):
        return False               # bo'lim bu nusxada umuman yo'q
    if endpoint in PUBLIC:
        return True
    if role == DIREKTOR:
        return True
    return endpoint in ALLOWED.get(role, ())


def sees_cash(role):
    """Yuqori paneldagi «Jami pul» shu rolga ko'rinadimi."""
    return role in (DIREKTOR, BUXGALTER)


# ── Kirish kodini saqlash ─────────────────────────────────────────
# Kod ochiq holda saqlanmaydi: PBKDF2 bilan tuzlanib xeshlanadi.
_ITERS = 200_000


def hash_pin(pin):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERS)
    return f"pbkdf2${_ITERS}${salt.hex()}${dk.hex()}"


def verify_pin(pin, stored):
    """Kod saqlangan xeshga mos keladimi (vaqt bo'yicha bir xil solishtirish)."""
    try:
        algo, iters, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (AttributeError, ValueError):
        return False


def app_pin():
    """Direktorning kodi — muhit o'zgaruvchisidan. Bo'sh bo'lsa qulf o'chiq."""
    return os.environ.get("APP_PIN", "").strip()


def stored_pin(role):
    """Rol uchun bazada saqlangan kod xeshi (yo'q bo'lsa bo'sh satr)."""
    from database import db
    from models import AppSetting
    try:
        row = db.session.get(AppSetting, f"pin_{role}")
    except Exception:                                  # noqa: BLE001
        db.session.rollback()
        return ""
    return (row.value or "") if row else ""


def match_role(pin):
    """Kiritilgan kod qaysi rolga tegishli (mos kelmasa None)."""
    if not pin:
        return None
    env = app_pin()
    # APP_PIN — direktorning kodi; eski deploy shu bilan ishlashda davom etadi
    if env and hmac.compare_digest(pin, env):
        return DIREKTOR
    for role in ROLES:
        stored = stored_pin(role)
        if stored and verify_pin(pin, stored):
            return role
    return None


def role_stamp(role):
    """Rol kodining barmoq izi.

    Kod almashtirilsa iz o'zgaradi — shu bilan o'sha roldagi ochiq
    sessiyalar uziladi. Kodning o'zi emas, uning xeshi asos qilinadi.
    """
    base = app_pin() if role == DIREKTOR else stored_pin(role)
    if not base:
        return ""
    return hashlib.sha256(f"{role}:{base}".encode()).hexdigest()[:16]
