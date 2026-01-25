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

# --- 1. 基础配置与样式 (极致精简) ---
st.set_page_config(page_title="事件合约终端", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    .nav-bar { position: fixed; top: 0; left: 0; width: 100%; height: 44px; background: #FFFFFF; border-bottom: 1px solid #E5E5EA; display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }
    div[data-testid="column"]:nth-of-type(1) button { background-color: #00B578 !important; color: white !important; height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important; }
    div[data-testid="column"]:nth-of-type(2) button { background-color: #FF3141 !important; color: white !important; height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important; }
    .order-card { padding: 12px; border-bottom: 1px solid #F5F5F7; background: #FFF; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
<div style="height: 50px;"></div>
""", unsafe_allow_html=True)

# --- 2. 稳健数据接口 ---
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return None

def get_klines_all_sources(symbol, interval='1m'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=80"
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

# --- 3. UI 核心渲染 (带防崩保护) ---
@st.fragment
def main_app():
    try:
        st_autorefresh(interval=2000, key="global_refresh")
        now_time = get_beijing_time()

        # 1. 顶部控制器
        chart_mode = st.radio("模式", ["原生 K 线", "TradingView"], horizontal=True, label_visibility="collapsed")
        c1, c2 = st.columns([2, 1])
        with c1: coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0, label_visibility="collapsed")
        with c2: k_interval = st.selectbox("周期", ["1m", "5m", "15m", "1h"], index=0, label_visibility="collapsed")
        
        curr_p = get_price(coin)

        # 2. 自动结算
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

        # 3. 图表渲染逻辑 (双重隔离)
        if chart_mode == "TradingView":
            tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
            tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies
