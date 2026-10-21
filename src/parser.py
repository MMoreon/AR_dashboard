import os
import sqlite3
from datetime import datetime
import openpyxl

def clean_float(value):
    if value is None or str(value).strip() in ['', '-']:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def clean_int(value):
    if value is None or str(value).strip() in ['', '-']:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return 0

def format_date(d):
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, str) and d.strip():
        try:
            return datetime.strptime(d.strip(), '%d.%m.%Y').date().isoformat()
        except ValueError:
            return None
    return None

def parse_1c_xlsx(file_path, department_name, snapshot_date, db_path='debts.db'):
    if not os.path.exists(file_path):
        print(f"Ошибка: Файл {file_path} не найден.")
        return

    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb.active

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customer_debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date DATE NOT NULL,
            organization TEXT NOT NULL,
            sales_dept TEXT NOT NULL,
            department TEXT NOT NULL,
            team TEXT,
            manager TEXT,
            client TEXT NOT NULL,
            contract TEXT,
            document TEXT,
            creation_date DATE,
            plan_payment_date DATE,
            days_to_payment INTEGER,
            amount_realization REAL DEFAULT 0,
            debt_total REAL DEFAULT 0,
            debt_overdue REAL DEFAULT 0,
            days_overdue INTEGER DEFAULT 0,
            our_debt REAL DEFAULT 0
        );
    ''')
    
    # Исходный контекст по умолчанию
    current_org = "ООО ТД Монолит Р"
    current_sales_dept = "ОТДЕЛ ПРОДАЖ"
    current_team = "Без команды"
    current_manager = "Без менеджера"
    current_client = "Неизвестный контрагент"
    current_contract = "Без договора"
    
    start_parsing = False
    records_count = 0

    for row in sheet.iter_rows(values_only=False):
        if not row:
            continue
            
        cell_a = row[0]  
        val_a = cell_a.value

        if val_a is None:
            continue

        val_a_str = str(val_a).strip()
        val_lower = val_a_str.lower()

        # Точка старта парсинга
        if "ооо \"тд \"монолит р\"" in val_lower and not start_parsing:
            start_parsing = True
        
        if not start_parsing:
            continue
            
        if any(x in val_lower for x in ["итого", "задолженность клиентов по срокам", "параметры:", "отбор:"]):
            continue

        # Маркеры типов данных на основе контента (100% стабильность в 1С)
        is_document = any(x in val_lower for x in [
            "реализация товаров", "поступление безналичных", 
            "корректировка задолженности", "возврат товаров", 
            "приходный кассовый", "корректировка реализации", 
            "эквайринговая операция", "взаимозачет"
        ])
        is_contract = any(x in val_lower for x in ["договор", "доп согл", "договр"]) and not is_document
        is_client = any(x in val_lower for x in [
            "ооо", "ип", "ао", "физлицо", "физ.лицо", "физ лицо", 
            "потребительское общество", "райпо", "сельпо", "нотариус", "кфх"
        ]) and not is_contract and not is_document
        
        clean_val = val_a_str.strip('"')

        # Определение ролей методом исключения и накопления контекста
        if "ооо \"тд \"монолит р\"" in val_lower:
            current_org = clean_val
        elif "отдел продаж" in val_lower:
            current_sales_dept = clean_val
        elif "команда" in val_lower:
            current_team = clean_val
            current_manager = "Без менеджера"  # Сброс контекста вниз
        elif is_client:
            current_client = clean_val
            current_contract = "Без договора"
        elif is_contract:
            current_contract = clean_val
        elif not is_document and len(clean_val.split()) >= 2:
            # Если это не клиент, не договор, не команда, но содержит минимум 2 слова (ФИО) — это Менеджер!
            if not any(x in val_lower for x in ["отдел", "организация", "состояние", "сумма"]):
                current_manager = clean_val

        # Запись документа реализации в БД
        if is_document:
            document = clean_val
            
            creation_date = row[4].value if len(row) > 4 else None
            plan_date = row[6].value if len(row) > 6 else None
            days_to_payment = clean_int(row[7].value) if len(row) > 7 else 0
            
            amount_realization = clean_float(row[8].value) if len(row) > 8 else 0.0
            debt_total = clean_float(row[9].value) if len(row) > 9 else 0.0
            debt_overdue = clean_float(row[11].value) if len(row) > 11 else 0.0
            days_overdue = clean_int(row[12].value) if len(row) > 12 else 0
            our_debt = clean_float(row[13].value) if len(row) > 13 else 0.0

            cursor.execute('''
                INSERT INTO customer_debts (
                    snapshot_date, organization, sales_dept, department, team, 
                    manager, client, contract, document, creation_date, 
                    plan_payment_date, days_to_payment, amount_realization, 
                    debt_total, debt_overdue, days_overdue, our_debt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot_date, current_org, current_sales_dept, department_name, current_team,
                current_manager, current_client, current_contract, document,
                format_date(creation_date), format_date(plan_date), days_to_payment,
                amount_realization, debt_total, debt_overdue, days_overdue, our_debt
            ))
            records_count += 1

    conn.commit()
    conn.close()
    wb.close()
    print(f"Успешно обработан отдел '{department_name}': добавлено {records_count} документов.")

if __name__ == '__main__':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(BASE_DIR, '..', 'debts.db')
    DIST_FILE = os.path.join(BASE_DIR, '..', 'data', 'distribution.xlsx')
    MATCH_FILE = os.path.join(BASE_DIR, '..', 'data', 'matching.xlsx')
    
    SNAPSHOT = '2026-07-08'
    
    if os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('DROP TABLE IF EXISTS customer_debts;')
            conn.commit()
            conn.close()
            print("Старая таблица успешно сброшена.")
        except sqlite3.OperationalError:
            print("БД заблокирована, пишем поверх...")
        
    print("Запуск парсинга оригинальных XLSX файлов...")
    parse_1c_xlsx(DIST_FILE, 'Дистрибьюция', SNAPSHOT, DB_NAME)
    parse_1c_xlsx(MATCH_FILE, 'Комплектация', SNAPSHOT, DB_NAME)
    print("Парсинг успешно завершен!")
