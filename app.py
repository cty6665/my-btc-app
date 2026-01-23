import streamlit as st
import pandas as pd
import requests
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 配置私有密钥与持久化 (保留你的通行证)
# ==========================================
API_KEY = "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"
DATA_FILE = "trading_data.csv"

st.set_page_config(page_title="Binance Private Pro", layout="wide", initial_sidebar_state="collapsed")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            return float(df['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_data(balance):
    df = pd.DataFrame({"balance": [balance], "last_update": [datetime.now()]})
    df.to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state:
    st.session_state.balance = load_data()
if 'orders' not in st.session_state:
    st.session_state.orders = []
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
    
# CSS 样式 (保留你的简洁白色风格)
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    [data-testid="stMetricValue"] { color: #000000 !important; font-weight: bold; }
    .stButton button { width: 100%; height: 60px; font-size: 20px !important; font-weight: bold; background-color: #FCD535 !important; color: #000 !important; border: none; }
</style>
""", unsafe_allow_html=True)

# 自动刷新：5秒一次
st_autorefresh(interval=5000, key="pro_refresh")

# ==========================================
# 2. 融合版行情获取 (你的特权 KEY + 稳健备份)
# ==========================================
def get_robust_private_price(symbol):
    headers = {'X-MBX-APIKEY': API_KEY}
    
    # 路径 A: 你的私有 API 路径 (优先使用通行证)
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, headers=headers, timeout=1.5).json()
        if 'price' in res:
            return float(res['price'])
    except:
        pass

    # 路径 B: 必通 K 线备份路径 (如果 A 被拦截，自动切到这里)
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, headers=headers, params=params, timeout=1.5).json()
        return float(res[-1][4])
    except:
        pass

    # 路径 C: 备用公共节点 (api3)
    try:
        url = f"https://api3.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=1.5).json()
        return float(res['price'])
    except:
        return None

# ==========================================
# 3. 核心交易逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 账户控制")
    coin = st.selectbox("币种选择", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("结算周期(分钟)", [1, 5, 10, 30], index=2)
    bet = st.number_input("下单金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_data(1000.0)
        st.rerun()

current_price = get_robust_private_price(coin)
now = datetime.now()

# 自动结算逻辑 (含开平仓价对比)
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            od["平仓价"] = current_price
            win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
            od.update({
                "状态": "已结算", 
                "结果": "W" if win else "L",
                "颜色": "#02C076" if win else "#CF304A"
            })
            updated = True
    if updated:
        save_data(st.session_state.balance)

# ==========================================
# 4. UI 布局
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric("实时价格", f"${current_price if current_price else '重连中...'}")
c3.metric("当前品种", coin)

# TradingView 插件
tv_html = f"""
    <div id="tv-chart" style="height:420px;"></div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
    new TradingView.widget({{
      "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
      "theme": "light", "style": "1", "locale": "zh_CN", "container_id": "tv-chart"
    }});
    </script>
"""
components.html(tv_html, height=420)

# 下单按钮
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)"):
    if st.session_state.balance >= bet and current_price:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({
            "方向": "看涨", "开仓价": current_price, "平仓价": None,
            "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
            "状态": "待结算", "结果": None
        })
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)"):
    if st.session_state.balance >= bet and current_price:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({
            "方向": "看跌", "开仓价": current_price, "平仓价": None,
            "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
            "状态": "待结算", "结果": None
        })
        st.rerun()

# 实时流水表格 (开平仓价对比)
st.write("📋 实时流水")
if st.session_state.orders:
    history_data = []
    for od in reversed(st.session_state.orders[-8:]):
        rem = (od["结算时间"] - now).total_seconds()
        countdown = f"{int(rem)}s" if rem > 0 else "结算中"
        
        history_data.append({
            "方向": od["方向"],
            "开仓价": f"{od['开仓价']:.2f}",
            "平仓价": f"{od['平仓价']:.2f}" if od['平仓价'] else "---",
            "金额": f"{od['金额']}U",
            "状态": od["状态"],
            "结果": od["结果"] if od["结果"] else countdown
        })
    st.table(history_data)


