import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit.components.v1 as components
import os
import re
import io
import json

# ==========================================
# Page Configuration
# ==========================================
st.set_page_config(page_title="Press Capacity Dashboard", page_icon="🏭", layout="wide")

# ==========================================
# CSS Styling (Clean & Modern Design)
# ==========================================
st.markdown("""
<style>
    /* ปรับแต่งกล่อง KPI Cards ให้ดูสะอาดตาและมีมิติ */
    [data-testid="stMetric"] {
        background-color: #ffffff;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0px 4px 6px -1px rgba(0,0,0,0.1);
        border: 1px solid #e0e0e0;
        border-left: 5px solid #3b82f6; 
    }
    
    div[data-testid="column"]:nth-child(1) [data-testid="stMetric"] { border-left-color: #8b5cf6; } 
    div[data-testid="column"]:nth-child(2) [data-testid="stMetric"] { border-left-color: #10b981; }
    div[data-testid="column"]:nth-child(3) [data-testid="stMetric"] { border-left-color: #f59e0b; }
    div[data-testid="column"]:nth-child(4) [data-testid="stMetric"] { border-left-color: #ef4444; }

    @media print {
        .stPopover { display: none !important; }
        .stExpander { display: none !important; }
        header { display: none !important; }
    }
    
    div[data-testid="stVerticalBlock"] > div {
        padding-top: 0.1rem;
        padding-bottom: 0.1rem;
    }
    
    ::-webkit-scrollbar {
        height: 6px;
    }
    ::-webkit-scrollbar-thumb {
        background: #cbd5e1; 
        border-radius: 10px;
    }
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

        wip_fg['Material'] = wip_fg['Material'].astype(str)
        wip_fg['Material'] = wip_fg['Material'].str.replace(r';A1$', '', regex=True)
        wip_fg['Material'] = wip_fg['Material'].str.replace(r';A2$', '', regex=True)
        wip_agg = wip_fg.groupby('Material', as_index=False)['Unrestricted'].sum()
        
        fo_cols = [c for c in data_fo.columns if 'FO' in str(c).upper() and '(PCS)' in str(c).upper() and re.search(r'\d{2}\.\d{4}', str(c))]
        if len(fo_cols) >= 3:
            fo_cols.sort(key=lambda x: pd.to_datetime(re.search(r'\d{2}\.\d{4}', x).group(), format='%m.%Y'))
            m_minus_1_str = re.search(r'\d{2}\.\d{4}', fo_cols[-3]).group()
            m_n_str = re.search(r'\d{2}\.\d{4}', fo_cols[-2]).group()
            m_n1_str = re.search(r'\d{2}\.\d{4}', fo_cols[-1]).group()
        else:
            m_minus_1_str, m_n_str, m_n1_str = '07.2026', '08.2026', '09.2026'

        def get_valid_col(df, kw1, kw2, m_str, fallback_name):
            cols = [c for c in df.columns if kw1 in str(c).upper() and kw2 in str(c).upper() and m_str in str(c)]
            if cols and cols[0] in df.columns:
                return cols[0]
            df[fallback_name] = 0
            return fallback_name

        fo_n_minus_1_col = get_valid_col(data_fo, 'FO', '(PCS)', m_minus_1_str, f'FO_PCS_{m_minus_1_str}')
        ord_n_minus_1_col = get_valid_col(data_fo, 'ORD', '(PCS)', m_minus_1_str, f'ORD_PCS_{m_minus_1_str}')
        fo_n_col = get_valid_col(data_fo, 'FO', '(PCS)', m_n_str, f'FO_PCS_{m_n_str}')
        ord_n_col = get_valid_col(data_fo, 'ORD', '(PCS)', m_n_str, f'ORD_PCS_{m_n_str}')
        fo_n1_col = get_valid_col(data_fo, 'FO', '(PCS)', m_n1_str, f'FO_PCS_{m_n1_str}')
        ord_n1_col = get_valid_col(data_fo, 'ORD', '(PCS)', m_n1_str, f'ORD_PCS_{m_n1_str}')

        df = data_fo[['Material', 'Description', fo_n_minus_1_col, ord_n_minus_1_col, fo_n_col, ord_n_col, fo_n1_col, ord_n1_col]].copy()
        
        df['Max_N_minus_1'] = df[[fo_n_minus_1_col, ord_n_minus_1_col]].max(axis=1).fillna(0)
        df['Max_N'] = df[[fo_n_col, ord_n_col]].max(axis=1).fillna(0)
        df['Max_N1'] = df[[fo_n1_col, ord_n1_col]].max(axis=1).fillna(0)
        
        if len(data_fo.columns) >= 15:
            amt_series = pd.to_numeric(data_fo.iloc[:, 14], errors='coerce').fillna(0)
            total_sales_n = amt_series.sum()
            df['Max_N_Amt'] = amt_series
        else:
            df['Max_N_Amt'] = 0
            total_sales_n = 0
        
        df = pd.merge(df, wip_agg, on='Material', how='left').fillna(0)
        df['Unrestricted'] = df['Unrestricted'] * (1 - (wip_reduction_pct / 100.0))
        df['Req_Qty'] = df['Max_N'] + (df['Max_N1'] * 0.3) - df['Unrestricted']
        df['Req_Qty'] = df['Req_Qty'].apply(lambda x: x if x > 0 else 0)

        df = pd.merge(df, fg_semi[['Material', 'Semi Part']], on='Material', how='left')
        cap_unique = capacity.drop_duplicates(subset=['Semi Part'])
        df = pd.merge(df, cap_unique[['Semi Part', 'Machine Type', 'Cap/1กะ  (pc)', 'กะละ (hr)']], on='Semi Part', how='left')

        df['Cap/1กะ  (pc)'] = df['Cap/1กะ  (pc)'].replace(0, np.nan)
        df['Req_Hours'] = (df['Req_Qty'] / df['Cap/1กะ  (pc)']) * df['กะละ (hr)']
        df['Req_Hours'] = df['Req_Hours'].fillna(0)

        req_by_mach = df.groupby('Machine Type', as_index=False)['Req_Hours'].sum()
        mach_summary = mc_data[['Machine Type', 'จำนวนเครื่องทั้งหมด', 'จำนวนเครื่องที่ให้ใช้ได้']].copy().dropna(subset=['Machine Type'])
        mach_summary.rename(columns={'จำนวนเครื่องทั้งหมด': 'Total Machines', 'จำนวนเครื่องที่ให้ใช้ได้': 'Usable Machines'}, inplace=True)
        mach_summary = pd.merge(mach_summary, req_by_mach, on='Machine Type', how='left').fillna(0)

        df_detail = df[['Material', 'Description', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Max_N_Amt', 'Req_Qty', 'Semi Part', 'Machine Type', 'Req_Hours']].copy()
        
        return mach_summary, df_detail, total_sales_n, None
    except Exception as e:
        return None, None, 0, f"เกิดข้อผิดพลาดในการประมวลผล: {str(e)}"

# ==========================================
# Sidebar: Upload & Global Params
# ==========================================
db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data base.xlsx')
saved_up_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_data_upload.xlsx')
settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'machine_settings.json')
params_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'params_settings.json')

# 📌 โหลดค่าพารามิเตอร์ที่เคยเซฟไว้
saved_params = {}
if os.path.exists(params_file):
    try:
        with open(params_file, 'r', encoding='utf-8') as f:
            saved_params = json.load(f)
    except:
        pass

init_work_days = int(saved_params.get('work_days', 23))
init_wip_reduction = float(saved_params.get('wip_reduction_pct', 0.0))

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2823/2823512.png", width=80)
    
    st.markdown("### 📂 1. อัปโหลดข้อมูลประจำเดือน")
    uploaded_up = st.file_uploader("ไฟล์ Data Upload (.xlsx)", type=["xlsx", "xls"])
    
    st.markdown("### ⚙️ 2. ค่าพารามิเตอร์เริ่มต้น")
    work_days = st.number_input("วันทำงาน (วัน/เดือน)", min_value=1, max_value=31, value=init_work_days)
    wip_reduction_pct = st.number_input("ปรับลด % WIP/FG ปลายเดือน", min_value=0.0, max_value=100.0, value=init_wip_reduction, step=1.0)
    
    st.markdown("---")

    # 📌 ระบบจำไฟล์ข้อมูล + พารามิเตอร์ (รวมกันในปุ่มเดียว)
    active_file = None
    if uploaded_up is not None:
        active_file = uploaded_up
        if st.button("💾 บันทึกข้อมูลและตั้งค่านี้ไว้ใช้รอบหน้า", use_container_width=True):
            # 1. เซฟไฟล์ Excel
            with open(saved_up_file, "wb") as f:
                f.write(uploaded_up.getbuffer())
            
            # 2. เซฟพารามิเตอร์
            params_data = {'work_days': work_days, 'wip_reduction_pct': wip_reduction_pct}
            with open(params_file, 'w', encoding='utf-8') as f:
                json.dump(params_data, f, ensure_ascii=False, indent=4)
                
            st.success("✅ บันทึกไฟล์และค่าพารามิเตอร์เรียบร้อย!")
        st.caption("🟢 กำลังแสดงผลจาก: **ไฟล์ที่เพิ่งอัปโหลด**")
        
    elif os.path.exists(saved_up_file):
        active_file = saved_up_file
        st.caption("📌 กำลังแสดงผลจาก: **ไฟล์ที่บันทึกไว้ล่าสุด**")
        
        # เพิ่มปุ่มกดเซฟเฉพาะพารามิเตอร์ (กรณีที่ใช้ไฟล์เดิมแต่อยากเปลี่ยนพารามิเตอร์)
        if st.button("💾 บันทึกเฉพาะค่าพารามิเตอร์ใหม่", use_container_width=True):
            params_data = {'work_days': work_days, 'wip_reduction_pct': wip_reduction_pct}
            with open(params_file, 'w', encoding='utf-8') as f:
                json.dump(params_data, f, ensure_ascii=False, indent=4)
            st.success("✅ บันทึกค่าพารามิเตอร์ใหม่เรียบร้อย!")
            
        if st.button("🗑️ ล้างข้อมูลไฟล์ที่บันทึกไว้", use_container_width=True):
            os.remove(saved_up_file)
            st.rerun()

# ==========================================
# Header & Placeholder for Export Button
# ==========================================
col_title, col_export = st.columns([4, 1])
with col_title:
    st.markdown("## 📊 Press Capacity Utilization Dashboard")
    st.caption("ระบบวิเคราะห์ยอดการผลิตและคำนวณอัตราการใช้กำลังการผลิตของเครื่องจักร Press")

export_placeholder = col_export.empty()

if not os.path.exists(db_file):
    st.error("⚠️ ไม่พบไฟล์ระบบ 'data base.xlsx' กรุณานำไฟล์ไปวางไว้ในโฟลเดอร์เดียวกับโปรแกรม")
    st.stop()
    
if active_file is None:
    st.info("👋 ยินดีต้อนรับ! กรุณาอัปโหลดไฟล์ **data upload.xlsx** ประจำเดือนที่แถบด้านซ้ายมือ เพื่อเริ่มต้นวิเคราะห์ข้อมูล")
    st.stop()

mach_summary, df_detail, total_sales_n, err = load_and_process(db_file, active_file, wip_reduction_pct)
if err:
    st.error(err)
    st.stop()

# ==========================================
# 1. Custom Sorting & Load Saved Settings
# ==========================================
cfg = mach_summary.copy()
cfg['Hours/Shift'] = 7.0

def get_sort_priority(machine_type):
    mt_upper = str(machine_type).upper()
    if "INJ" in mt_upper: return 1
    elif "PRESS" in mt_upper: return 2
    elif "VACUUM" in mt_upper: return 3
    else: return 4

cfg['Sort_Priority'] = cfg['Machine Type'].apply(get_sort_priority)
cfg = cfg.sort_values(by=['Sort_Priority', 'Machine Type']).reset_index(drop=True)

saved_settings = {}
if os.path.exists(settings_file):
    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            saved_settings = json.load(f)
    except:
        pass

saved_oee = saved_settings.get('oee_dict', {})
saved_use = saved_settings.get('use_dict', {})
saved_shift = saved_settings.get('shift_dict', {})

if "oee_dict" not in st.session_state:
    st.session_state.oee_dict = {mt: int(saved_oee.get(mt, 85)) for mt in cfg['Machine Type']}
if "use_dict" not in st.session_state:
    st.session_state.use_dict = {row['Machine Type']: int(saved_use.get(row['Machine Type'], row['Usable Machines'])) for _, row in cfg.iterrows()}
if "shift_dict" not in st.session_state:
    st.session_state.shift_dict = {row['Machine Type']: float(saved_shift.get(row['Machine Type'], 3.0)) for _, row in cfg.iterrows()}

# ==========================================
# 2. KPI Cards
# ==========================================
st.markdown("### 📈 สรุปผลการดำเนินงาน (Overview)")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
ph1 = kpi1.empty()
ph2 = kpi2.empty()
ph3 = kpi3.empty()
ph4 = kpi4.empty()

st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

kpi5, kpi6, kpi7, kpi8 = st.columns(4)
ph5 = kpi5.empty()
ph6 = kpi6.empty()
ph7 = kpi7.empty()
ph8 = kpi8.empty()

st.divider()

# ==========================================
# 3. Side-by-Side: Easy Adjust & Bar Chart
# ==========================================
col_adj, col_chart = st.columns([1.5, 2.5])
over_machines_alerts = []

with col_adj:
    with st.expander("🎛️ แผงตั้งค่า กะและ OEE รายเครื่องจักร (คลิกเพื่อเปิด/ปิด)", expanded=False):
        
        st.info("💡 **กดปุ่ม + / -** ในช่องเพื่อเพิ่มลดค่า และกด **บันทึกเป็นค่าเริ่มต้น** เพื่อจำค่าไว้ใช้ครั้งหน้า")
        
        b_col1, b_col2, b_col3 = st.columns([1.5, 1, 1.2])
        with b_col1:
            bulk_oee = st.number_input("🔄 ปรับ OEE ทุกเครื่อง (%)", value=85, min_value=1, max_value=100, step=1, format="%d")
        with b_col2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("✨ อัปเดต", use_container_width=True):
                for mt in cfg['Machine Type']:
                    st.session_state.oee_dict[mt] = bulk_oee
                st.rerun() 
        with b_col3:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("💾 บันทึกค่า", use_container_width=True, help="บันทึกค่าที่ตั้งไว้ใช้ในครั้งต่อไป"):
                settings_data = {
                    'oee_dict': st.session_state.oee_dict,
                    'use_dict': st.session_state.use_dict,
                    'shift_dict': st.session_state.shift_dict
                }
                with open(settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings_data, f, ensure_ascii=False, indent=4)
                st.toast("✅ บันทึกค่ากะและ OEE เรียบร้อยแล้ว!")
        
        st.markdown("---")
        
        h1, h2, h3, h4, h5 = st.columns([3.5, 1, 1.2, 1.2, 1.2])
        h1.markdown("**Machine**")
        h2.markdown("**<div style='text-align:center;'>มี</div>**", unsafe_allow_html=True)
        h3.markdown("**<div style='text-align:center;'>ใช้</div>**", unsafe_allow_html=True)
        h4.markdown("**<div style='text-align:center;'>กะ</div>**", unsafe_allow_html=True)
        h5.markdown("**<div style='text-align:center;'>OEE%</div>**", unsafe_allow_html=True)
        
        with st.container(height=350):
            for idx, row in cfg.iterrows():
                mt = row['Machine Type']
                total_mach = int(row['Total Machines'])
                
                c1, c2, c3, c4, c5 = st.columns([3.5, 1, 1.2, 1.2, 1.2])
                
                c1.markdown(f"<div style='font-size: 13px; margin-top: 8px; white-space: nowrap; overflow-x: auto; padding-bottom: 2px;' title='{mt}'><b>{mt}</b></div>", unsafe_allow_html=True)
                c2.markdown(f"<div style='font-size: 13px; margin-top: 8px; text-align: center;'>{total_mach}</div>", unsafe_allow_html=True)
                
                current_use = st.session_state.use_dict.get(mt, int(row['Usable Machines']))
                use_val = c3.number_input("ใช้", min_value=0, value=int(current_use), step=1, format="%d", key=f"u_{idx}", label_visibility="collapsed")
                
                shift_options = [1.0, 1.5, 2.0, 3.0]
                current_shift = st.session_state.shift_dict.get(mt, 3.0)
                shift_val = c4.selectbox("กะ", shift_options, index=shift_options.index(current_shift), key=f"s_{idx}", label_visibility="collapsed")
                
                current_oee = st.session_state.oee_dict.get(mt, 85)
                oee_val = c5.number_input("OEE", min_value=1, max_value=100, value=int(current_oee), step=1, format="%d", key=f"o_{idx}", label_visibility="collapsed")
                
                st.session_state.use_dict[mt] = use_val
                st.session_state.shift_dict[mt] = shift_val
                st.session_state.oee_dict[mt] = oee_val
                
                cfg.at[idx, 'Usable Machines'] = use_val
                cfg.at[idx, 'Shifts/Day'] = shift_val
                cfg.at[idx, 'OEE (%)'] = oee_val
                
                if use_val > total_mach:
                    short_mt = mt[:18] + ".." if len(mt) > 18 else mt
                    over_machines_alerts.append(f"- **{short_mt}** (มี {total_mach} แต่ตั้ง {int(use_val)})")

        if over_machines_alerts:
            st.error("⚠️ **ใช้งานเครื่องจักรเกินจำนวนที่มี:**\n" + "\n".join(over_machines_alerts))

# --- คำนวณ Capacity หลังรับค่าจากแผงควบคุม ---
cfg['Capacity_Per_Machine'] = (cfg['Shifts/Day'] * cfg['Hours/Shift'] * work_days * (cfg['OEE (%)'] / 100.0))
cfg['Available Hours'] = cfg['Usable Machines'] * cfg['Capacity_Per_Machine']
cfg['Utilization (%)'] = np.where(cfg['Available Hours'] > 0, (cfg['Req_Hours'] / cfg['Available Hours']) * 100.0, 0.0)
cfg['Req_Machines'] = np.where(cfg['Capacity_Per_Machine'] > 0, cfg['Req_Hours'] / cfg['Capacity_Per_Machine'], 0.0)

# ==========================================
# 📌 ปุ่ม Export (ดึงค่าที่อัปเดตแล้วมาสร้างไฟล์)
# ==========================================
with export_placeholder.container():
    st.write("")
    with st.popover("📥 Export Report"):
        st.markdown("**1. ส่งออกข้อมูลเป็น Excel**")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            cfg.to_excel(writer, sheet_name='Machine_Summary', index=False)
            df_detail.to_excel(writer, sheet_name='Part_Details', index=False)
        excel_data = output.getvalue()
        
        st.download_button(
            label="💾 ดาวน์โหลด Data (.xlsx)",
            data=excel_data,
            file_name="Capacity_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        st.divider()
        st.markdown("**2. ส่งออกเป็น PDF**")
        components.html(
            """
            <button onclick="window.parent.print()" style="
                background-color: #3b82f6; border: none; color: white;
                padding: 10px 20px; text-align: center; border-radius: 5px;
                cursor: pointer; width: 100%; font-family: sans-serif;
                font-weight: bold; font-size: 14px;
            ">🖨️ Print / Save as PDF</button>
            <p style="font-size:12px; color:gray; text-align:center; margin-top:10px;">
            * เปิดตัวเลือก <b>'Background graphics'</b> ตอน Print เสมอ
            </p>
            """, height=110
        )

# ==========================================
# เติมค่าให้ KPI Cards 
# ==========================================
total_machines_all = 66
total_req = cfg['Req_Hours'].sum()
total_avail = cfg['Available Hours'].sum()
overall_util = (total_req / total_avail) * 100 if total_avail > 0 else 0
over_cap_count = len(cfg[cfg['Utilization (%)'] > 100])
total_req_machines = cfg['Req_Machines'].sum()

ph1.metric("⚙️ เครื่องพร้อมใช้", f"{total_machines_all} เครื่อง")
ph2.metric("💡 เครื่องพร้อมใช้ (ตั้งค่า)", f"{int(cfg['Usable Machines'].sum())} เครื่อง")
ph3.metric("🔥 เครื่องที่ต้องใช้จริง", f"{total_req_machines:.1f} เครื่อง")
ph4.metric("⏱️ ชั่วโมงผลิตรวม", f"{total_req:,.0f} ชม.")

ph5.metric("📈 Util. เฉลี่ยรวม", f"{overall_util:.1f}%")
ph6.metric("⚠️ Over Capacity", f"{over_cap_count} ประเภท", delta="Over Capacity" if over_cap_count > 0 else "ปกติ", delta_color="inverse")
ph7.metric("💰 ยอดขายเดือน N (Amt)", f"฿ {total_sales_n:,.0f}")
ph8.metric("🗓️ วันทำงาน", f"{int(work_days)} วัน")

with col_chart:
    st.markdown("#### 📊 กราฟวิเคราะห์ Utilization & OEE")
    fig_bar = make_subplots(specs=[[{"secondary_y": True}]])
    bar_colors = ['#ef4444' if val > 100 else '#3b82f6' for val in cfg['Utilization (%)']]
    
    fig_bar.add_trace(go.Bar(
        x=cfg['Machine Type'], y=cfg['Utilization (%)'], marker_color=bar_colors, name="Utilization (%)",
        text=cfg['Utilization (%)'].apply(lambda x: f'{x:.1f}%'), textposition='inside', textfont=dict(color='white'),
        hovertemplate="<b>%{x}</b><br>Utilization: %{y:.1f}%<extra></extra>"
    ), secondary_y=False)
    
    fig_bar.add_trace(go.Scatter(
        x=cfg['Machine Type'], y=cfg['OEE (%)'], mode='lines+markers', name="OEE (%)",
        line=dict(color='#f59e0b', width=3, shape='spline'), 
        marker=dict(size=8, symbol='diamond', line=dict(width=1, color='white')),
        hovertemplate="<b>%{x}</b><br>OEE: %{y:.1f}%<extra></extra>"
    ), secondary_y=True)
    
    fig_bar.add_hline(y=100, line_dash="dash", line_color="#ef4444", line_width=2, 
                      annotation_text="Max Capacity 100%", annotation_position="top left",
                      annotation_font=dict(color="#ef4444", size=12), secondary_y=False)
    
    fig_bar.update_layout(height=450, margin=dict(t=20, b=50, l=0, r=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1), hovermode="x unified")
    
    fig_bar.update_yaxes(title_text="Utilization (%)", gridcolor='rgba(200,200,200,0.2)', secondary_y=False, rangemode='tozero')
    fig_bar.update_yaxes(title_text="OEE (%)", showgrid=False, secondary_y=True, range=[0, 110])
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ==========================================
# 4. Overall & Individual Donut Charts
# ==========================================
col_donut_all, col_donut_ind = st.columns([1, 3])

def create_donut(title, util_val, height=220):
    color = "#ef4444" if util_val > 100 else "#10b981"
    visual_util = min(util_val, 100)
    remaining = max(100 - visual_util, 0)
    
    fig = go.Figure(data=[go.Pie(
        labels=['ใช้งานแล้ว', 'พื้นที่ว่าง'],
        values=[visual_util, remaining], hole=0.65,
        marker=dict(colors=[color, '#e2e8f0']), textinfo='none', hoverinfo='label'
    )])
    
    font_size = 28 if height > 220 else 22
    fig.add_annotation(text=f"<b>{util_val:.1f}%</b>", x=0.5, y=0.5, font_size=font_size, font_color=color, showarrow=False)
    
    layout_args = dict(showlegend=False, margin=dict(t=10, b=10, l=10, r=10), height=height, paper_bgcolor="rgba(0,0,0,0)")
    if title: 
        layout_args['title'] = dict(text=title, x=0.5, font=dict(size=15, color="#1e293b"))
        layout_args['margin']['t'] = 40
    fig.update_layout(**layout_args)
    return fig

with col_donut_all:
    st.markdown("#### 🍩 ภาพรวม (Overall)")
    with st.expander("🔍 กรองเครื่องจักร"):
        selected_machines = st.multiselect("รวมยอด:", options=cfg['Machine Type'].tolist(), default=cfg['Machine Type'].tolist(), label_visibility="collapsed")
    
    if selected_machines:
        filtered_cfg = cfg[cfg['Machine Type'].isin(selected_machines)]
        f_total_req = filtered_cfg['Req_Hours'].sum()
        f_total_avail = filtered_cfg['Available Hours'].sum()
        f_overall_util = (f_total_req / f_total_avail) * 100 if f_total_avail > 0 else 0
        st.plotly_chart(create_donut("Overall Utilization", f_overall_util, height=250), use_container_width=True)
    else:
        st.warning("กรุณาเลือกเครื่องอย่างน้อย 1 ประเภท")

with col_donut_ind:
    st.markdown("#### 🍩 อัตราการใช้เครื่องจักรแยกรายประเภท")
    num_cols = 4
    rows = [cfg.iloc[i:i + num_cols] for i in range(0, len(cfg), num_cols)]
    for row_df in rows:
        cols = st.columns(num_cols)
        for idx, (index, data) in enumerate(row_df.iterrows()):
            with cols[idx]:
                short_name = data['Machine Type'][:25] + ".." if len(data['Machine Type']) > 25 else data['Machine Type']
                st.markdown(f"<div style='text-align: center; font-size: 13px; font-weight: 600; color: #1e293b;'>{short_name}</div>", unsafe_allow_html=True)
                st.plotly_chart(create_donut("", data['Utilization (%)'], height=180), use_container_width=True)

st.divider()

# ==========================================
# 5. Deep Dive Analytics (Top 5 & 3-Month Trends)
# ==========================================
col_deep1, col_deep2 = st.columns(2)

with col_deep1:
    st.markdown("### 🏆 Top 5 Parts ที่ใช้เวลาผลิตสูงสุด")
    st.caption("จัดอันดับชิ้นงานที่ต้องใช้ชั่วโมงเครื่องจักรมากที่สุด แยกตามประเภทเครื่องจักร")
    
    df_valid = df_detail[df_detail['Req_Hours'] > 0].copy()
    top_5_parts = df_valid.sort_values(['Machine Type', 'Req_Hours'], ascending=[True, False]).groupby('Machine Type').head(5)
    machine_types = sorted(top_5_parts['Machine Type'].unique(), key=get_sort_priority)
    
    if machine_types:
        tabs = st.tabs([mt[:12] + ".." if len(mt) > 12 else mt for mt in machine_types])
        for i, m_type in enumerate(machine_types):
            with tabs[i]:
                m_df = top_5_parts[top_5_parts['Machine Type'] == m_type][['Material', 'Description', 'Req_Qty', 'Max_N_Amt', 'Req_Hours']]
                m_df = m_df.rename(columns={'Max_N_Amt': 'ยอดขายเดือน N (Amt)'})
                st.dataframe(m_df.style.format({'Req_Qty': '{:,.0f}', 'ยอดขายเดือน N (Amt)': '{:,.0f}', 'Req_Hours': '{:,.1f} ชม.'}), use_container_width=True, hide_index=True)
    else:
        st.info("ไม่มีข้อมูลชั่วโมงการผลิต")

with col_deep2:
    st.markdown("### 📈 Top 5 Parts (Trend 3 เดือน สวิง > 30%)")
    st.caption("ชิ้นงานที่กินชั่วโมงเครื่องจักรเยอะ (Req_Hours) และมียอดออเดอร์ (Pcs) สวิงเกิน 30%")
    
    df_trend = df_detail[['Machine Type', 'Material', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Req_Hours']].copy().drop_duplicates(subset=['Material'])
    
    def calc_change_3m(row):
        if row['Max_N_minus_1'] == 0:
            return 100.0 if row['Max_N1'] > 0 else 0.0
        return ((row['Max_N1'] - row['Max_N_minus_1']) / row['Max_N_minus_1']) * 100.0
        
    def get_trend_icon(row):
        n_m1, n, n1 = row['Max_N_minus_1'], row['Max_N'], row['Max_N1']
        if n1 > n > n_m1: return "↗️ ขึ้นต่อเนื่อง"
        elif n1 < n < n_m1: return "↘️ ลงต่อเนื่อง"
        elif n1 > n_m1: return "⤴️ ขึ้น (แกว่ง)"
        elif n1 < n_m1: return "⤵️ ลง (แกว่ง)"
        else: return "➡️ คงที่"
    
    df_trend['% Change'] = df_trend.apply(calc_change_3m, axis=1)
    df_trend['Trend'] = df_trend.apply(get_trend_icon, axis=1)
    
    df_up = df_trend[df_trend['% Change'] > 30].sort_values(by=['Req_Hours', '% Change'], ascending=[False, False]).head(8)
    df_down = df_trend[df_trend['% Change'] < -30].sort_values(by=['Req_Hours', '% Change'], ascending=[False, True]).head(8)
    
    def style_change(val):
        color = '#10b981' if val > 0 else '#ef4444' 
        return f'color: {color}; font-weight: bold'
    
    tab_up, tab_down = st.tabs(["🟢 แนวโน้มยอดเพิ่ม (Top 5 Up)", "🔴 แนวโน้มยอดลด (Top 5 Down)"])
    disp_cols = ['Machine Type', 'Material', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Trend', '% Change', 'Req_Hours']
    
    with tab_up:
        if not df_up.empty:
            disp_up = df_up[disp_cols].rename(columns={'Max_N_minus_1': 'Mth N-1 (Pcs)', 'Max_N': 'Mth N (Pcs)', 'Max_N1': 'Mth N+1 (Pcs)'})
            st.dataframe(
                disp_up.style.format({'Mth N-1 (Pcs)': '{:,.0f}', 'Mth N (Pcs)': '{:,.0f}', 'Mth N+1 (Pcs)': '{:,.0f}', '% Change': '{:+.1f}%', 'Req_Hours': '{:,.1f}'})
                       .map(style_change, subset=['% Change']),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("ไม่มี Part ที่ยอดสั่งผลิตเพิ่มขึ้นเกิน 30% ในช่วง 3 เดือน")
            
    with tab_down:
        if not df_down.empty:
            disp_down = df_down[disp_cols].rename(columns={'Max_N_minus_1': 'Mth N-1 (Pcs)', 'Max_N': 'Mth N (Pcs)', 'Max_N1': 'Mth N+1 (Pcs)'})
            st.dataframe(
                disp_down.style.format({'Mth N-1 (Pcs)': '{:,.0f}', 'Mth N (Pcs)': '{:,.0f}', 'Mth N+1 (Pcs)': '{:,.0f}', '% Change': '{:+.1f}%', 'Req_Hours': '{:,.1f}'})
                       .map(style_change, subset=['% Change']),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("ไม่มี Part ที่ยอดสั่งผลิตลดลงเกิน 30% ในช่วง 3 เดือน")