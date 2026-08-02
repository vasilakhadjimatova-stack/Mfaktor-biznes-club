"""
Mfaktor ДДС Google Sheets → Mfaktor Moliya importeri.

Foydalanish:
  1. Google Sheets'da: Файл → Скачать → Microsoft Excel (.xlsx)
  2. python import_dds.py /yol/dds.xlsx [--year 2026] [--wipe]

Jadval formati (skrinshotdagi kabi):
  • Bir ustunda qator nomlari («Наименование»), keyin 12 oy ustuni
  • «Остаток ДС на начало периода» ostida hamyon qatorlari
  • «Поступления...» ostida kirim statyalari
  • «Выбытия...» ostida chiqim statyalari

Import natijasi:
  • Har (statya, oy) → bitta jamlama Transaction (oyning 15-sanasi,
    "sheets" virtual hamyoni)
  • Hamyonlar birinchi oy qoldiqlaridan ochiladi
  • --wipe: eski import yozuvlarini o'chirib qayta yuklaydi
"""
import sys
import unicodedata
from datetime import date

from openpyxl import load_workbook

from app import create_app
from database import db
from models import EXPENSE_CATS, INCOME_CATS, Transaction, Wallet

IMPORT_WALLET = ("sheets", "Sheets import (jamlama)")

# Sheets'dagi qator nomi → dastur statyasi (kichik harf, moslashuvchan)
ROW_MAP = {
    "поступление от клиента роп": "Поступление от клиента РОП",
    "поступление от клиента смк": "Поступление от клиента СМК",
    "поступление от клиента твв": "Поступление от клиента ТВВ",
    "поступление б2б": "Поступление Б2Б",
    "мфактор поступления": "Мфактор поступления",
    "доход — долг": "Доход — долг",
    "доход - долг": "Доход — долг",
    "возврат поступлений клиент": "Возврат клиенту",
    "зарплата": "Зарплата МФМ",
    "зарплата смк": "Зарплата СМК",
    "зарплата роп": "Зарплата РОП",
    "зарплата твв": "Зарплата ТВВ",
    "зарплата тбб": "Зарплата ТВВ",
    "премия": "Премия",
    "аренда": "Аренда",
    "налог дивиденд зп": "Налог/дивиденд",
    "налог дивиденд 3п": "Налог/дивиденд",
    "обед сотрудник": "Обед сотрудников",
    "комиссия банк": "Комиссия банка",
    "коммунальные услуги": "Коммунальные услуги",
    "ремонт": "Ремонт",
    "таргет": "Таргет (реклама)",
    "закупхоз товар": "Закуп хоз. товаров",
    "закуп хоз товар": "Закуп хоз. товаров",
    "выпускные расходы": "Выпускные расходы",
    "кофе брейк": "Кофе-брейк",
    "кофе-брейк": "Кофе-брейк",
    "crm online pbx": "CRM OnlinePBX",
    "срм online pbx": "CRM OnlinePBX",
    "такси": "Такси",
    "интернет ip-телефония": "Интернет/IP-телефония",
    "интернет iр-телефония": "Интернет/IP-телефония",
    "абонентские подписки": "Абонентские подписки",
    "хайринг": "Хайринг",
    "корпоративный расход": "Корпоративный расход",
    "прочие расходы": "Прочие расходы",
    "расход — долг": "Расход — долг",
    "расход - долг": "Расход — долг",
}


def norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    return " ".join(s.split())


def match_cat(label):
    n = norm(label)
    if n in ROW_MAP:
        return ROW_MAP[n]
    for key, cat in ROW_MAP.items():  # qisman moslik
        if key and (key in n or n in key) and len(n) > 3:
            return cat
    return None


def find_layout(ws):
    """Sarlavha qatori va oy ustunlarini topadi."""
    for row in ws.iter_rows(min_row=1, max_row=30):
        for cell in row:
            if norm(cell.value).startswith("наименование"):
                label_col = cell.column
                month_cols = []
                for c in ws[cell.row]:
                    v = norm(c.value)
                    for i, pref in enumerate(["янв", "фев", "мар", "апр", "май",
                                              "июн", "июл", "авг", "сен",
                                              "окт", "ноя", "дек"]):
                        if v.startswith(pref):
                            month_cols.append((c.column, i + 1))
                return cell.row, label_col, month_cols
    raise SystemExit("«Наименование» qatori topilmadi — jadval formati boshqacha")


def to_num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def run(path, year, wipe):
    app = create_app()
    with app.app_context():
        wb = load_workbook(path, data_only=True)
        ws = wb.active
        hdr_row, label_col, month_cols = find_layout(ws)
        print(f"Varaq: {ws.title} | sarlavha qatori {hdr_row} | "
              f"{len(month_cols)} oy ustuni")

        if wipe:
            n = Transaction.query.filter_by(wallet_code=IMPORT_WALLET[0]) \
                .delete(synchronize_session=False)
            print(f"Eski import o'chirildi: {n} yozuv")

        if not Wallet.query.filter_by(code=IMPORT_WALLET[0]).first():
            db.session.add(Wallet(code=IMPORT_WALLET[0], name=IMPORT_WALLET[1],
                                  opening=0.0, sort=99))

        section = None   # 'balance' | 'income' | 'expense'
        opening_done = False
        made = skipped = 0
        for r in range(hdr_row + 1, ws.max_row + 1):
            label = ws.cell(row=r, column=label_col).value
            n = norm(label)
            if not n:
                continue
            if n.startswith("остаток дс на начало"):
                section = "balance"
                continue
            if "поступления по операционной" in n:
                section = "income"
                continue
            if "выбытия по операционной" in n:
                section = "expense"
                continue
            if n.startswith(("операционная", "инвестиционная", "финансовая",
                             "остаток дс на конец", "отчет о движении")):
                if n.startswith(("инвестиционная", "финансовая")):
                    section = None
                continue

            if section == "balance" and not opening_done:
                # hamyon qatori: birinchi oy ustuni = ochilish qoldig'i
                first_col = month_cols[0][0] if month_cols else None
                val = to_num(ws.cell(row=r, column=first_col).value) if first_col else 0
                code = norm(label).replace(" ", "_").replace(".", "")[:20] or f"w{r}"
                w = Wallet.query.filter_by(code=code).first()
                if not w:
                    db.session.add(Wallet(code=code, name=str(label).strip(),
                                          opening=val, sort=r))
                    print(f"  Hamyon: {label} → ochilish {val:,.0f}")
                continue

            if section in ("income", "expense"):
                cat = match_cat(label)
                if not cat:
                    if any(to_num(ws.cell(row=r, column=c).value)
                           for c, _ in month_cols):
                        print(f"  ! Notanish statya (o'tkazildi): {label}")
                        skipped += 1
                    continue
                op = "kirim" if cat in INCOME_CATS else "chiqim"
                for col, month in month_cols:
                    val = to_num(ws.cell(row=r, column=col).value)
                    if val <= 0:
                        continue
                    db.session.add(Transaction(
                        tdate=date(year, month, 15),
                        wallet_code=IMPORT_WALLET[0],
                        operation=op, amount=val, category=cat,
                        counterparty="Sheets import",
                        comment=f"ДДС {year} import: {label}"))
                    made += 1

        db.session.commit()
        print(f"Tayyor: {made} jamlama tranzaksiya, {skipped} notanish qator.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    year = date.today().year
    if "--year" in args:
        year = int(args[args.index("--year") + 1])
    run(path, year, wipe="--wipe" in args)
