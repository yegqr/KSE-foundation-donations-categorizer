import streamlit as st
import pandas as pd
from datetime import datetime, time
import io
import re
from thefuzz import fuzz, process

# --- CONFIG ---
st.set_page_config(page_title="Donor Time Machine", page_icon="🛡️", layout="wide")
st.title("🛡️ Donor Time Machine: Intelligent Aggregation")

# --- HELPERS ---

def clean_money(val):
    if pd.isna(val): return 0.0
    val_str = str(val)
    clean_str = re.sub(r'[^\d\.]', '', val_str)
    try:
        return float(clean_str)
    except:
        return 0.0

def is_excluded_from_fuzzy(name, email_body=None):
    """
    Фільтр безпеки.
    """
    name_lower = str(name).lower()
    stop_words = ['anonymous', 'unknown', 'donor', 'guest', 'user', 'n/a']
    
    # 1. Check Name
    if any(s in name_lower for s in stop_words) or len(name_lower) < 3:
        return True
    
    # 2. Check Email (if provided)
    if email_body:
        corporate_prefixes = ['info', 'admin', 'ceo', 'contact', 'office', 'support', 'sales', 'marketing', 'finance', 'hr', 'hello', 'team', 'account', 'billing']
        if email_body in corporate_prefixes:
            return True
            
    return False

def normalize_data(df):
    total_raw = len(df)
    df.columns = df.columns.str.lower().str.strip()
    
    # ОНОВЛЕНА МАПА ПОШУКУ
    search_map = {
        'date': ['date of donation', 'donation date', 'donated at', 'date', 'datetime', 'created at', 'time'],
        'email': ['email', 'donor email', 'supporter email', 'e-mail', 'mail'],
        'amount': ['donation amount in usd', 'converted donation amount', 'amount in usd', 'converted amount', 'donation amount', 'amount', 'sum'],
        'first_name': ['contact of the donor', 'donation name', 'supporter first name', 'donor\'s first name', 'first name', 'firstname', 'name'],
        'last_name': ['supporter last name', 'donor\'s last name', 'last name', 'lastname'],
        
        # --- НОВІ КОЛОНКИ ---
        'platform': ['platform', 'payment gateway', 'provider', 'via'],
        'source_origin': ['source'], # Прямий пошук колонки SOURCE
        
        # Tag тепер шукає все інше, крім source (щоб не було конфлікту)
        'tag': ['designations', 'direction', 'utm campaign source', 'utm source', 'campaign', 'project']
    }
    
    found_cols = {}
    for target_col, candidates in search_map.items():
        match = None
        for candidate in candidates:
            if candidate in df.columns:
                match = candidate
                break
        if match: found_cols[target_col] = match
    
    rename_dict = {v: k for k, v in found_cols.items()}
    df = df.rename(columns=rename_dict)
    
    if 'date' not in df.columns: return None, "Error: No Date column found."
    if 'email' not in df.columns: return None, "Error: No Email column found."

    # FIX: Ensure text columns are actually strings
    # Додаємо сюди нові колонки, щоб перетворити їх на текст і прибрати NaN
    text_cols = ['first_name', 'last_name', 'tag', 'platform', 'source_origin']
    for col in text_cols:
        if col not in df.columns: 
            df[col] = ''
        else:
            df[col] = df[col].astype(str).replace('nan', '').fillna('')
    
    df['full_name'] = (df['first_name'] + ' ' + df['last_name']).str.strip()
    df['email'] = df['email'].astype(str).str.lower().str.strip()
    df['email_body'] = df['email'].apply(lambda x: x.split('@')[0] if '@' in x else x)
    
    df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
    df = df.dropna(subset=['date'])
    
    df['amount'] = df['amount'].apply(clean_money)
    zeros = len(df[df['amount'] <= 0])
    df = df[df['amount'] > 0]
    
    final_count = len(df)
    stats = {"raw_rows": total_raw, "zero_amounts": zeros, "final_rows": final_count}
    
    # Повертаємо нові колонки теж
    return df[['date', 'email', 'email_body', 'full_name', 'amount', 'tag', 'platform', 'source_origin']], stats

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# --- UI EXECUTION ---

st.sidebar.header("1. Data Input")
uploaded_file = st.sidebar.file_uploader("Upload Master File (Excel/CSV)", type=['xlsx', 'xls', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            raw_df = pd.read_csv(uploaded_file)
        else:
            raw_df = pd.read_excel(uploaded_file)
            
        df, load_stats = normalize_data(raw_df)
        
        if df is None:
            st.error(load_stats)
            st.stop()
            
        df = df.sort_values('date')
        
        st.sidebar.success(f"✅ Loaded: {len(df)} txs")
        st.sidebar.markdown(f"**Data Quality Log:**")
        st.sidebar.text(f"Raw Rows:   {load_stats['raw_rows']}")
        st.sidebar.text(f"Zero/Ref:   -{load_stats['zero_amounts']}")
        st.sidebar.text(f"Clean Rows: ={load_stats['final_rows']}")
        
    except Exception as e:
        st.error(f"File Error: {e}")
        st.stop()

    st.header("2. Analysis Settings")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("From (Inclusive)", value=datetime(2025, 12, 1))
    end_date = c2.date_input("To (Inclusive)", value=datetime.now())
    
    use_smart_match = st.checkbox("🧠 Enable Smart Name Match", value=False, 
                                  help="Якщо пошта не знайдена, шукає збіг по колонці Contact of the donor. Поріг схожості 88%.")

    if st.button("🚀 Run Aggregated Analytics", type="primary"):
        ts_start = pd.Timestamp(datetime.combine(start_date, time.min))
        ts_end = pd.Timestamp(datetime.combine(end_date, time.max))
        
        # 1. SPLIT DATA
        history_df = df[df['date'] < ts_start]
        period_df = df[(df['date'] >= ts_start) & (df['date'] <= ts_end)].copy()
        
        if period_df.empty:
            st.warning("No transactions in selected period.")
            st.stop()

        # 2. LIFETIME STATS (Aggregation by Email)
        lifetime_stats = df.groupby('email').agg(
            lifetime_count=('date', 'count'),
            lifetime_sum=('amount', 'sum')
        )
        
        # 3. PERIOD STATS (Aggregation by Email)
        # ТУТ ДОДАЄМО АГРЕГАЦІЮ НОВИХ КОЛОНОК
        period_stats = period_df.groupby('email').agg(
            period_count=('date', 'count'),
            period_sum=('amount', 'sum'),
            full_name=('full_name', 'first'),
            email_body=('email_body', 'first'),
            
            # Склеюємо унікальні значення через кому
            tag=('tag', lambda x: ', '.join(sorted(set(str(i) for i in x if i and str(i).strip() != '')))),
            platform=('platform', lambda x: ', '.join(sorted(set(str(i) for i in x if i and str(i).strip() != '')))),
            source_origin=('source_origin', lambda x: ', '.join(sorted(set(str(i) for i in x if i and str(i).strip() != ''))))
            
        ).reset_index()
        
        # 4. PRIMARY CHECK: EXACT EMAIL MATCH
        existing_emails = set(history_df['email'].unique())
        period_stats['is_new'] = ~period_stats['email'].isin(existing_emails)
        
        # 5. SECONDARY CHECK: SMART NAME MATCH
        period_stats['potential_duplicate'] = False
        smart_match_count = 0
        
        if use_smart_match:
            candidates = period_stats[period_stats['is_new'] == True]
            history_names = history_df['full_name'].dropna().unique()
            history_names = [n for n in history_names if not is_excluded_from_fuzzy(n)]
            
            if len(history_names) > 0 and not candidates.empty:
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_cand = len(candidates)
                
                for i, (idx, row) in enumerate(candidates.iterrows()):
                    if i % 10 == 0: 
                        progress_bar.progress(int((i / total_cand) * 100))
                        status_text.text(f"Smart Match Scanning: {i}/{total_cand} candidates...")
                    
                    name_cand = row['full_name']
                    if is_excluded_from_fuzzy(name_cand, row['email_body']): 
                        continue
                    
                    best_match, score = process.extractOne(name_cand, history_names, scorer=fuzz.token_sort_ratio)
                    
                    if score >= 88:
                        period_stats.at[idx, 'is_new'] = False 
                        period_stats.at[idx, 'potential_duplicate'] = True
                        smart_match_count += 1
                        
                progress_bar.empty()
                status_text.empty()

        # 6. MERGE & CATEGORIZE
        final_df = period_stats.merge(lifetime_stats, on='email', how='left')
        
        def get_cat(row):
            status = "New" if row['is_new'] else "Repeated"
            value = "500+" if row['period_sum'] >= 500 else "<500"
            
            if status == "New" and value == "<500": return "1. New (<500)"
            if status == "New" and value == "500+": return "2. New (500+)"
            if status == "Repeated" and value == "<500": return "3. Repeated (<500)"
            return "4. Repeated (500+)"

        final_df['Category'] = final_df.apply(get_cat, axis=1)
        
        # Rename Cols for Export (ДОДАЛИ НОВІ)
        output_cols = [
            'email', 'full_name', 
            'period_count', 'period_sum', 
            'lifetime_count', 'lifetime_sum', 
            'Category', 
            'platform', 'source_origin', 'tag', # <--- ОСЬ ВОНИ
            'potential_duplicate'
        ]
        
        pretty_cols = {
            'email': 'Email', 'full_name': 'Name', 
            'period_count': 'Period Tx', 'period_sum': 'Period Sum ($)', 
            'lifetime_count': 'Lifetime Tx', 'lifetime_sum': 'Lifetime Sum ($)', 
            'tag': 'Tags (Designation)', 
            'platform': 'Platform',          # <---
            'source_origin': 'Source',       # <---
            'potential_duplicate': 'Name Match Flag'
        }
        
        final_df = final_df[output_cols].rename(columns=pretty_cols)
        
        # --- STATISTICS DASHBOARD ---
        st.divider()
        st.subheader("📊 Analytical Report")
        
        total_raised = final_df['Period Sum ($)'].sum()
        total_donors = len(final_df)
        avg_val = total_raised / total_donors if total_donors > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Period Volume", f"${total_raised:,.2f}")
        m2.metric("Unique Donors", total_donors)
        m3.metric("Avg Donor Value", f"${avg_val:,.2f}")
        m4.metric("Smart Match Saves", smart_match_count, help="Donors identified by Name Match")
        
        st.markdown("### 🧩 Segmentation Breakdown")
        
        df_new = final_df[final_df['Category'].str.contains("New")]
        df_rep = final_df[final_df['Category'].str.contains("Repeated")]
        
        sc1, sc2 = st.columns(2)
        with sc1:
            st.info(f"**🐣 New Donors**")
            col_a, col_b = st.columns(2)
            col_a.metric("Count", len(df_new))
            col_b.metric("Volume", f"${df_new['Period Sum ($)'].sum():,.2f}")
        
        with sc2:
            st.success(f"**🔄 Repeated Donors**")
            col_a, col_b = st.columns(2)
            col_a.metric("Count", len(df_rep))
            col_b.metric("Volume", f"${df_rep['Period Sum ($)'].sum():,.2f}")

        # --- DOWNLOADS ---
        st.divider()
        st.markdown("### 📥 Download Lists")
        st.caption("Число в дужках [] — це кількість унікальних донорів у файлі.")
        
        df_new_low = final_df[final_df['Category'] == "1. New (<500)"]
        df_new_high = final_df[final_df['Category'] == "2. New (500+)"]
        df_rep_low = final_df[final_df['Category'] == "3. Repeated (<500)"]
        df_rep_high = final_df[final_df['Category'] == "4. Repeated (500+)"]
        
        d1, d2, d3, d4 = st.columns(4)
        
        with d1:
            st.download_button(
                f"📂 1. New (<500) [{len(df_new_low)}]", 
                convert_df_to_csv(df_new_low), 
                f"New_Low_{start_date}.csv", "text/csv"
            )
        with d2:
            st.download_button(
                f"📂 2. New (500+) [{len(df_new_high)}]", 
                convert_df_to_csv(df_new_high), 
                f"New_High_{start_date}.csv", "text/csv"
            )
        with d3:
            st.download_button(
                f"📂 3. Repeated (<500) [{len(df_rep_low)}]", 
                convert_df_to_csv(df_rep_low), 
                f"Rep_Low_{start_date}.csv", "text/csv"
            )
        with d4:
            st.download_button(
                f"📂 4. Repeated (500+) [{len(df_rep_high)}]", 
                convert_df_to_csv(df_rep_high), 
                f"Rep_High_{start_date}.csv", "text/csv"
            )
            
        with st.expander("🔍 Preview Data"):
            st.dataframe(final_df.head(50))
