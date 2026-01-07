import streamlit as st
import pandas as pd
from datetime import datetime
import io

# --- CONFIG ---
st.set_page_config(page_title="Donor Analytics System 2.0", page_icon="🚀", layout="wide")
st.title("🚀 Donor Analytics System 2.0")
st.markdown("Система повного циклу: Мердж баз -> Історичний аналіз -> Звітність")

# --- CORE LOGIC ---

def parse_dates(series):
    return pd.to_datetime(series, format='mixed', errors='coerce')

def normalize_donorbox(df):
    """Приводить файл Donorbox до стандарту"""
    # Renaming map based on your file structure
    rename_map = {
        'Donated At': 'date',
        'Donor Email': 'email',
        'Amount': 'amount', # Using raw Amount, assuming USD or convert later if needed
        'Donor\'s First Name': 'first_name',
        'Donor\'s Last Name': 'last_name',
        'UTM Source': 'tag',
        'Donation Type': 'type'
    }
    # Check if 'Converted Amount' exists, prefer it
    if 'Converted Amount' in df.columns:
        rename_map['Converted Amount'] = 'amount'
    elif 'Amount in USD' in df.columns:
        rename_map['Amount in USD'] = 'amount'

    df = df.rename(columns=rename_map)
    
    # Fill missing tags
    if 'tag' not in df.columns: df['tag'] = ''
    
    # Standardize columns
    df['source_system'] = 'Donorbox'
    df['full_name'] = (df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')).str.strip()
    return df[['date', 'email', 'full_name', 'amount', 'tag', 'source_system']]

def normalize_funraise(df):
    """Приводить файл Funraise (FU) до стандарту"""
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
    
    # Handle potential missing columns if file format varies
    required = ['date', 'email', 'full_name', 'amount', 'tag', 'source_system']
    for col in required:
        if col not in df.columns:
            df[col] = '' if col != 'amount' else 0
            
    return df[required]

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

# Date Selection
st.markdown("### 📅 Обери період для аналізу")
col_d1, col_d2 = st.columns(2)
with col_d1:
    start_date = st.date_input("ВІД (Дата початку звіту)", value=datetime(2025, 12, 1))
with col_d2:
    end_date = st.date_input("ДО (Дата кінця звіту)", value=datetime.now())

# Convert inputs to datetime for comparison
start_ts = pd.Timestamp(start_date)
end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) # Include full end day

if st.button("🚀 ЗМЕРДЖИТИ І ПРОАНАЛІЗУВАТИ", type="primary"):
    if not file_db or not file_fu:
        st.error("Будь ласка, завантаж обидва файли історії!")
    else:
        with st.spinner('Читаємо, чистимо, зшиваємо...'):
            # 1. Load & Normalize
            try:
                raw_db = pd.read_csv(file_db)
                raw_fu = pd.read_csv(file_fu)
                
                df_db = normalize_donorbox(raw_db)
                df_fu = normalize_funraise(raw_fu)
                
                # 2. Merge Master Log
                master_log = pd.concat([df_db, df_fu], ignore_index=True)
                
                # Clean Data
                master_log['date'] = parse_dates(master_log['date'])
                master_log['email'] = master_log['email'].astype(str).str.lower().str.strip()
                master_log['amount'] = pd.to_numeric(master_log['amount'], errors='coerce').fillna(0)
                
                # Sort by date
                master_log = master_log.sort_values('date')
                
                total_history_rows = len(master_log)
                
            except Exception as e:
                st.error(f"Помилка при обробці файлів: {e}")
                st.stop()

        st.success(f"✅ Успішний мердж! Всього в історії: {total_history_rows} транзакцій.")

        # --- CORE LOGIC: TIME TRAVEL ---
        
        # 3. Визначаємо "Старичків" (Supporters)
        # Це всі унікальні email, які донатили ДО start_date
        history_before_period = master_log[master_log['date'] < start_ts]
        existing_donors = set(history_before_period['email'].unique())
        
        st.info(f"📚 База знань: Знайдено {len(existing_donors)} донорів, які вже донатили до {start_date}")

        # 4. Визначаємо "Робочий батч" (Транзакції за вибраний період)
        current_batch = master_log[
            (master_log['date'] >= start_ts) & 
            (master_log['date'] <= end_ts)
        ].copy()
        
        if current_batch.empty:
            st.warning("У вибраному діапазоні немає транзакцій!")
        else:
            # 5. Присвоюємо статуси
            # Якщо email є в existing_donors -> Repeated. Якщо ні -> New.
            current_batch['is_new'] = ~current_batch['email'].isin(existing_donors)
            
            # Категорії (Money)
            current_batch['category'] = current_batch.apply(categorize_donor, axis=1)
            
            # 6. Обробка "Героїв" (Мульти-донорів всередині періоду)
            batch_counts = current_batch['email'].value_counts().to_dict()
            current_batch['transactions_in_period'] = current_batch['email'].map(batch_counts)
            
            # --- СТАТИСТИКА ---
            
            # Групуємо по людях (для KPI)
            unique_people = current_batch.groupby('email').agg({
                'is_new': 'first',
                'amount': 'max', # Max donation for classification
                'transactions_in_period': 'first',
                'full_name': 'first',
                'source_system': 'first' # Just for info
            }).reset_index()

            def get_unique_cat(row):
                if row['is_new']:
                    return "1. New (<500)" if row['amount'] < 500 else "2. New (500+)"
                else:
                    return "3. Repeated (<500)" if row['amount'] < 500 else "4. Repeated (500+)"
            
            unique_people['unique_category'] = unique_people.apply(get_unique_cat, axis=1)

            # Metrics
            total_u = len(unique_people)
            one_time = len(unique_people[unique_people['transactions_in_period'] == 1])
            multi = len(unique_people[unique_people['transactions_in_period'] > 1])
            
            st.markdown("---")
            st.subheader(f"📊 Звіт за період: {start_date} — {end_date}")
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Унікальних донорів", total_u)
            k2.metric("1 донат за період", one_time)
            k3.metric("2+ донатів за період", multi, help="Кількість людей, які зробили більше 1 транзакції саме в ці дати")
            
            # Графік
            chart_data = unique_people['unique_category'].value_counts().sort_index()
            st.bar_chart(chart_data)

            # --- EXPORT ---
            st.markdown("### 📥 Отримати фінальний файл")
            
            # Preparing final clean export
            export_df = current_batch[[
                'date', 'full_name', 'email', 'amount', 'category', 'is_new', 
                'tag', 'source_system', 'transactions_in_period'
            ]].sort_values('date', ascending=False)
            
            # Rename for beauty
            export_df.columns = [
                'Date', 'Name', 'Email', 'Amount', 'Category', 'Is New?', 
                'Tag', 'Source', 'Tx Count (Period)'
            ]
            
            csv = export_df.to_csv(index=False).encode('utf-8')
            fname = f"Report_{start_date}_{end_date}.csv"
            
            st.download_button(
                label="📥 Скачати звіт (CSV)",
                data=csv,
                file_name=fname,
                mime='text/csv',
                type='primary'
            )

            with st.expander("🔍 Детальна таблиця (Прев'ю)"):
                st.dataframe(export_df)
