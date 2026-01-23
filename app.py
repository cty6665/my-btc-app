import streamlit as st
import pandas as pd
import requests
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 配置与持久化
# ==========================================
API_KEY = "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"
DATA_FILE = "trading_data.csv"

st.set_page_config(page_title="Binance Pro", layout="wide", initial_sidebar_state="collapsed")

def load_balance():
    if os.path.exists(DATA_FILE):
        try: return float(pd.read_csv(DATA_FILE)['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_balance(balance):
    pd.DataFrame({"balance": [balance]}).to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state: st.session_state.balance = load_balance()
if 'orders' not in st.session_state: st.session_state.orders = []

# 样式
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000; }
    [data-testid="stMetricValue"] { color: #02C076 !important; font-size: 24px !important; }
    .stButton button { width: 100%; height: 50px; font-weight: bold; }
    .order-row { border-bottom: 1px solid #eee; padding: 10px 0; font-size: 14px; }
</style>
""", unsafe_allow_html=True)

# 自动刷新 (5秒一次)
st_autorefresh(interval=5000, key="price_refresh")

# ==========================================
# 2. 增强型价格获取 (多路保障)
# ==========================================
def get_robust_price(symbol):
    # 路径 A: 私有 Key 请求
    try:
        headers = {'X-MBX-APIKEY': API_KEY}
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=1).json()
        return float(res['price'])
    except: pass

    # 路径 B: 你验证最稳的 K 线接口
    try:
        res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1", timeout=1).json()
        return float(res[-1][4])
    except: pass

    # 路径 C: 备用节点
    try:
        res = requests.get(f"https://api3.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return None

# ==========================================
# 3. 核心逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 设置")
    coin = st.selectbox("选择品种", ["BTCUSDT", "ETHUSDT"])
    duration = st.selectbox("结算周期(分)", [1, 5, 10, 30, 60], index=2)
    bet = st.number_input("金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置系统"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_balance(1000.0)
        st.rerun()

current_price = get_robust_price(coin)
now = datetime.now()

# 自动结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "等待中" and now >= od["结算时间"]:
            od["平仓价"] = current_price
            win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
            if win: st.session_state.balance += od["金额"] * 1.8
            od["状态"], od["结果"] = "已结算", ("W" if win else "L")
            updated = True
    if updated: save_balance(st.session_state.balance)

# ==========================================
# 4. 界面展示
# ==========================================
c1, c2 = st.columns(2)
c1.metric("可用余额", f"${st.session_state.balance:,.2f}")
c2.metric("实时价格", f"{current_price if current_price else '获取中...'}")

# TV 图表
tv_html = f"""
    <div id="tv-chart" style="height:400px;"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
    new TradingView.widget({{"autosize": true, "symbol": "BINANCE:{coin}", "interval": "1", "theme": "light", "style": "1", "locale": "zh_CN", "container_id": "tv-chart"}});
    </script>
"""
components.html(tv_html, height=400)

# 交易按钮
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_balance(st.session_state.balance)
        st.session_state.orders.append({
            "方向": "看涨", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "等待中", "结果": None
        })
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_balance(st.session_state.balance)
        st.session_state.orders.append({
            "方向": "看跌", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "等待中", "结果": None
        })
        st.rerun()

# 交易流水 (包含开仓价、平仓价对比)
st.write("📋 交易流水")
if st.session_state.orders:
    # 转换为表格显示，更清晰直观
    df_history = []
    for od in reversed(st.session_state.orders[-8:]):
        rem = (od["结算时间"] - now).total_seconds()
        res = od["结果"] if od["结果"] else (f"{int(rem)}s" if rem > 0 else "结算中")
        df_history.append({
            "方向": od["方向"],
            "金额": f"{od['金额']}U",
            "开仓价": od["开仓价"],
            "平仓价": od["平仓价"] if od["平仓价"] else "---",
            "状态": od["状态"],
            "结果": res
        })
    st.table(df_history)
