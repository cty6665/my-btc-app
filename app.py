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

# --- 1. 核心视觉定制 ---
st.set_page_config(page_title="事件合约Pro", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    .nav-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }
    
    /* 下单按钮：纯绿/纯红 */
    div[data-testid="column"]:nth-of-type(1) button {
        background-color: #00B578 !important; color: white !important;
        height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important;
    }
    div[data-testid="column"]:nth-of-type(2) button {
        background-color: #FF3141 !important; color: white !important;
        height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important;
    }

    /* 动态成功对勾 */
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.95); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; display: block; stroke-width: 2; stroke: #0ECB81; stroke-miterlimit: 10; box-shadow: inset 0px 0px 0px #0ECB81; animation: fill .4s ease-in-out .4s forwards, scale .3s ease-in-out .9s both; }
    .checkmark__circle { stroke-dasharray: 166; stroke-dashoffset: 166; stroke-width: 2; stroke-miterlimit: 10; stroke: #0ECB81; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }
    .checkmark__check { transform-origin: 50% 50%; stroke-dasharray: 48; stroke-dashoffset: 48; animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.8s forwards; }
    @keyframes stroke { 100% { stroke-dashoffset: 0; } }
    @keyframes fill { 100% { box-shadow: inset 0px 0px 0px 80px #0ECB81; } }

    .order-card { padding: 12px; border-bottom: 1px solid #F5F5F7; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# --- 2. 强力数据接口 (Binance + Gate.io 双备份) ---
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        # 接口 A: Binance
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except:
        try:
            # 接口 B: Gate.io
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=1).json()
            return float(res[0]['last'])
        except: return None

def get_klines_all_sources(symbol, interval='1m'):
    # 尝试多源获取数据，确保图表不丢失
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=80"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=80"
            res = requests.get(url, timeout=2).json()
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
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

# --- 3. UI 渲染 ---
@st.fragment
def main_app():
    st_autorefresh(interval=2000, key="refresh_all")
    now_time = get_beijing_time()
    
    # 顶部币种与周期
    c1, c2 = st.columns([2, 1])
    with c1: coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], index=0, label_visibility="collapsed")
    with c2: k_interval = st.selectbox("周期", ["1m", "5m", "15m", "1h"], index=0, label_visibility="collapsed")
    
    curr_p = get_price(coin)
    
    # 自动结算
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

    # --- K 线图表区 ---
    df_k = get_klines_all_sources(coin, k_interval)
    if not df_k.empty:
        # 计算布林带
        df_k['ma'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'] = df_k['ma'] + 2*df_k['std']
        df_k['dn'] = df_k['ma'] - 2*df_k['std']
        
        fig = make_subplots(rows=1, cols=1)
        # 1. 纯色 K 线：上涨绿，下跌红
        fig.add_trace(go.Candlestick(
            x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
            increasing_fillcolor='#00B578', increasing_line_color='#00B578',
            decreasing_fillcolor='#FF3141', decreasing_line_color='#FF3141'
        ))
        # 2. 布林带加粗渲染
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(31,119,180,0.3)', width=2), hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(227,119,194,0.3)', width=2), hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3), name='MB')) # 金色中轨

        # 3. 实时虚线与箭头 (开仓中的单子)
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and od['资产'] == coin:
                l_color = "#00B578" if od['方向']=="上涨" else "#FF3141"
                fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=l_color, line_width=2,
                              annotation_text=f"{od['方向']} {'▲' if od['方向']=='上涨' else '▼'}",
                              annotation_position="right", annotation_font_color=l_color)

        fig.update_layout(height=420, margin=dict(t=10,b=10,l=0,r=0), xaxis_rangeslider_visible=False, dragmode='pan', plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
        fig.update_yaxes(side="right", gridcolor="#F5F5F7", fixedrange=False)
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
    else:
        st.warning("🔄 正在从多个接口同步行情数据，请稍候...")

    # --- 交互区 ---
    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
    bet = st.number_input("下单数量(USDT)", 10.0, 5000.0, 100.0, step=10.0)
    st.markdown(f'<div style="text-align:right; font-size:12px; color:#8E8E93; margin-top:-10px;">可用: {st.session_state.balance:,.2f} USDT</div>', unsafe_allow_html=True)
    
    b1, b2 = st.columns(2)
    if b1.button("上涨 ▲"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "上涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    if b2.button("下跌 ▼"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "下跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st
