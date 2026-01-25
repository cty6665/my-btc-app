import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 核心配置与样式 ---
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    
    /* 1. 导航栏 */
    .nav-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }

    /* 2. 按钮颜色强化 */
    div[data-testid="column"]:nth-of-type(1) button {
        background-color: #00B578 !important; color: white !important;
        height: 55px !important; font-size: 18px !important; font-weight: 800 !important; width: 100%;
    }
    div[data-testid="column"]:nth-of-type(2) button {
        background-color: #FF3141 !important; color: white !important;
        height: 55px !important; font-size: 18px !important; font-weight: 800 !important; width: 100%;
    }

    /* 3. 动态对勾动画回归 */
    @keyframes stroke { 100% { stroke-dashoffset: 0; } }
    @keyframes scale { 0%, 100% { transform: none; } 50% { transform: scale3d(1.1, 1.1, 1); } }
    @keyframes fill { 100% { box-shadow: inset 0px 0px 0px 80px #0ECB81; } }
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; display: block; stroke-width: 2; stroke: #0ECB81; stroke-miterlimit: 10; box-shadow: inset 0px 0px 0px #0ECB81; animation: fill .4s ease-in-out .4s forwards, scale .3s ease-in-out .9s both; }
    .checkmark__circle { stroke-dasharray: 166; stroke-dashoffset: 166; stroke-width: 2; stroke-miterlimit: 10; stroke: #0ECB81; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }
    .checkmark__check { transform-origin: 50% 50%; stroke-dasharray: 48; stroke-dashoffset: 48; animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.8s forwards; }
    
    .order-card { padding: 12px; border-bottom: 1px solid #F5F5F7; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# --- 2. 逻辑函数 ---
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except: return None

def get_klines_smart_source(symbol, interval='1m'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f); orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if od.get(key) and isinstance(od[key], str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# --- 3. 主界面 ---
@st.fragment
def main_app():
    st_autorefresh(interval=3000, key="global_refresh")
    now_time = get_beijing_time()
    
    # 切换数据源
    chart_mode = st.radio("数据源选择", ["原生 K 线", "TradingView"], horizontal=True, label_visibility="collapsed")
    
    col_sel1, col_sel2 = st.columns([2, 1])
    with col_sel1: coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=1, label_visibility="collapsed")
    with col_sel2: k_interval = st.selectbox("周期", ["1m", "5m", "15m", "1h"], index=0, label_visibility="collapsed")
    
    curr_p = get_price(coin)
    
    # 自动结算逻辑
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_p
                win = (od['方向']=="上涨" and od['平仓价']>od['开仓价']) or (od['方向']=="下跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'] = "已结算"
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 1. 图表区
    if chart_mode == "TradingView":
        tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df_k = get_klines_smart_source(coin, k_interval)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']
            df_k['dn'] = df_k['ma'] - 2*df_k['std']
            
            fig = make_subplots(rows=1, cols=1)
            # K线颜色纯化
            fig.add_trace(go.Candlestick(
                x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
                increasing_fillcolor='#00B578', increasing_line_color='#00B578',
                decreasing_fillcolor='#FF3141', decreasing_line_color='#FF3141'
            ))
            # 布林带加粗
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(31,119,180,0.5)', width=2.5), name='UP'))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(227,119,194,0.5)', width=2.5), name='DN'))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3), name='MB'))

            # --- 核心新增：实时画虚线 ---
            for od in st.session_state.orders:
                if od['状态'] == "待结算" and od['资产'] == coin:
                    line_color = "#00B578" if od['方向']=="上涨" else "#FF3141"
                    marker_symbol = "triangle-up" if od['方向']=="上涨" else "triangle-down"
                    # 画全屏横线
                    fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=line_color, line_width=2, 
                                  annotation_text=f"{od['方向']} ▲" if od['方向']=="上涨" else f"{od['方向']} ▼", 
                                  annotation_position="right", annotation_font_color=line_color)

            fig.update_layout(height=380, margin=dict(t=5,b=5,l=0,r=0), xaxis_rangeslider_visible=False, dragmode='pan', plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
            fig.update_yaxes(side="right", gridcolor="#F5F5F7")
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})

    # 2. 下单区
    bet = st.number_input("数量(USDT)", 10.0, 5000.0, 100.0)
    st.markdown(f'<div style="text-align:right; font-size:12px; color:#8E8E93; margin-top:-10px;">可用: {st.session_state.balance:.2f}</div>', unsafe_allow_html=True)
    
    btn_col1, btn_col2 = st.columns(2)
    if btn_col1.button("上涨"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "上涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    if btn_col2.button("下跌"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "下跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    # 3. 流水区
    st.markdown('<div style="margin-top:20px; font-weight:700; border-bottom:2px solid #00B578; width:fit-content;">交易详情流水</div>', unsafe_allow_html=True)
    for o in reversed(st.session_state.orders[-10:]):
        color = "#00B578" if o['方向'] == "上涨" else "#FF3141"
        st.markdown(f"""
        <div class="order-card">
            <div style="display:flex; justify-content:space-between;">
                <span style="font-weight:700; color:{color};">{o['方向']} {o['资产']}</span>
                <span style="font-weight:700;">${o['金额']}</span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; font-size: 11px; color:#8E8E93; margin-top:5px;">
                <div>开仓价: <b style="color:#000">{o['开仓价']:,.2f}</b></div>
                <div>平仓价: <b style="color:#000">{o['平仓价'] or '进行中'}</b></div>
                <div>时间(开): {o['开仓时间'].strftime('%H:%M:%S')}</div>
                <div>时间(平): {o['结算时间'].strftime('%H:%M:%S')}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# 动态对勾动画组件
if st.session_state.get('show_success'):
    st.markdown("""
        <div class="success-overlay">
            <svg class="checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52">
                <circle class="checkmark__circle" cx="26" cy="26" r="25" fill="none"/>
                <path class="checkmark__check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8"/>
            </svg>
            <h2 style="color: #0ECB81; margin-top: 20px;">开仓成功</h2>
        </div>
    """, unsafe_allow_html=True)
    time.sleep(1.2)
    st.session_state.show_success = False
    st.rerun()

main_app()
