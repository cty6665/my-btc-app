import streamlit as st
import pandas as pd
import requests
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 基础配置
# ==========================================
DATA_FILE = "trading_data.csv"
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

def load_data():
    if os.path.exists(DATA_FILE):
        try: return float(pd.read_csv(DATA_FILE)['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_data(balance):
    pd.DataFrame({"balance": [balance]}).to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state: st.session_state.balance = load_data()
if 'orders' not in st.session_state: st.session_state.orders = []

st.markdown("<style>.stApp { background-color: #FFFFFF; color: #000; } .stButton button { background-color: #FCD535 !important; color: #000 !important; font-weight: bold; }</style>", unsafe_allow_html=True)
st_autorefresh(interval=5000, key="pro_refresh")

# ==========================================
# 2. 核心：跨源行情抓取 (不再死磕币安)
# ==========================================
def get_price_emergency():
    # 路径 1: 币安备用接口
    try:
        res = requests.get("https://api3.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=1.5).json()
        return float(res['price'])
    except: pass

    # 路径 2: Gate.io 接口 (非常稳，极少封IP)
    try:
        res = requests.get("https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT", timeout=1.5).json()
        return float(res[0]['last'])
    except: pass

    # 路径 3: Crypto.com 接口
    try:
        res = requests.get("https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT", timeout=1.5).json()
        return float(res['result']['data'][0]['a'])
    except: pass

    return None

# ==========================================
# 3. 页面逻辑
# ==========================================
coin = st.sidebar.selectbox("币种", ["BTCUSDT", "ETHUSDT"])
duration = st.sidebar.radio("周期(分)", [1, 5, 10, 30], index=2)
bet = st.sidebar.number_input("下单金额", 10.0, 1000.0, 50.0)

current_price = get_price_emergency()
now = datetime.now()

# 结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            od["平仓价"] = current_price
            win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
            if win: st.session_state.balance += od["金额"] * 1.8
            od.update({"状态": "已结算", "结果": "W" if win else "L"})
            updated = True
    if updated: save_data(st.session_state.balance)

# UI 布局
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
if current_price:
    c2.metric("实时价格", f"${current_price:,.2f}")
else:
    c2.error("🚫 所有数据源均被封锁")

# TradingView 插件 (直连行情，通常不受服务器封锁影响)
tv_html = f"""
    <div id="tv-chart" style="height:400px;"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart"}});</script>
"""
components.html(tv_html, height=400)

# 下单区
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({"方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({"方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        st.rerun()

st.write("📋 交易流水")
if st.session_state.orders:
    st.table(pd.DataFrame([{
        "方向": od["方向"], "开仓价": od["开仓价"], 
        "平仓价": od["平仓价"] if od["平仓价"] else "---", 
        "结果": od["结果"] if od["结果"] else f"等待中"
    } for od in reversed(st.session_state.orders[-5:])]))
