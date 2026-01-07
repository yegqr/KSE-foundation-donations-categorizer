import streamlit as st
import pandas as pd
from datetime import datetime, time
import io

# --- CONFIG ---
st.set_page_config(page_title="Donor Analytics System 2.0", page_icon="🚀", layout="wide")
st.title("🚀 Donor Analytics System 2.0")
st.markdown("Система повного циклу: **Мердж історії** -> **Фільтр по датах** -> **Аналіз**")

# --- CORE LOGIC ---

def parse_dates(series):
    return pd.to_datetime(series, format='mixed', errors='coerce')

def normalize_donorbox(df):
    """Приводить файл Donorbox до стандарту"""
    # Мапінг колонок на основі твого файлу all-donorb.csv
    rename_map = {
        'Donated At': 'date',
        'Donor Email': 'email',
        'Donor\'s First Name': 'first_name',
        'Donor\'s Last Name': 'last_name',
        'UTM Source': 'tag',
        'Donation Type': 'type'
    }
    
    # Пріоритет вибору суми (Converted > USD > Amount)
    if 'Converted Amount' in df.columns:
        rename_map['Converted Amount'] = 'amount'
    elif 'Amount in USD' in df.columns:
        rename_map['Amount in USD'] = 'amount'
    else:
        rename_map['Amount'] = 'amount'

    df = df.rename(columns=rename_map)
    
    # Якщо якоїсь колонки немає - створюємо пусту
    if 'tag' not in df.columns: df['tag'] = ''
    
    # Стандартизація
    df['source_system'] = 'Donorbox'
    df['full_name'] = (df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')).str.strip()
    
    # Повертаємо тільки потрібні колонки
    cols_to_keep = ['date', 'email', 'full_name', 'amount', 'tag', 'source_system']
    # Фільтруємо ті, що реально є (щоб не падало, якщо формат трохи зміниться)
    available_cols = [c for c in cols_to_keep if c in df.columns]
    return df[available_cols]

def normalize_funraise(df):
    """Приводить файл Funraise (FU) до стандарту"""
    # Мапінг колонок на основі твого файлу all-fu.csv
    rename_map = {
        'Donation Date': 'date',
        'Supporter Email': 'email',
        'Converted Donation Amount': 'amount',
        'Supporter First Name': 'first_name',
        'Supporter Last Name': 'last_name',
        'UTM Campaign Source': 'tag'
    }
    
    df = df.rename(columns=rename_map)
    
    if 'tag' not in df.columns: df['tag'] = ''
    
    df['source_system'] = 'Funraise'
    df['full_name'] = (df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')).str.strip()
    
    cols_to_keep = ['date', 'email', 'full_name', 'amount', 'tag', 'source_system']
    available_cols = [c for c in cols_to_keep if c in df.columns]
    return df[available_cols]

def categorize_donor(row):
    is_new = row['is_new']
    amount = row['amount']
    if is_new:
        return "1. New (<500)" if amount < 500 else "2. New (500+)"
    else:
        return "3. Repeated (<500)" if amount < 500 else "4. Repeated (500+)"

# --- UI & EXECUTION ---

col_u1, col_u2 = st.columns(2)
with col_u1:
    file_db = st.file_uploader("📂 Завантаж All-Time DONORBOX", type=['csv'])
with col_u2:
    file_fu = st.file_uploader("📂 Завантаж All-Time FUNRAISE (FU)", type=['csv'])

st.markdown("---")
st.subheader("📅 Налаштування періоду звіту")

col_d1, col_d2 = st.columns(2)
with col_d1:
    # За замовчуванням ставимо початок поточного місяця
    default_start = datetime.today().replace(day=1)
    start_date = st.date_input("ВІД (Дата початку аналізу)", value=default_start)
with col_d2:
    end_date = st.date_input("ДО (Дата кінця аналізу)", value=datetime.now())

# Кнопка запуску
if st.button("🚀 ЗМЕРДЖИТИ І ПРОАНАЛІЗУВАТИ", type="primary"):
    if not file_db or not file_fu:
        st.error("❌ Потрібно завантажити ОБИДВА файли з повною історією!")
    else:
        with st.spinner('Магія відбувається: чистимо, зшиваємо, рахуємо історію...'):
            try:
                # 1. Читання
                raw_db = pd.read_csv(file_db)
                raw_fu = pd.read_csv(file_fu)
                
                # 2. Нормалізація
                df_db = normalize_donorbox(raw_db)
                df_fu = normalize_funraise(raw_fu)
                
                # 3. Мердж в "Майстер-лог"
                master_log = pd.concat([df_db, df_fu], ignore_index=True)
                
                # Типізація даних
                master_log['date'] = parse_dates(master_log['date'])
                master_log['email'] = master_log['email'].astype(str).str.lower().str.strip()
                master_log['amount'] = pd.to_numeric(master_log['amount'], errors='coerce').fillna(0)
                
                # Сортування
                master_log = master_log.sort_values('date')
                
                total_rows = len(master_log)
                
            except Exception as e:
                st.error(f"Помилка обробки файлів: {e}")
                st.stop()

        st.success(f"✅ Успішно оброблено {total_rows} транзакцій за весь час.")

        # --- ГОЛОВНА ЛОГІКА (Машина часу) ---
        
        # Конвертуємо дати з UI в timestamp
        # start_date -> 00:00:00
        start_ts = pd.Timestamp(datetime.combine(start_date, time.min))
        # end_date -> 23:59:59
        end_ts = pd.Timestamp(datetime.combine(end_date, time.max))

        # 4. Визначаємо "Базу Supporters" (історію ДО початку періоду)
        # Всі унікальні емейли, які донатили раніше
        history_before = master_log[master_log['date'] < start_ts]
        existing_donors_set = set(history_before['email'].unique())
        
        st.info(f"📚 На момент {start_date} у базі знайдено {len(existing_donors_set)} існуючих донорів (Supporters).")

        # 5. Визначаємо "Робочий звіт" (Транзакції В ПЕРІОДІ)
        current_batch = master_log[
            (master_log['date'] >= start_ts) & 
            (master_log['date'] <= end_ts)
        ].copy()
        
        if current_batch.empty:
            st.warning("⚠️ У вибраному діапазоні дат немає транзакцій.")
        else:
            # 6. Визначаємо статуси (New vs Repeated)
            # Логіка: Якщо email немає в existing_donors_set -> New. Інакше -> Repeated.
            current_batch['is_new'] = ~current_batch['email'].isin(existing_donors_set)
            
            # Категоризація по грошах
            current_batch['category'] = current_batch.apply(categorize_donor, axis=1)
            
            # 7. Рахуємо частоту В МЕЖАХ ПЕРІОДУ (для KPI "2+ донатів")
            batch_counts = current_batch['email'].value_counts().to_dict()
            current_batch['transactions_in_period'] = current_batch['email'].map(batch_counts)

            # --- СТАТИСТИКА (KPI) ---
            
            # Групуємо по унікальних людях
            unique_people = current_batch.groupby('email').agg({
                'is_new': 'first',
                'amount': 'max', # Максимальний донат визначає категорію
                'transactions_in_period': 'first',
                'full_name': 'first'
            }).reset_index()

            # Категорія для людини
            def get_unique_cat(row):
                if row['is_new']:
                    return "1. New (<500)" if row['amount'] < 500 else "2. New (500+)"
                else:
                    return "3. Repeated (<500)" if row['amount'] < 500 else "4. Repeated (500+)"
            
            unique_people['unique_category'] = unique_people.apply(get_unique_cat, axis=1)

            # Розрахунок метрик
            total_u = len(unique_people)
            one_time = len(unique_people[unique_people['transactions_in_period'] == 1])
            multi = len(unique_people[unique_people['transactions_in_period'] > 1])
            
            st.markdown("---")
            st.subheader(f"📊 Результат за період: {start_date} — {end_date}")
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Унікальних донорів", total_u, help="Кількість унікальних людей у звіті")
            k2.metric("1 донат за період", one_time, help="Люди, які зробили лише 1 транзакцію за цей час")
            k3.metric("2+ донатів за період", multi, help="Люди, які зробили 2 або більше транзакцій за цей час (ваші герої)")
            
            # Графік
            chart_data = unique_people['unique_category'].value_counts().sort_index()
            st.bar_chart(chart_data)

            # --- ЕКСПОРТ ---
            st.markdown("### 📥 Отримати файл")
            
            # Формуємо красиву табличку на вихід
            export_df = current_batch[[
                'date', 'full_name', 'email', 'amount', 'category', 'is_new', 
                'tag', 'source_system', 'transactions_in_period'
            ]].sort_values('date', ascending=False)
            
            export_df.columns = [
                'Date', 'Name', 'Email', 'Amount', 'Category', 'Is New?', 
                'Tag', 'Source', 'Tx Count (Period)'
            ]
            
            csv = export_df.to_csv(index=False).encode('utf-8')
            fname = f"Report_{start_date}_{end_date}.csv"
            
            st.download_button(
                label="📥 Скачати CSV звіт",
                data=csv,
                file_name=fname,
                mime='text/csv',
                type='primary'
            )
            
            with st.expander("🔍 Переглянути деталі (Preview)"):
                st.dataframe(export_df.head(100))
