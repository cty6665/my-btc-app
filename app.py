import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置与持久化 (沿用你代码的逻辑)
# ==========================================
st.set_page_config(page_title="Pro Hybrid Terminal", layout="wide", initial_sidebar_state="collapsed")
DATA_FILE = "trading_data.csv"

def load_data():
    if os.path.exists(DATA_FILE):
        try: return float(pd.read_csv(DATA_FILE)['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_data(balance):
    pd.DataFrame({"balance": [balance]}).to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state: st.session_state.balance = load_data()
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 2. 提取你提供的必通报价逻辑 (2秒刷新)
# ==========================================
def get_binance_price(symbol):
    try:
        # 参考你代码中的 K 线接口获取最新价
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, timeout=1.5)
        return float(res.json()['price'])
    except:
        return None

# ==========================================
# 3. 页面样式
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    .price-text { font-size: 42px; font-weight: bold; color: #02C076; text-align: center; }
    .stButton button { width: 100%; height: 60px; font-size: 20px !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. 侧边栏
# ==========================================
with st.sidebar:
    coin = st.selectbox("选择品种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("结算周期(分钟)", [1, 5, 10, 30])
    bet = st.number_input("下单金额", 10.0, 5000.0, 50.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_data(1000.0)
        st.rerun()

# ==========================================
# 5. 主界面布局
# ==========================================
# 获取最新价 (每当页面运行都会刷新)
current_price = get_binance_price(coin)
now = datetime.now()

col_main, col_side = st.columns([3, 1])

with col_main:
    # --- 100% 自由的 TradingView 图表 ---
    # 只要 coin 没变，它就不会被刷新，你可以随意切分钟、调指标
    tv_html = f"""
        <div id="tv-chart" style="height:500px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
          "timezone": "Asia/Shanghai", "theme": "light", "style": "1",
          "locale": "zh_CN", "container_id": "tv-chart",
          "hide_side_toolbar": false, "allow_symbol_change": true,
          "studies": ["MAExp@tv-basicstudies", "BollingerBandsUpper@tv-basicstudies"]
        }});
        </script>
    """
    components.html(tv_html, height=500)

with col_side:
    st.write("💰 账户余额")
    st.subheader(f"${st.session_state.balance:.2f}")
    
    st.write("📈 实时报价")
    if current_price:
        st.markdown(f'<div class="price-text">${current_price:,.2f}</div>', unsafe_allow_html=True)
    else:
        st.warning("连接中...")

    # 下单逻辑
    if st.button("🟢 看涨 (UP)", type="primary"):
        if current_price and st.session_state.balance >= bet:
            st.session_state.balance -= bet
            save_data(st.session_state.balance)
            st.session_state.orders.append({
                "方向": "看涨", "开仓价": current_price, "金额": bet,
                "结算时间": now + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

    if st.button("🔴 看跌 (DOWN)"):
        if current_price and st.session_state.balance >= bet:
            st.session_state.balance -= bet
            save_data(st.session_state.balance)
            st.session_state.orders.append({
                "方向": "看跌", "开仓价": current_price, "金额": bet,
                "结算时间": now + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

# ==========================================
# 6. 自动结算 (沿用你代码的 W/L 逻辑)
# ==========================================
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "看涨" and current_price > od["开仓价"]) or \
                  (od["方向"] == "看跌" and current_price < od["开仓价"])
            st.session_state.balance += (od["金额"] * 1.8) if win else 0
            od["状态"] = "已结算 (WIN)" if win else "已结算 (LOSS)"
            updated = True
    if updated: save_data(st.session_state.balance)

# 强制页面每 2 秒静默刷新数据 (不会重置 TV 图表)
time.sleep(2)
st.rerun()
