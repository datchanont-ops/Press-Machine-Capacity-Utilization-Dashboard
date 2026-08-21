import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit.components.v1 as components
import os
import re
import io

# ==========================================
# Page Configuration
# ==========================================
st.set_page_config(page_title="Press Capacity Dashboard", page_icon="🏭", layout="wide")

st.markdown("""
<style>
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border: 1px solid #e0e0e0;
        padding: 5% 5% 5% 10%;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        border-left: 4px solid #1f77b4;
    }
    .stSelectbox, .stNumberInput {
        margin-bottom: -15px;
    }
    
    @media print {
        .stPopover { display: none !important; }
        .stExpander { display: none !important; }
        header { display: none !important; }
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
        
        fo_cols = [c for c in data_fo.columns if 'FO' in c and '(Pcs)' in c and re.search(r'\d{2}\.\d{4}', c)]
        
        if len(fo_cols) >= 3:
            fo_cols.sort(key=lambda x: pd.to_datetime(re.search(r'\d{2}\.\d{4}', x).group(), format='%m.%Y'))
            fo_n_minus_1_col = fo_cols[-3] 
            fo_n_col = fo_cols[-2]         
            fo_n1_col = fo_cols[-1]        
        else:
            fo_n_minus_1_col = [c for c in data_fo.columns if 'FO' in c and '(Pcs)' in c and '07' in c][0]
            fo_n_col = [c for c in data_fo.columns if 'FO' in c and '(Pcs)' in c and '08' in c][0]
            fo_n1_col = [c for c in data_fo.columns if 'FO' in c and '(Pcs)' in c and '09' in c][0]

        ord_n_minus_1_col = fo_n_minus_1_col.replace('FO', 'ORD')
        ord_n_col = fo_n_col.replace('FO', 'ORD')
        ord_n1_col = fo_n1_col.replace('FO', 'ORD')

        df = data_fo[['Material', 'Description', fo_n_minus_1_col, ord_n_minus_1_col, fo_n_col, ord_n_col, fo_n1_col, ord_n1_col]].copy()
        
        df['Max_N_minus_1'] = df[[fo_n_minus_1_col, ord_n_minus_1_col]].max(axis=1).fillna(0)
        df['Max_N'] = df[[fo_n_col, ord_n_col]].max(axis=1).fillna(0)
        df['Max_N1'] = df[[fo_n1_col, ord_n1_col]].max(axis=1).fillna(0)
        
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

        df_detail = df[['Material', 'Description', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Req_Qty', 'Semi Part', 'Machine Type', 'Req_Hours']].copy()
        return mach_summary, df_detail, None
    except Exception as e:
        return None, None, f"เกิดข้อผิดพลาดในการประมวลผล: {str(e)}"

# ==========================================
# Sidebar: Upload & Global Params
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2823/2823512.png", width=80)
    
    st.markdown("### 📂 1. อัปโหลดข้อมูลประจำเดือน")
    uploaded_up = st.file_uploader("ไฟล์ Data Upload (.xlsx)", type=["xlsx", "xls"])
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data base.xlsx')

    st.markdown("### ⚙️ 2. ค่าพารามิเตอร์เริ่มต้น")
    work_days = st.number_input("วันทำงาน (วัน/เดือน)", min_value=1, max_value=31, value=23)
    wip_reduction_pct = st.number_input("ปรับลด % WIP/FG ปลายเดือน", min_value=0.0, max_value=100.0, value=0.0, step=1.0)

# ==========================================
# Header & Export
# ==========================================
col_title, col_export = st.columns([4, 1])
with col_title:
    st.title("📊 Press Capacity Utilization Dashboard")
    st.markdown("ระบบวิเคราะห์ยอดการผลิตและคำนวณอัตราการใช้กำลังการผลิตของเครื่องจักร Press")

if not os.path.exists(db_file):
    st.error("⚠️ ไม่พบไฟล์ระบบ 'data base.xlsx' กรุณานำไฟล์ไปวางไว้ในโฟลเดอร์เดียวกับโปรแกรม")
    st.stop()
    
if uploaded_up is None:
    st.info("👋 ยินดีต้อนรับ! กรุณาอัปโหลดไฟล์ **data upload.xlsx** ประจำเดือนที่แถบด้านซ้ายมือ เพื่อเริ่มต้นวิเคราะห์ข้อมูล")
    st.stop()

mach_summary, df_detail, err = load_and_process(db_file, uploaded_up, wip_reduction_pct)
if err:
    st.error(err)
    st.stop()

# ==========================================
# 1. Custom Sorting & Easy Adjust Panel
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

if "oee_dict" not in st.session_state:
    st.session_state.oee_dict = {mt: 85.0 for mt in cfg['Machine Type']}
if "use_dict" not in st.session_state:
    st.session_state.use_dict = {row['Machine Type']: float(row['Usable Machines']) for _, row in cfg.iterrows()}

with col_export:
    st.write("")
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
        st.markdown("**2. ส่งออกหน้าเว็บพร้อมกราฟเป็น PDF**")
        components.html(
            """
            <button onclick="window.parent.print()" style="
                background-color: #EF553B; 
                border: none;
                color: white;
                padding: 10px 20px;
                text-align: center;
                border-radius: 5px;
                cursor: pointer;
                width: 100%;
                font-family: sans-serif;
                font-weight: bold;
                font-size: 14px;
            ">🖨️ Print / Save as PDF</button>
            <p style="font-size:12px; color:gray; font-family:sans-serif; text-align:center; margin-top:10px;">
            * แนะนำให้เปิดตัวเลือก <b>'Background graphics'</b> ในตั้งค่า Print ของเบราว์เซอร์เพื่อให้กราฟแสดงสีสันครบถ้วน
            </p>
            """,
            height=110
        )

# สร้าง List เก็บแจ้งเตือนเครื่องที่ใช้งานเกิน Total
over_machines_alerts = []

with st.expander("🎛️ แผงควบคุม: ปรับแต่งกะและ OEE รายเครื่องจักร (Easy Adjust)", expanded=False):
    st.markdown("##### 🔄 ปรับค่า OEE พร้อมกันทุกเครื่อง")
    b_col1, b_col2, b_col3 = st.columns([2, 2, 6])
    bulk_oee = b_col1.number_input("ตั้ง OEE ทุกเครื่องเป็น (%)", value=85.0, min_value=1.0, max_value=100.0)
    
    if b_col2.button("✨ นำไปใช้กับทุกเครื่อง"):
        for mt in cfg['Machine Type']:
            st.session_state.oee_dict[mt] = bulk_oee
        st.rerun() 
    st.markdown("---")

    h1, h2, h3, h4, h5 = st.columns([3.5, 1.5, 1.5, 1.5, 2.0])
    h1.write("**ประเภทเครื่องจักร**")
    h2.write("**Total**") # เปลี่ยนเป็น Total
    h3.write("**ใช้ได้ (ปรับ)**")
    h4.write("**กะการทำงาน**")
    h5.write("**OEE (%)**")
    st.markdown("---")
    
    for idx, row in cfg.iterrows():
        c1, c2, c3, c4, c5 = st.columns([3.5, 1.5, 1.5, 1.5, 2.0])
        mt = row['Machine Type']
        total_mach = int(row['Total Machines'])
        
        c1.write(f"🔧 {mt}")
        c2.write(f"**{total_mach}**")
        
        current_use = st.session_state.use_dict.get(mt, float(row['Usable Machines']))
        use_val = c3.number_input("ใช้ได้", min_value=0.0, value=current_use, step=1.0, key=f"use_{idx}", label_visibility="collapsed")
        
        # ถ้ายอดปรับมีค่ามากกว่า Total ให้เก็บแจ้งเตือน
        if use_val > total_mach:
            over_machines_alerts.append(f"- **{mt}** (มี {total_mach} แต่ปรับเป็น {int(use_val)})")
            
        shift_val = c4.selectbox("กะ", [1.0, 1.5, 2.0, 3.0], index=3, key=f"sh_{idx}", label_visibility="collapsed")
        
        current_oee = st.session_state.oee_dict.get(mt, 85.0)
        oee_val = c5.number_input("OEE", min_value=1.0, max_value=100.0, value=float(current_oee), step=1.0, key=f"oee_{idx}", label_visibility="collapsed")
        
        st.session_state.oee_dict[mt] = oee_val
        st.session_state.use_dict[mt] = use_val
        cfg.at[idx, 'Usable Machines'] = use_val
        cfg.at[idx, 'Shifts/Day'] = shift_val
        cfg.at[idx, 'OEE (%)'] = oee_val

    # แสดงแจ้งเตือนด้านล่างของตาราง ถ้ามีเครื่องเกิน
    if over_machines_alerts:
        st.error("⚠️ **พบเครื่องที่ใช้งานเกินจำนวนทั้งหมดที่มี (Total):**\n" + "\n".join(over_machines_alerts))

# ==========================================
# 2. Calculation
# ==========================================
cfg['Capacity_Per_Machine'] = (cfg['Shifts/Day'] * cfg['Hours/Shift'] * work_days * (cfg['OEE (%)'] / 100.0))
cfg['Available Hours'] = cfg['Usable Machines'] * cfg['Capacity_Per_Machine']
cfg['Utilization (%)'] = np.where(cfg['Available Hours'] > 0, (cfg['Req_Hours'] / cfg['Available Hours']) * 100.0, 0.0)
cfg['Req_Machines'] = np.where(cfg['Capacity_Per_Machine'] > 0, cfg['Req_Hours'] / cfg['Capacity_Per_Machine'], 0.0)

# ==========================================
# 3. KPI Cards
# ==========================================
total_req = cfg['Req_Hours'].sum()
total_avail = cfg['Available Hours'].sum()
overall_util = (total_req / total_avail) * 100 if total_avail > 0 else 0
over_cap_count = len(cfg[cfg['Utilization (%)'] > 100])
total_req_machines = cfg['Req_Machines'].sum()

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("💡 เครื่องพร้อมใช้ (ตั้งค่า)", f"{int(cfg['Usable Machines'].sum())} เครื่อง")
kpi2.metric("⚙️ เครื่องที่ใช้จริง (คำนวณ)", f"{total_req_machines:.1f} เครื่อง")
kpi3.metric("⏱️ ชั่วโมงผลิตที่ต้องการ", f"{total_req:,.0f} ชม.")
kpi4.metric("📈 Utilization เฉลี่ย", f"{overall_util:.1f}%")
kpi5.metric("⚠️ เกินกำลัง (>100%)", f"{over_cap_count} ประเภท", delta="Over Capacity" if over_cap_count > 0 else "ปกติ", delta_color="inverse")
st.divider()

# ==========================================
# 4. Overall Donut & Professional Bar Chart
# ==========================================
col_donut_all, col_bar = st.columns([1, 2.5])

def create_donut(title, util_val, height=220):
    color = "#EF553B" if util_val > 100 else "#1f77b4"
    visual_util = min(util_val, 100)
    remaining = max(100 - visual_util, 0)
    
    fig = go.Figure(data=[go.Pie(
        labels=['ใช้งานแล้ว', 'พื้นที่ว่าง'],
        values=[visual_util, remaining], hole=0.65,
        marker=dict(colors=[color, '#e9ecef']), textinfo='none', hoverinfo='label'
    )])
    
    font_size = 28 if height > 220 else 22
    fig.add_annotation(text=f"<b>{util_val:.1f}%</b>", x=0.5, y=0.5, font_size=font_size, font_color=color, showarrow=False)
    
    layout_args = dict(showlegend=False, margin=dict(t=10, b=10, l=10, r=10), height=height, paper_bgcolor="rgba(0,0,0,0)")
    if title: 
        layout_args['title'] = dict(text=title, x=0.5, font=dict(size=15, color="#333333"))
        layout_args['margin']['t'] = 40
    fig.update_layout(**layout_args)
    return fig

with col_donut_all:
    st.markdown("#### 🍩 ภาพรวมทั้งหมด (Overall)")
    with st.expander("🔍 กรองเฉพาะบางเครื่องจักร"):
        selected_machines = st.multiselect("เลือกประเภทเครื่องจักรเพื่อรวมยอด:", options=cfg['Machine Type'].tolist(), default=cfg['Machine Type'].tolist(), label_visibility="collapsed")
    
    if selected_machines:
        filtered_cfg = cfg[cfg['Machine Type'].isin(selected_machines)]
        f_total_req = filtered_cfg['Req_Hours'].sum()
        f_total_avail = filtered_cfg['Available Hours'].sum()
        f_overall_util = (f_total_req / f_total_avail) * 100 if f_total_avail > 0 else 0
        st.plotly_chart(create_donut("Overall Machine Utilization", f_overall_util, height=270), use_container_width=True)
    else:
        st.warning("กรุณาเลือกเครื่องจักรอย่างน้อย 1 ประเภท")

with col_bar:
    st.markdown("#### 📊 กราฟวิเคราะห์ Utilization & OEE")
    fig_bar = make_subplots(specs=[[{"secondary_y": True}]])
    bar_colors = ['#EF553B' if val > 100 else '#1f77b4' for val in cfg['Utilization (%)']]
    
    fig_bar.add_trace(go.Bar(
        x=cfg['Machine Type'], y=cfg['Utilization (%)'], marker_color=bar_colors, name="Utilization (%)",
        text=cfg['Utilization (%)'].apply(lambda x: f'{x:.1f}%'), textposition='inside', textfont=dict(color='white'),
        hovertemplate="<b>%{x}</b><br>Utilization: %{y:.1f}%<extra></extra>"
    ), secondary_y=False)
    
    fig_bar.add_trace(go.Scatter(
        x=cfg['Machine Type'], y=cfg['OEE (%)'], mode='lines', name="OEE (%)",
        line=dict(color='#FF8C00', width=3.5, shape='spline', smoothing=1.2), 
        hovertemplate="<b>%{x}</b><br>OEE: %{y:.1f}%<extra></extra>"
    ), secondary_y=True)
    
    fig_bar.add_hline(y=100, line_dash="dash", line_color="#EF553B", line_width=2, 
                      annotation_text="Max Capacity 100%", annotation_position="top left",
                      annotation_font=dict(color="#EF553B", size=12), secondary_y=False)
    
    fig_bar.update_layout(height=380, margin=dict(t=20, b=50, l=0, r=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1), hovermode="x unified")
    
    fig_bar.update_yaxes(title_text="Utilization (%)", gridcolor='rgba(200,200,200,0.2)', secondary_y=False, rangemode='tozero')
    fig_bar.update_yaxes(title_text="OEE (%)", showgrid=False, secondary_y=True, range=[0, 110])
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ==========================================
# 5. Individual Donut Charts
# ==========================================
st.markdown("### 🍩 อัตราการใช้เครื่องจักรแยกรายประเภท")
num_cols = 4
rows = [cfg.iloc[i:i + num_cols] for i in range(0, len(cfg), num_cols)]
for row_df in rows:
    cols = st.columns(num_cols)
    for idx, (index, data) in enumerate(row_df.iterrows()):
        with cols[idx]:
            short_name = data['Machine Type'][:30] + ".." if len(data['Machine Type']) > 30 else data['Machine Type']
            st.markdown(f"<div style='text-align: center; font-size: 14px; font-weight: bold; color: #333333;'>{short_name}</div>", unsafe_allow_html=True)
            st.plotly_chart(create_donut("", data['Utilization (%)'], height=200), use_container_width=True)

st.divider()

# ==========================================
# 6. Deep Dive Analytics (Top 5 & 3-Month Trends)
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
                m_df = top_5_parts[top_5_parts['Machine Type'] == m_type][['Material', 'Description', 'Req_Qty', 'Req_Hours']]
                st.dataframe(m_df.style.format({'Req_Qty': '{:,.0f}', 'Req_Hours': '{:,.1f} ชม.'}), use_container_width=True, hide_index=True)
    else:
        st.info("ไม่มีข้อมูลชั่วโมงการผลิต")

with col_deep2:
    st.markdown("### 📈 Top 5 Parts (Trend 3 เดือน สวิง > 30%)")
    st.caption("ดึงข้อมูลชิ้นงานที่กินชั่วโมงเครื่องจักรมากที่สุดก่อน (Req_Hours) ที่มียอดออเดอร์สวิงเกิน 30%")
    
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
        color = '#00cc96' if val > 0 else '#EF553B' 
        return f'color: {color}; font-weight: bold'
    
    tab_up, tab_down = st.tabs(["🟢 แนวโน้มเพิ่มขึ้น (Top 5 Up)", "🔴 แนวโน้มลดลง (Top 5 Down)"])
    disp_cols = ['Machine Type', 'Material', 'Max_N_minus_1', 'Max_N', 'Max_N1', 'Trend', '% Change', 'Req_Hours']
    
    with tab_up:
        if not df_up.empty:
            disp_up = df_up[disp_cols].rename(columns={'Max_N_minus_1': 'Mth N-1', 'Max_N': 'Mth N', 'Max_N1': 'Mth N+1'})
            st.dataframe(
                disp_up.style.format({'Mth N-1': '{:,.0f}', 'Mth N': '{:,.0f}', 'Mth N+1': '{:,.0f}', '% Change': '{:+.1f}%', 'Req_Hours': '{:,.1f}'})
                       .map(style_change, subset=['% Change']),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("ไม่มี Part ที่ยอดสั่งผลิตเพิ่มขึ้นเกิน 30% ในช่วง 3 เดือน")
            
    with tab_down:
        if not df_down.empty:
            disp_down = df_down[disp_cols].rename(columns={'Max_N_minus_1': 'Mth N-1', 'Max_N': 'Mth N', 'Max_N1': 'Mth N+1'})
            st.dataframe(
                disp_down.style.format({'Mth N-1': '{:,.0f}', 'Mth N': '{:,.0f}', 'Mth N+1': '{:,.0f}', '% Change': '{:+.1f}%', 'Req_Hours': '{:,.1f}'})
                       .map(style_change, subset=['% Change']),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("ไม่มี Part ที่ยอดสั่งผลิตลดลงเกิน 30% ในช่วง 3 เดือน")