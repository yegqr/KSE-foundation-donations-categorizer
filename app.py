import streamlit as st
import pandas as pd
import difflib
from datetime import datetime
import io

# --- КОНФІГУРАЦІЯ СТОРІНКИ ---
st.set_page_config(page_title="Donor Classifier Pro", page_icon="💸", layout="wide")

st.title("💸 Donor Classifier & Analytics")
st.markdown("""
Цей інструмент категоризує донорів на **New** (нові) та **Repeated** (повторні), 
враховуючи історію з бази та перевірку на дублі транзакцій у поточному файлі.
""")

# --- ЛОГІКА ---

def get_token_sort_ratio(str1, str2):
    if not isinstance(str1, str) or not isinstance(str2, str):
        return 0
    tokens1 = sorted(str1.lower().split())
    tokens2 = sorted(str2.lower().split())
    s1 = " ".join(tokens1)
    s2 = " ".join(tokens2)
    matcher = difflib.SequenceMatcher(None, s1, s2)
    return matcher.ratio() * 100

def parse_dates(series):
    return pd.to_datetime(series, format='mixed', errors='coerce')

def process_data(donations_file, supporters_file):
    # 1. Читання
    try:
        df_don = pd.read_csv(donations_file)
        df_sup = pd.read_csv(supporters_file)
    except Exception as e:
        st.error(f"Помилка читання CSV: {e}")
        return None, None

    # 2. Підготовка
    df_don['dt_obj'] = parse_dates(df_don['Donation Date'])
    df_sup['first_dt_obj'] = parse_dates(df_sup['First Donation Date'])
    
    BATCH_START_DATE = df_don['dt_obj'].min()
    
    # Клінінг
    df_sup['Email'] = df_sup['Email'].astype(str).str.lower().str.strip()
    df_sup['Full_Name'] = (df_sup['First Name'].fillna('') + ' ' + df_sup['Last Name'].fillna('')).str.lower().str.strip()
    
    df_don['Supporter Email'] = df_don['Supporter Email'].astype(str).str.lower().str.strip()
    df_don['clean_name'] = (df_don['Supporter First Name'].fillna('') + ' ' + df_don['Supporter Last Name'].fillna('')).str.lower().str.strip()
    df_don['Donation Amount'] = pd.to_numeric(df_don['Converted Donation Amount'], errors='coerce').fillna(0)
    
    if 'UTM Campaign Source' in df_don.columns:
        df_don['tag'] = df_don['UTM Campaign Source'].fillna('')
    else:
        df_don['tag'] = ''

    sup_dict = df_sup.set_index('Email')[['Lifetime Donations', 'Lifetime Donated', 'first_dt_obj']].to_dict('index')
    
    result = df_don.copy()
    result['is_new'] = True 
    result['match_type'] = 'None' 
    result['hist_count'] = 0
    result['hist_sum'] = 0.0

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_rows = len(result)

    # 3. Аналіз
    for idx, row in result.iterrows():
        if idx % (max(1, total_rows // 10)) == 0:
            progress = int((idx / total_rows) * 100)
            progress_bar.progress(progress)
            status_text.text(f"Обробка транзакції {idx}/{total_rows}...")

        email = row['Supporter Email']
        donor_name = row['clean_name']
        match_data = None
        
        # A. Email Match
        if email in sup_dict:
            match_data = sup_dict[email]
            result.at[idx, 'match_type'] = 'Email'
        # B. Fuzzy Match
        else:
            if len(donor_name) > 3:
                best_score = 0
                best_match_idx = -1
                potential_matches = df_sup[df_sup['Full_Name'].str.startswith(donor_name[0], na=False)]
                if potential_matches.empty: potential_matches = df_sup
                
                for sup_idx, sup_row in potential_matches.iterrows():
                    score = get_token_sort_ratio(donor_name, sup_row['Full_Name'])
                    if score > best_score:
                        best_score = score
                        best_match_idx = sup_idx
                
                if best_score >= 80:
                    match_data = df_sup.loc[best_match_idx]
                    result.at[idx, 'match_type'] = 'Fuzzy'

        # C. Status Determination
        if match_data is not None:
            if isinstance(match_data, pd.Series):
                first_date = match_data['first_dt_obj']
                lt_count = match_data['Lifetime Donations']
                lt_sum = match_data['Lifetime Donated']
            else:
                first_date = match_data['first_dt_obj']
                lt_count = match_data['Lifetime Donations']
                lt_sum = match_data['Lifetime Donated']

            result.at[idx, 'hist_count'] = lt_count
            result.at[idx, 'hist_sum'] = lt_sum

            if pd.notnull(first_date) and first_date < BATCH_START_DATE:
                result.at[idx, 'is_new'] = False
            else:
                result.at[idx, 'is_new'] = True
        else:
            result.at[idx, 'is_new'] = True
            result.at[idx, 'hist_count'] = 1
            result.at[idx, 'hist_sum'] = row['Donation Amount']

    progress_bar.progress(100)
    status_text.text("Готово!")

    # 4. Категоризація (НОВІ НАЗВИ)
    def assign_category(row):
        is_new = row['is_new']
        amount = row['Donation Amount']
        if is_new:
            return "1. New (<500)" if amount < 500 else "2. New (500+)"
        else:
            return "3. Repeated (<500)" if amount < 500 else "4. Repeated (500+)"

    result['category'] = result.apply(assign_category, axis=1)

    # 5. Frequency Count
    batch_counts = result['Supporter Email'].value_counts().to_dict()
    result['batch_count'] = result['Supporter Email'].map(batch_counts)

    # 6. Output
    output = pd.DataFrame()
    output['ID'] = result['Supporter ID']
    output['new'] = result['is_new']
    output['category'] = result['category']
    output['date'] = result['dt_obj'].dt.date
    output['name'] = result['Supporter First Name'] + ' ' + result['Supporter Last Name']
    output['email'] = result['Supporter Email']
    output['donation'] = result['Donation Amount']
    output['tag'] = result['tag']
    output['transactions_in_batch'] = result['batch_count']
    output['is_multi_donor'] = result['batch_count'] > 1
    output['total_lifetime_donations'] = result['hist_count']
    output['total_lifetime_donated'] = result['hist_sum']
    output['email_mess'] = result['match_type'] == 'Fuzzy'

    return output, result

# --- ІНТЕРФЕЙС ---

col1, col2 = st.columns(2)
with col1:
    donations_file = st.file_uploader("📂 Завантаж Donations CSV", type=['csv'])
with col2:
    supporters_file = st.file_uploader("📂 Завантаж Supporters CSV", type=['csv'])

if donations_file and supporters_file:
    if st.button("🚀 Запустити аналіз", type="primary"):
        with st.spinner('Магія працює...'):
            output_df, raw_result = process_data(donations_file, supporters_file)
        
        if output_df is not None:
            # --- БЛОК СТАТИСТИКИ ---
            st.success("Аналіз завершено!")
            
            # Рахуємо унікальних
            unique_stats = raw_result.groupby('Supporter Email').agg({
                'is_new': 'first',
                'Donation Amount': 'max',
                'batch_count': 'first'
            }).reset_index()

            # Категоризація для статистики (НОВІ НАЗВИ)
            def get_unique_category(row):
                is_new = row['is_new']
                max_amount = row['Donation Amount']
                if is_new:
                    return "1. New (<500)" if max_amount < 500 else "2. New (500+)"
                else:
                    return "3. Repeated (<500)" if max_amount < 500 else "4. Repeated (500+)"

            unique_stats['unique_category'] = unique_stats.apply(get_unique_category, axis=1)
            
            # KPI Metrics
            total_people = len(unique_stats)
            multi_donors = len(unique_stats[unique_stats['batch_count'] > 1])
            one_timers = total_people - multi_donors
            
            # --- ВИПРАВЛЕНІ KPI ---
            kpi1, kpi2, kpi3 = st.columns(3)
            
            kpi1.metric(
                "Унікальних донорів (у файлі)", 
                total_people, 
                help="Кількість унікальних email-адрес у завантаженому файлі donations"
            )
            
            kpi2.metric(
                "1 донат за цей період", 
                one_timers, 
                help="Люди, які зробили рівно 1 транзакцію у цьому файлі"
            )
            
            kpi3.metric(
                "2+ донатів за цей період", 
                multi_donors, 
                help="Люди, які зробили 2 або більше транзакцій САМЕ В ЦЬОМУ файлі (ваші найактивніші зараз)"
            )

            st.markdown("### 📊 Розподіл по категоріях (Унікальні люди)")
            cat_counts = unique_stats['unique_category'].value_counts().sort_index()
            st.bar_chart(cat_counts)
            
            # --- ЗАВАНТАЖЕННЯ ---
            st.markdown("### 📥 Скачати результат")
            
            csv = output_df.to_csv(index=False).encode('utf-8')
            filename = f"classified_donors_{datetime.now().strftime('%Y%m%d')}.csv"
            
            st.download_button(
                label="Скачати CSV",
                data=csv,
                file_name=filename,
                mime='text/csv',
                type='primary'
            )
            
            with st.expander("Переглянути сирі дані (Preview)"):
                st.dataframe(output_df.head(50))
