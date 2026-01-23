import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 配置私有密钥 (请自行修改此处)
# ==========================================
API_KEY = "你的API_KEY"
API_SECRET = "你的SECRET_KEY"
DATA_FILE = "trading_data.csv"

# ==========================================
# 2. 页面配置与持久化存储逻辑
# ==========================================
st.set_page_config(page_title="Binance Private Pro", layout="wide", initial_sidebar_state="collapsed")

# 读写数据的函数
def load_data():
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        # 将字符串转回列表格式
        balance = df['balance'].iloc[0]
        # 简化处理：记录主要存余额，订单存session以保流畅，
        # 如果需要极高要求的订单恢复，可扩展此逻辑
        return float(balance)
    return 1000.0

def save_data(balance):
    df = pd.DataFrame({"balance": [balance], "last_update": [datetime.now()]})
    df.to_csv(DATA_FILE, index=False)

# 初始化
if 'balance' not in st.session_state:
    st.session_state.balance = load_data()
if 'orders' not in st.session_state:
    st.session_state.orders = []

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    [data-testid="stMetricValue"] { color: #000000 !important; font-weight: bold; }
    .price-box { background: #F8F9FA; padding: 15px; border-radius: 10px; border: 1px solid #EEE; text-align: center; }
    .stButton button { width: 100%; height: 60px; font-size: 20px !important; font-weight: bold; background-color: #FCD535 !important; color: #000 !important; border: none; }
    .order-card { background: #F8F9FA; border-left: 5px solid #FCD535; padding: 10px; margin-top: 5px; color: #333; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="pro_refresh")

# ==========================================
# 3. 私有 API 请求
# ==========================================
def get_private_price(symbol):
    try:
        # 带上 API Key 请求私有权重节点
        headers = {'X-MBX-APIKEY': API_KEY}
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        return None

# ==========================================
# 4. 主逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 账户控制")
    coin = st.selectbox("币种选择", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("结算周期(分钟)", [1, 5, 10, 30])
    bet = st.number_input("下单金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_data(1000.0)
        st.rerun()

current_price = get_private_price(coin)
now = datetime.now()

# 自动结算
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "看涨" and current_price > od["开仓价"]) or \
                  (od["方向"] == "看跌" and current_price < od["开仓价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
            od.update({"状态": "已结算", "结果": "WIN" if win else "LOSS", "颜色": "#02C076" if win else "#CF304A"})
            updated = True
    if updated:
        save_data(st.session_state.balance) # 结算后自动保存余额

# ==========================================
# 5. UI 布局
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("账户余额", f"${st.session_state.balance:.2f}")
c2.metric("实时价格", f"${current_price if current_price else '加载中...'}")
c3.metric("当前品种", coin)

# TradingView 插件（手机端直连行情）
tv_html = f"""
    <div id="tv-chart" style="height:420px;"></div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
    new TradingView.widget({{
      "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
      "timezone": "Asia/Shanghai", "theme": "light", "style": "1",
      "locale": "zh_CN", "container_id": "tv-chart",
      "studies": ["MAExp@tv-basicstudies", "BollingerBandsUpper@tv-basicstudies"]
    }});
    </script>
"""
components.html(tv_html, height=420)

# 交易按钮
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)"):
    if st.session_state.balance >= bet and current_price:
        st.session_state.balance -= bet
        save_data(st.session_state.balance) # 下单扣款后立即保存
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
            "方向": "看涨", "开仓价": current_price, "金额": bet, "状态": "待结算", "结果": None
        })
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)"):
    if st.session_state.balance >= bet and current_price:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
            "方向": "看跌", "开仓价": current_price, "金额": bet, "状态": "待结算", "结果": None
        })
        st.rerun()

st.write("📋 实时流水")
for od in reversed(st.session_state.orders[-5:]):
    color = od.get("颜色", "#333")
    st.markdown(f"""
    <div class="order-card">
        <b>{od['方向']}</b> ${od['开仓价']:.2f} | {od['金额']}U <br>
        <span style="color:{color}">状态: {od['状态']} {od['结果'] if od['结果'] else ''}</span>
    </div>
    """, unsafe_allow_html=True)
