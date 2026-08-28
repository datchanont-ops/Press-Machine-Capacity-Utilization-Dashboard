import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import streamlit.components.v1 as components
import os
import re
import io
import json
import base64
import requests

# ==========================================
# Page Configuration & Theming
# ==========================================
st.set_page_config(page_title="Press Capacity Pro Dashboard", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

trigger_save = False

# ==========================================
# 🔗 GitHub Persistence Layer
# ==========================================
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
    GITHUB_DATA_DIR = st.secrets.get("GITHUB_DATA_DIR", "data")
    GITHUB_ENABLED = True
except Exception:
    GITHUB_ENABLED = False

GITHUB_API = "https://api.github.com"

def gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def gh_get_file(remote_path):
    if not GITHUB_ENABLED: return None, None
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{remote_path}?ref={GITHUB_BRANCH}"
    try:
        r = requests.get(url, headers=gh_headers(), timeout=15)
        if r.status_code == 200:
            data = r.json()
            return base64.b64decode(data["content"]), data["sha"]
    except Exception: pass
    return None, None

def gh_put_file(remote_path, content_bytes, message):
    if not GITHUB_ENABLED: return False, "GitHub Secrets not set"
    _, sha = gh_get_file(remote_path)
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{remote_path}"
    payload = {"message": message, "content": base64.b64encode(content_bytes).decode("utf-8"), "branch": GITHUB_BRANCH}
    if sha: payload["sha"] = sha
    try:
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=15)
        if r.status_code in (200, 201): return True, "Success"
        else: return False, f"HTTP {r.status_code}: {r.text}"
    except Exception as e: return False, str(e)

# ==========================================
# 🎨 PRO CSS Styling (Enterprise Look)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
    
    [data-testid="stMetric"] {
        background-color: #ffffff; padding: 20px 24px; border-radius: 12px;
        box-shadow: 0px 4px 20px rgba(0, 0, 0, 0.04); border: 1px solid #f1f5f9;
        transition: transform 0.2s ease, box-shadow 0.2s ease; position: relative; overflow: hidden;
    }
    [data-testid="stMetric"]:hover { transform: translateY(-3px); box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.08); }
    [data-testid="stMetric"]::before { content: ''; position: absolute; top: 0; left: 0; width: 6px; height: 100%; }
    
    div[data-testid="column"]:nth-child(1) [data-testid="stMetric"]::before { background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%); }
    div[data-testid="column"]:nth-child(2) [data-testid="stMetric"]::before { background: linear-gradient(180deg, #10b981 0%, #059669 100%); }
    div[data-testid="column"]:nth-child(3) [data-testid="stMetric"]::before { background: linear-gradient(180deg, #f59e0b 0%, #d97706 100%); }
    div[data-testid="column"]:nth-child(4) [data-testid="stMetric"]::before { background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%); }

    .streamlit-expanderHeader { font-weight: 600 !important; color: #1e293b !important; background-color: #f1f5f9; border-radius: 8px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: #ffffff; border-radius: 6px 6px 0 0; box-shadow: 0 -2px 10px rgba(0,0,0,0.02); padding: 10px 20px; }
    
    h1, h2, h3 { color: #0f172a; font-weight: 800; tracking: -0.02em; }
    @media print { .stPopover, .stExpander, header, [data-testid="stSidebar"] { display: none !important; } body { background-color: white !important; } }
</style>
""", unsafe_allow_html=True)

# ==========================================
# Data Processing
# ==========================================
@st.cache_data
def load_and_process(db_file, up_file, wip_reduction_pct):
    try:
        data_fo = pd.read_excel(up_file, sheet_name='data fo')
        wip_fg = pd.read_excel(up_file, sheet_name='wip-fg')
        fg_semi = pd.read_excel(db_file, sheet_name='FG-SEMI')
        capacity = pd.read_excel(db_file, sheet_name='Capacity')
        mc_data = pd.read_excel(db_file, sheet_name='mc data')

        wip_fg['Material'] = wip_fg['Material'].astype(str).str.replace(r';A1$', '', regex=True).str.replace(r';A2$', '', regex=True)
        wip_agg = wip_fg.groupby('Material', as_index=False)['Unrestricted'].sum()
        
        fo_cols = [c for c in data_fo.columns if 'FO' in str(c).upper() and '(PCS)' in str(c).upper() and re.search(r'\d{2}\.\d{4}', str(c))]
        if len(fo_cols) >= 3:
            fo_cols.sort(key=lambda x: pd.to_datetime(re.search(r'\d{2}\.\d{4}', x).group(), format='%m.%Y'))
            m_minus_1_str, m_n_str, m_n1_str = re.search(r'\d{2}\.\d{4}', fo_cols[-3]).group(), re.search(r'\d{2}\.\d{4}', fo_cols[-2]).group(), re.search(r'\d{2}\.\d{4}', fo_cols[-1]).group()
        else:
            m_minus_1_str, m_n_str, m_n1_str = '07.2026', '08.2026', '09.2026'

        def get_valid_col(df, kw1, kw2, m_str, fallback_name):
            cols = [c for c in df.columns if kw1 in str(c).upper() and kw2 in str(c).upper() and m_str in str(c)]
            return cols[0] if cols and cols[0] in df.columns else fallback_name

        df = data_fo[['Material', 'Description']].copy()
        for col_name, (kw1, kw2, m_str) in zip(
            ['fo_n_m1', 'ord_n_m1', 'fo_n', 'ord_n', 'fo_n1', 'ord_n1'],
            [('FO','(PCS)',m_minus_1_str), ('ORD','(PCS)',m_minus_1_str), ('FO','(PCS)',m_n_str), ('ORD','(PCS)',m_n_str), ('FO','(PCS)',m_n1_str), ('ORD','(PCS)',m_n1_str)]
        ):
            real_col = get_valid_col(data_fo, kw1, kw2, m_str, f'{kw1}_{m_str}')
            if real_col not in data_fo.columns: data_fo[real_col] = 0
            df[col_name] = data_fo[real_col]

        df['Max_N_minus_1'] = df[['fo_n_m1', 'ord_n_m1']].max(axis=1).fillna(0)
        df['Max_N'] = df[['fo_n', 'ord_n']].max(axis=1).fillna(0)
        df['Max_N1'] = df[['fo_n1', 'ord_n1']].max(axis=1).fillna(0)
        
        if len(data_fo.columns) >= 15:
            amt_series = pd.to_numeric(data_fo.iloc[:, 14], errors='coerce').fillna(0)
            total_sales_n = amt_series.sum()
            df['Max_N_Amt'] = amt_series
        else:
            df['Max_N_Amt'], total_sales_n = 0, 0
        
        df = pd.merge(df, wip_agg, on='Material', how='left').fillna(0)
        df['Unrestricted'] = df['Unrestricted'] * (1 - (wip_reduction_pct / 100.0))
        df['Req_Qty'] = (df['Max_N'] + (df['Max_N1'] * 0.3) - df['Unrestricted']).clip(lower=0)

        df = pd.merge(df, fg_semi[['Material', 'Semi Part']], on='Material', how='left')
        cap_unique = capacity.drop_duplicates(subset=['Semi Part'])
        df = pd.merge(df, cap_unique[['Semi Part', 'Machine Type', 'Cap/1กะ  (pc)', 'กะละ (hr)']], on='Semi Part', how='left')

        df['Cap/1กะ  (pc)'] = df['Cap/1กะ  (pc)'].replace(0, np.nan)
        df['Req_Hours'] = ((df['Req_Qty'] / df['Cap/1กะ  (pc)']) * df['กะละ (hr)']).fillna(0)

        req_by_mach = df.groupby('Machine Type', as_index=False)['Req_Hours'].sum()
        mach_summary = mc_data[['Machine Type', 'จำนวนเครื่องทั้งหมด', 'จำนวนเครื่องที่ให้ใช้ได้']].copy().dropna(subset=['Machine Type'])
        mach_summary.rename(columns={'จำนวนเครื่องทั้งหมด': 'Total Machines', 'จำนวนเครื่องที่ให้ใช้ได้': 'Usable Machines'}, inplace=True)
        mach_summary = pd.merge(mach_summary, req_by_mach, on='Machine Type', how='left').fillna(0)

        df_detail = df[['Material', 'Description', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Max_N_Amt', 'Req_Qty', 'Semi Part', 'Machine Type', 'Req_Hours']].copy()
        
        return mach_summary, df_detail, total_sales_n, m_n_str, None
    except Exception as e:
        return None, None, 0, "", f"System Error: {str(e)}"

# ==========================================
# Sidebar Settings
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ Control Panel")
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data base.xlsx')
    saved_up_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_data_upload.xlsx')
    settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'machine_settings.json')
    data_settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_settings.json')

    if GITHUB_ENABLED and not st.session_state.get("github_synced"):
        with st.spinner("🔄 Syncing Cloud Data..."):
            for fname, local_path in [("saved_data_upload.xlsx", saved_up_file), ("machine_settings.json", settings_file), ("data_settings.json", data_settings_file)]:
                content, _ = gh_get_file(f"{GITHUB_DATA_DIR}/{fname}")
                if content:
                    with open(local_path, "wb") as f: f.write(content)
        st.session_state["github_synced"] = True

    uploaded_up = st.file_uploader("📂 Upload Monthly Data (.xlsx)", type=["xlsx", "xls"])
    saved_data_settings = {}
    if os.path.exists(data_settings_file):
        try:
            with open(data_settings_file, 'r', encoding='utf-8') as f: saved_data_settings = json.load(f)
        except: pass
    
    if "p_work_days" not in st.session_state: st.session_state.p_work_days = int(saved_data_settings.get("work_days", 23))
    if "p_wip" not in st.session_state: st.session_state.p_wip = float(saved_data_settings.get("wip_reduction_pct", 0.0))

    st.markdown("---")
    work_days = st.number_input("🗓️ วันทำงานปกติ (วัน/เดือน)", min_value=1, max_value=31, key="p_work_days")
    wip_reduction_pct = st.number_input("📉 ปรับลด % WIP/FG", min_value=0.0, max_value=100.0, step=1.0, key="p_wip")
    st.markdown("---")

    active_file = None
    if uploaded_up is not None:
        active_file = uploaded_up
        file_signature = f"{uploaded_up.name}_{uploaded_up.size}"
        if st.session_state.get("last_saved_signature") != file_signature:
            file_bytes = bytes(uploaded_up.getbuffer())
            with open(saved_up_file, "wb") as f: f.write(file_bytes)
            if GITHUB_ENABLED: gh_put_file(f"{GITHUB_DATA_DIR}/saved_data_upload.xlsx", file_bytes, f"Auto-save: {uploaded_up.name}")
            st.session_state["last_saved_signature"] = file_signature
            st.toast("✅ File Uploaded & Synced")

        if st.button("💾 Save All Settings", use_container_width=True, type="primary"): trigger_save = True
        st.caption("🟢 Status: Using New Upload")
    elif os.path.exists(saved_up_file):
        active_file = saved_up_file
        st.caption("📌 Status: Using Cached Data")
        if st.button("💾 Save All Settings", use_container_width=True, type="primary"): trigger_save = True
        if st.button("🗑️ Clear Cache", use_container_width=True):
            os.remove(saved_up_file)
            st.session_state.pop("last_saved_signature", None)
            st.rerun()

# ==========================================
# Application Start (Validation)
# ==========================================
if not os.path.exists(db_file) or active_file is None:
    st.markdown("<h2 style='margin-bottom: 0px;'>📊 Press Capacity Utilization <span style='color: #3b82f6;'>Pro</span></h2>", unsafe_allow_html=True)
    st.info("👋 กรุณาอัปโหลดไฟล์ **Data Upload (.xlsx)** ประจำเดือนที่แถบด้านซ้ายมือ เพื่อเริ่มต้นใช้งาน")
    st.stop()

mach_summary, df_detail, total_sales_n, m_n_str, err = load_and_process(db_file, active_file, wip_reduction_pct)
if err: st.error(err); st.stop()
month_display = pd.to_datetime(m_n_str, format='%m.%Y').strftime('%b%y') if m_n_str else ""

# ==========================================
# Main Dashboard Header (Dynamic)
# ==========================================
col_header, col_export = st.columns([4, 1])
with col_header:
    st.markdown(f"<h2 style='margin-bottom: 0px; display: flex; align-items: center;'>📊 Press Capacity Utilization <span style='color: #3b82f6; margin-left: 8px;'>Pro</span> <span style='font-size: 16px; color: #0284c7; background: #e0f2fe; padding: 4px 12px; border-radius: 20px; margin-left: 15px;'>🗓️ {month_display}</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #64748b; font-size: 15px;'>ระบบวิเคราะห์และวางแผนกำลังการผลิตขั้นสูงสำหรับเครื่องจักร Press</p>", unsafe_allow_html=True)

export_placeholder = col_export.empty()

# ==========================================
# Initialize Machine Settings
# ==========================================
cfg = mach_summary.copy()
cfg['Hours/Shift'] = 7.0

def get_sort_priority(mt):
    mt_up = str(mt).upper()
    if "INJ" in mt_up: return 1
    elif "PRESS" in mt_up: return 2
    elif "VACUUM" in mt_up: return 3
    else: return 4

cfg['Sort_Priority'] = cfg['Machine Type'].apply(get_sort_priority)
cfg = cfg.sort_values(by=['Sort_Priority', 'Machine Type']).reset_index(drop=True)

saved_settings = {}
if os.path.exists(settings_file):
    try:
        with open(settings_file, 'r', encoding='utf-8') as f: saved_settings = json.load(f)
    except: pass

saved_oee = saved_settings.get('oee_dict', {})
saved_use = saved_settings.get('use_dict', {})
saved_shift = saved_settings.get('shift_dict', {})
saved_ot = saved_settings.get('ot_dict', {})

for idx, row in cfg.iterrows():
    mt = str(row['Machine Type'])
    if f"use_{mt}" not in st.session_state: st.session_state[f"use_{mt}"] = int(saved_use.get(mt, row['Usable Machines']))
    if f"shf_{mt}" not in st.session_state: st.session_state[f"shf_{mt}"] = float(saved_shift.get(mt, 3.0))
    if f"oee_{mt}" not in st.session_state: st.session_state[f"oee_{mt}"] = int(saved_oee.get(mt, 85))
    if f"ot_{mt}" not in st.session_state: st.session_state[f"ot_{mt}"] = int(saved_ot.get(mt, 0))

# ==========================================
# Interactive Adjustments
# ==========================================
with st.expander("🎛️ **แผงควบคุมกำลังผลิตรายเครื่อง (Machine Configuration)**", expanded=False):
    b1, b2, b3 = st.columns([2, 1, 1])
    bulk_oee = b1.number_input("🔄 ตั้งค่า OEE เท่ากันทุกเครื่อง (%)", value=85, min_value=1, max_value=100)
    if b2.button("✨ นำไปใช้กับทุกเครื่อง", use_container_width=True):
        for mt in cfg['Machine Type']: st.session_state[f"oee_{mt}"] = bulk_oee
        st.rerun()
    if b3.button("💾 บันทึกการตั้งค่าตารางนี้", use_container_width=True, type="primary"): trigger_save = True
    
    st.markdown("---")
    h1, h2, h3, h4, h5, h6 = st.columns([3, 1, 1, 1, 1, 1])
    h1.markdown("**Machine Type**")
    h2.markdown("**ทั้งหมด (M/c)**")
    h3.markdown("**เปิดใช้**")
    h4.markdown("**กะ/วัน**")
    h5.markdown("**OEE (%)**")
    h6.markdown("**OT (+วัน)**")
    
    over_alerts = []
    with st.container(height=300):
        for idx, row in cfg.iterrows():
            mt, total_mach = str(row['Machine Type']), int(row['Total Machines'])
            c1, c2, c3, c4, c5, c6 = st.columns([3, 1, 1, 1, 1, 1])
            c1.markdown(f"<div style='font-size: 14px; margin-top: 5px; font-weight:600;'>{mt}</div>", unsafe_allow_html=True)
            c2.markdown(f"<div style='font-size: 14px; margin-top: 5px; color:#64748b;'>{total_mach}</div>", unsafe_allow_html=True)
            
            use_val = c3.number_input("U", min_value=0, key=f"use_{mt}", label_visibility="collapsed")
            shift_val = c4.selectbox("S", [1.0, 1.5, 2.0, 3.0], key=f"shf_{mt}", label_visibility="collapsed")
            oee_val = c5.number_input("O", min_value=1, max_value=100, key=f"oee_{mt}", label_visibility="collapsed")
            ot_val = c6.number_input("OT", min_value=0, max_value=31, key=f"ot_{mt}", label_visibility="collapsed")
            
            cfg.at[idx, 'Usable Machines'], cfg.at[idx, 'Shifts/Day'], cfg.at[idx, 'OEE (%)'], cfg.at[idx, 'OT_Days'] = use_val, shift_val, oee_val, ot_val
            if use_val > total_mach: over_alerts.append(f"{mt} (มี {total_mach} แต่ตั้ง {use_val})")
            
    if over_alerts: st.error("⚠️ **เตือน! เครื่องจักรถูกเปิดใช้เกินจำนวนที่มี:** " + ", ".join(over_alerts))

# --- Calculate Final Capacity ---
cfg['Capacity_Per_Machine'] = (cfg['Shifts/Day'] * cfg['Hours/Shift'] * (work_days + cfg['OT_Days'].fillna(0)) * (cfg['OEE (%)'] / 100.0))
cfg['Available Hours'] = cfg['Usable Machines'] * cfg['Capacity_Per_Machine']
cfg['Utilization (%)'] = np.where(cfg['Available Hours'] > 0, (cfg['Req_Hours'] / cfg['Available Hours']) * 100.0, 0.0)
cfg['Req_Machines'] = np.where(cfg['Capacity_Per_Machine'] > 0, cfg['Req_Hours'] / cfg['Capacity_Per_Machine'], 0.0)

# ==========================================
# Export Button
# ==========================================
with export_placeholder.container():
    st.write("")
    with st.popover("📥 Reports"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            cfg.to_excel(writer, sheet_name='Machine_Summary', index=False)
            df_detail.to_excel(writer, sheet_name='Part_Details', index=False)
        st.download_button(label="💾 Excel Data", data=output.getvalue(), file_name=f"Capacity_{month_display}.xlsx", use_container_width=True)
        components.html("<button onclick='window.parent.print()' style='background:#0f172a; color:white; padding:8px; border-radius:6px; width:100%; border:none; cursor:pointer;'>🖨️ Print PDF</button>", height=50)

# ==========================================
# 📈 1. Executive Summary (KPIs)
# ==========================================
total_machines_all = 66
total_req, total_avail = cfg['Req_Hours'].sum(), cfg['Available Hours'].sum()
overall_util = (total_req / total_avail) * 100 if total_avail > 0 else 0
over_cap_count = len(cfg[cfg['Utilization (%)'] > 100])
adj_mach_val = (cfg['Usable Machines'] * (cfg['Shifts/Day'] / 3.0)).sum()
adj_mach_str = f"{adj_mach_val:.1f}".rstrip('0').rstrip('.')

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("🛠️ Total Machines", f"{total_machines_all} units")
kpi2.metric("🟢 Active Machines (Eqv.)", f"{adj_mach_str} units")
kpi3.metric("🔥 Req. Machines", f"{cfg['Req_Machines'].sum():.1f} units")
kpi4.metric("⏱️ Total Req. Hours", f"{total_req:,.0f} hr")

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
kpi5, kpi6, kpi7, kpi8 = st.columns(4)
kpi5.metric("📈 Overall Utilization", f"{overall_util:.1f}%")
kpi6.metric("⚠️ Over Capacity Types", f"{over_cap_count} machines", delta="Action Required" if over_cap_count > 0 else "Optimal", delta_color="inverse")
kpi7.metric("💰 Estimated Sales", f"฿ {total_sales_n:,.0f}")
kpi8.metric("🗓️ Work Days", f"{int(work_days)} Days")
st.divider()

# ==========================================
# 📊 2. Main Visualizations (Tabs)
# ==========================================
tab_util, tab_oee, tab_donut, tab_avail = st.tabs(["📊 Capacity Utilization", "⚡ Efficiency (OEE) Grouping", "🍩 Detailed Breakdown", "📋 สรุปพื้นที่ว่าง (Available Capacity)"])

with tab_util:
    st.markdown("#### อัตราการใช้กำลังการผลิตเครื่องจักร (Utilization %)")
    fig_bar = go.Figure()
    bar_colors = ['#ef4444' if val > 100 else '#3b82f6' for val in cfg['Utilization (%)']]
    
    fig_bar.add_trace(go.Bar(
        x=cfg['Machine Type'], y=cfg['Utilization (%)'], marker_color=bar_colors, name="Utilization (%)",
        text=cfg['Utilization (%)'].apply(lambda x: f'{x:.1f}%'), textposition='outside', textfont=dict(color='#0f172a', size=12),
        hovertemplate="<b>%{x}</b><br>Utilization: %{y:.1f}%<extra></extra>"
    ))
    fig_bar.add_hline(y=100, line_dash="dash", line_color="#ef4444", line_width=2, annotation_text="Maximum Capacity (100%)", annotation_font=dict(color="#ef4444", size=12))
    
    fig_bar.update_layout(height=450, margin=dict(t=40, b=50, l=10, r=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
    fig_bar.update_yaxes(title_text="Utilization (%)", gridcolor='#e2e8f0', rangemode='tozero')
    st.plotly_chart(fig_bar, use_container_width=True)

with tab_oee:
    st.markdown("#### ประสิทธิภาพเครื่องจักร OEE (แยกตามกลุ่มเครื่อง)")
    st.caption("เปรียบเทียบค่าความพร้อมการทำงาน (OEE%) ที่ตั้งไว้สำหรับเครื่องแต่ละประเภท")
    
    cfg_oee = cfg.sort_values(by='OEE (%)', ascending=True)
    fig_oee = go.Figure(go.Bar(
        x=cfg_oee['OEE (%)'], y=cfg_oee['Machine Type'], orientation='h',
        marker=dict(color=cfg_oee['OEE (%)'], colorscale='Teal', showscale=False),
        text=cfg_oee['OEE (%)'].apply(lambda x: f'{x:.0f}%'), textposition='inside', textfont=dict(color='white', size=14)
    ))
    fig_oee.add_vline(x=85, line_dash="dot", line_color="#f59e0b", line_width=2, annotation_text="Target 85%", annotation_position="top right")
    fig_oee.update_layout(height=500, margin=dict(l=10, r=20, t=30, b=30), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(range=[0, 110], gridcolor='#e2e8f0'))
    st.plotly_chart(fig_oee, use_container_width=True)

with tab_donut:
    col_d1, col_d2 = st.columns([1, 3])
    with col_d1:
        st.markdown("##### 🍩 Overall Mix")
        selected_machines = st.multiselect("Filter Machines:", options=cfg['Machine Type'].tolist(), default=cfg['Machine Type'].tolist(), label_visibility="collapsed")
        if selected_machines:
            f_cfg = cfg[cfg['Machine Type'].isin(selected_machines)]
            f_util = (f_cfg['Req_Hours'].sum() / f_cfg['Available Hours'].sum() * 100) if f_cfg['Available Hours'].sum() > 0 else 0
            
            fig = go.Figure(data=[go.Pie(labels=['Used', 'Free'], values=[min(f_util, 100), max(100 - min(f_util, 100), 0)], hole=0.7, marker=dict(colors=["#ef4444" if f_util>100 else "#3b82f6", '#f1f5f9']), textinfo='none')])
            fig.add_annotation(text=f"<b>{f_util:.1f}%</b>", x=0.5, y=0.5, font_size=24, font_color="#0f172a", showarrow=False)
            fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=250, paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    
    with col_d2:
        st.markdown("##### 🍩 Individual breakdown")
        num_cols = 4
        rows = [cfg.iloc[i:i + num_cols] for i in range(0, len(cfg), num_cols)]
        for row_df in rows:
            cols = st.columns(num_cols)
            for idx, (_, data) in enumerate(row_df.iterrows()):
                with cols[idx]:
                    u_val = data['Utilization (%)']
                    short_name = data['Machine Type'][:20] + ".." if len(data['Machine Type']) > 20 else data['Machine Type']
                    st.markdown(f"<div style='text-align:center; font-size:12px; font-weight:600;'>{short_name}</div>", unsafe_allow_html=True)
                    
                    fig2 = go.Figure(data=[go.Pie(labels=['Used', 'Free'], values=[min(u_val, 100), max(100 - min(u_val, 100), 0)], hole=0.7, marker=dict(colors=["#ef4444" if u_val>100 else "#10b981", '#f1f5f9']), textinfo='none')])
                    fig2.add_annotation(text=f"<b>{u_val:.0f}%</b>", x=0.5, y=0.5, font_size=16, font_color="#0f172a", showarrow=False)
                    fig2.update_layout(showlegend=False, margin=dict(t=5, b=5, l=5, r=5), height=140, paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig2, use_container_width=True, key=f"d_{data['Machine Type']}")

with tab_avail:
    col_title_avail, col_toggle = st.columns([3, 1])
    with col_title_avail:
        st.markdown("#### 📋 สรุปพื้นที่ว่างรองรับงานใหม่ (Available Capacity Report)")
        st.caption("กราฟและตารางเพื่อประเมินความสามารถในการรับ New Part หรือ Order แทรก")
    
    with col_toggle:
        simulate_max = st.toggle("🚀 จำลองสถานการณ์: เดินเครื่องทั้งหมด (ตั้งเปิดใช้ = มีทั้งหมด)", value=False)
    
    mock_usable = pd.Series(cfg['Total Machines'] if simulate_max else cfg['Usable Machines'])
    mock_avail_hrs = pd.Series(mock_usable * cfg['Capacity_Per_Machine'])
    mock_util = pd.Series(np.where(mock_avail_hrs > 0, (cfg['Req_Hours'] / mock_avail_hrs) * 100.0, 0.0), index=cfg.index)

    df_avail = pd.DataFrame({
        'Machine Type': cfg['Machine Type'],
        'ตั้งเปิดใช้ (เครื่อง)': mock_usable,
        'ใช้ไปจริง (เครื่อง)': cfg['Req_Machines'],
        'ใช้ไป (%)': mock_util,
        'เหลือว่าง (เครื่อง)': (mock_usable - cfg['Req_Machines']).clip(lower=0),
        'เหลือว่าง (%)': (100.0 - mock_util).clip(lower=0),
        'รับงานเพิ่มได้อีก (ชั่วโมง)': (mock_avail_hrs - cfg['Req_Hours']).clip(lower=0)
    })
    df_avail = df_avail.sort_values(by='รับงานเพิ่มได้อีก (ชั่วโมง)', ascending=False)
    
    # 📌 อัปเดต: กราฟ Stacked Bar (รวม) แบบ 2 แกน พร้อมกราฟเส้น % เหลือว่าง
    st.markdown("##### 📊 กราฟแสดงสัดส่วนเครื่องทั้งหมด (% เหลือใช้)")
    
    fig_avail = make_subplots(specs=[[{"secondary_y": True}]])
    
    # 1. แท่ง "ใช้ไปแล้ว"
    fig_avail.add_trace(go.Bar(
        x=df_avail['Machine Type'], y=df_avail['ใช้ไปจริง (เครื่อง)'], 
        name='ใช้ไปแล้ว (เครื่อง)', marker_color='#3b82f6',
        text=df_avail['ใช้ไปจริง (เครื่อง)'].apply(lambda x: f'{x:.1f}'), textposition='inside',
        hovertemplate="<b>%{x}</b><br>ใช้ไปแล้ว: %{y:.1f} เครื่อง<extra></extra>"
    ), secondary_y=False)
    
    # 2. แท่ง "เหลือว่าง" (นำไปซ้อนทับกัน จะได้ความสูงเท่ากับจำนวนเครื่องที่เปิดใช้ทั้งหมด)
    fig_avail.add_trace(go.Bar(
        x=df_avail['Machine Type'], y=df_avail['เหลือว่าง (เครื่อง)'], 
        name='เหลือว่าง (เครื่อง)', marker_color='#10b981',
        text=df_avail['เหลือว่าง (เครื่อง)'].apply(lambda x: f'{x:.1f}' if x >= 0.1 else ''), textposition='inside',
        hovertemplate="<b>%{x}</b><br>เหลือว่าง: %{y:.1f} เครื่อง<extra></extra>"
    ), secondary_y=False)
    
    # 3. กราฟเส้นแสดง "เปอร์เซ็นต์พื้นที่เหลือว่าง" (แกน Y ฝั่งขวา)
    fig_avail.add_trace(go.Scatter(
        x=df_avail['Machine Type'], y=df_avail['เหลือว่าง (%)'],
        name='% เหลือว่าง', mode='lines+markers',
        line=dict(color='#f59e0b', width=3, shape='spline'),
        marker=dict(size=8, symbol='circle', line=dict(width=1, color='white')),
        text=df_avail['เหลือว่าง (%)'].apply(lambda x: f'{x:.1f}%'), textposition='top center',
        hovertemplate="<b>%{x}</b><br>เหลือว่าง: %{y:.1f}%<extra></extra>"
    ), secondary_y=True)
    
    fig_avail.update_layout(
        barmode='stack', height=450, margin=dict(t=20, b=50, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
        hovermode="x unified"
    )
    
    fig_avail.update_yaxes(title_text="จำนวนเครื่อง (Units)", gridcolor='#e2e8f0', secondary_y=False)
    fig_avail.update_yaxes(title_text="เปอร์เซ็นต์เหลือว่าง (%)", showgrid=False, secondary_y=True, range=[0, 110])
    
    st.plotly_chart(fig_avail, use_container_width=True)

    # 📌 ตารางสรุปตัวเลข
    st.markdown("##### 🧮 ตารางสรุปตัวเลขโดยละเอียด")
    def highlight_avail(row):
        color = '#15803d' if row['เหลือว่าง (%)'] > 20 else ('#b91c1c' if row['เหลือว่าง (%)'] == 0 else '#0f172a')
        return [f'color: {color}; font-weight: 600' if i >= 4 else '' for i in range(len(row))]

    st.dataframe(
        df_avail.style.format({
            'ตั้งเปิดใช้ (เครื่อง)': '{:.0f}', 'ใช้ไปจริง (เครื่อง)': '{:.1f}', 'ใช้ไป (%)': '{:.1f}%',
            'เหลือว่าง (เครื่อง)': '{:.1f}', 'เหลือว่าง (%)': '{:.1f}%', 'รับงานเพิ่มได้อีก (ชั่วโมง)': '{:,.0f} ชม.'
        }).apply(highlight_avail, axis=1),
        use_container_width=True, hide_index=True, height=350
    )

st.divider()

# ==========================================
# 🏆 3. Rankings & Analytics 
# ==========================================
st.markdown("### 🏆 จัดอันดับสถานะเครื่องจักร (Machine Rankings)")

cfg_sorted_util = cfg[cfg['Available Hours'] > 0].sort_values(by='Utilization (%)', ascending=False)
top_5_worst = cfg_sorted_util.head(5) 
top_5_best = cfg_sorted_util.tail(5).sort_values(by='Utilization (%)', ascending=True)

col_rank1, col_rank2 = st.columns(2)

with col_rank1:
    st.markdown("<div style='background-color:#fee2e2; padding:10px; border-radius:8px;'><h4 style='color:#b91c1c; margin:0;'>🔴 Top 5 เครื่องที่ทำงานมากที่สุด (Overloaded)</h4></div>", unsafe_allow_html=True)
    st.caption("เครื่องจักรที่มีอัตรา Utilization สูงสุด (เสี่ยงคอขวด / ผลิตไม่ทัน)")
    
    fig_t5 = px.bar(top_5_worst, x='Utilization (%)', y='Machine Type', orientation='h', text_auto='.1f', color_discrete_sequence=['#ef4444'])
    fig_t5.update_layout(yaxis={'categoryorder':'total ascending'}, height=300, margin=dict(l=10, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor='#e2e8f0'))
    st.plotly_chart(fig_t5, use_container_width=True)

with col_rank2:
    st.markdown("<div style='background-color:#dcfce3; padding:10px; border-radius:8px;'><h4 style='color:#15803d; margin:0;'>🟢 Top 5 เครื่องที่น้อยที่สุด (Underutilized)</h4></div>", unsafe_allow_html=True)
    st.caption("เครื่องจักรที่มีอัตรา Utilization ต่ำที่สุด (มีพื้นที่รองรับงานเพิ่มได้)")
    
    fig_b5 = px.bar(top_5_best, x='Utilization (%)', y='Machine Type', orientation='h', text_auto='.1f', color_discrete_sequence=['#10b981'])
    fig_b5.update_layout(yaxis={'categoryorder':'total descending'}, height=300, margin=dict(l=10, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor='#e2e8f0', range=[0, 100]))
    st.plotly_chart(fig_b5, use_container_width=True)

st.divider()

# ==========================================
# 4. Deep Dive Part Analysis
# ==========================================
col_deep1, col_deep2 = st.columns(2)

with col_deep1:
    st.markdown("#### 📦 Top 5 Parts ที่ใช้เวลาผลิตสูงสุด (แยกตามเครื่อง)")
    df_valid = df_detail[df_detail['Req_Hours'] > 0].copy()
    top_5_parts = df_valid.sort_values(['Machine Type', 'Req_Hours'], ascending=[True, False]).groupby('Machine Type').head(5)
    machine_types = sorted(top_5_parts['Machine Type'].unique(), key=get_sort_priority)
    
    if machine_types:
        tabs = st.tabs([mt[:12] + ".." if len(mt) > 12 else mt for mt in machine_types])
        for i, m_type in enumerate(machine_types):
            with tabs[i]:
                m_df = top_5_parts[top_5_parts['Machine Type'] == m_type][['Material', 'Description', 'Req_Qty', 'Req_Hours']]
                st.dataframe(m_df.style.format({'Req_Qty': '{:,.0f}', 'Req_Hours': '{:,.1f} hr'}), use_container_width=True, hide_index=True)

with col_deep2:
    st.markdown("#### 📈 Parts Trend (ยอดสั่งผลิตแกว่งตัว > 30%)")
    df_trend = df_detail[['Machine Type', 'Material', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Req_Hours']].drop_duplicates(subset=['Material']).copy()
    df_trend['% Change'] = df_trend.apply(lambda r: ((r['Max_N1'] - r['Max_N_minus_1']) / r['Max_N_minus_1']) * 100.0 if r['Max_N_minus_1'] > 0 else (100.0 if r['Max_N1']>0 else 0), axis=1)
    
    df_up = df_trend[df_trend['% Change'] > 30].sort_values(by=['Req_Hours'], ascending=False).head(5)
    df_down = df_trend[df_trend['% Change'] < -30].sort_values(by=['Req_Hours'], ascending=False).head(5)
    
    def style_change(val): return f'color: {"#15803d" if val > 0 else "#b91c1c"}; font-weight: bold'
    
    t_up, t_down = st.tabs(["🚀 ขึ้น (Up Trend)", "📉 ลง (Down Trend)"])
    cols_disp = ['Material', 'Max_N_minus_1', 'Max_N', 'Max_N1', '% Change', 'Req_Hours']
    with t_up:
        st.dataframe(df_up[cols_disp].style.format({'Max_N_minus_1':'{:,.0f}', 'Max_N':'{:,.0f}', 'Max_N1':'{:,.0f}', '% Change':'{:+.1f}%', 'Req_Hours':'{:.1f}'}).map(style_change, subset=['% Change']), hide_index=True, use_container_width=True)
    with t_down:
        st.dataframe(df_down[cols_disp].style.format({'Max_N_minus_1':'{:,.0f}', 'Max_N':'{:,.0f}', 'Max_N1':'{:,.0f}', '% Change':'{:+.1f}%', 'Req_Hours':'{:.1f}'}).map(style_change, subset=['% Change']), hide_index=True, use_container_width=True)

# ==========================================
# 📌 GitHub Save Trigger
# ==========================================
if trigger_save:
    settings_data_left = {"work_days": int(work_days), "wip_reduction_pct": float(wip_reduction_pct)}
    with open(data_settings_file, 'w', encoding='utf-8') as f: json.dump(settings_data_left, f)
        
    new_oee, new_use, new_shift, new_ot = {}, {}, {}, {}
    for mt in cfg['Machine Type']:
        mt_str = str(mt)
        new_use[mt_str], new_shift[mt_str], new_oee[mt_str], new_ot[mt_str] = st.session_state.get(f"use_{mt_str}",0), st.session_state.get(f"shf_{mt_str}",3.0), st.session_state.get(f"oee_{mt_str}",85), st.session_state.get(f"ot_{mt_str}",0)
    settings_data_table = {'oee_dict': new_oee, 'use_dict': new_use, 'shift_dict': new_shift, 'ot_dict': new_ot}
    with open(settings_file, 'w', encoding='utf-8') as f: json.dump(settings_data_table, f, ensure_ascii=False, indent=4)
        
    if GITHUB_ENABLED:
        with st.spinner("☁️ กำลังบันทึกขึ้น GitHub..."):
            ok_left, msg_left = gh_put_file(f"{GITHUB_DATA_DIR}/data_settings.json", json.dumps(settings_data_left, ensure_ascii=False, indent=4).encode('utf-8'), "Auto-save left panel")
            ok_table, msg_table = gh_put_file(f"{GITHUB_DATA_DIR}/machine_settings.json", json.dumps(settings_data_table, ensure_ascii=False, indent=4).encode('utf-8'), "Auto-save machine settings")
        if ok_table and ok_left: st.toast("✅ บันทึกข้อมูลและพารามิเตอร์ทั้งหมดลง GitHub เรียบร้อยแล้ว!")
        else: st.error(f"⚠️ GitHub Error: {msg_table} / {msg_left}")
    else: st.toast("✅ บันทึกข้อมูลและพารามิเตอร์ทั้งหมดลง Local เรียบร้อยแล้ว!")