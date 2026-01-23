import streamlit as st
import pandas as pd
import requests
import time
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 配置 (保持你的存储文件名)
# ==========================================
DB_FILE = "user_data.json"
st.set_page_config(page_title="BTC Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 2. 移植你代码中“必通”的行情获取函数
# ==========================================
def get_verified_price(symbol):
    try:
        # 完全照搬你代码里的 K 线获取逻辑
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, params=params, timeout=1.5)
        data = res.json()
        # 取最新一根 K 线的收盘价，这在你那边是验证通过的
        return float(data[-1][4])
    except Exception as e:
        return None

# ==========================================
# 3. 页面布局与 TradingView 图表
# ==========================================
# 侧边栏选择器
coin = st.sidebar.selectbox("选择品种", ["BTCUSDT", "ETHUSDT"], index=0)
bet = st.sidebar.number_input("下单金额", 10.0, 1000.0, 50.0)
duration = st.sidebar.radio("周期", [1, 5, 10])

# 获取当前实时价格 (使用你验证过的函数)
price = get_verified_price(coin)

col_left, col_right = st.columns([3, 1])

with col_left:
    # 这里的 TV 图表负责视觉，走手机流量，不影响后端
    tv_html = f"""
        <div id="tv-chart" style="height:500px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
          "timezone": "Asia/Shanghai", "theme": "light", "style": "1",
          "locale": "zh_CN", "container_id": "tv-chart",
          "hide_side_toolbar": false, "allow_symbol_change": true,
          "studies": ["MAExp@tv-basicstudies"]
        }});
        </script>
    """
    components.html(tv_html, height=500)

with col_right:
    st.write("💰 账户余额")
    st.subheader(f"${st.session_state.balance:.2f}")
    
    st.write("📈 实时执行价")
    if price:
        # 这里就是你代码里那个会跳动的价格数字
        st.markdown(f"<h1 style='color:#02C076; font-family:monospace;'>{price:,.2f}</h1>", unsafe_allow_html=True)
    else:
        st.error("报价接口重连中...")

    # 下单按钮逻辑
    if st.button("🟢 看涨 (UP)", type="primary", use_container_width=True):
        if price:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "方向": "看涨", "开仓价": price, "金额": bet,
                "结算时间": datetime.now() + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

    st.write("") # 间距

    if st.button("🔴 看跌 (DOWN)", use_container_width=True):
        if price:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "方向": "看跌", "开仓价": price, "金额": bet,
                "结算时间": datetime.now() + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

# ==========================================
# 4. 自动刷新逻辑 (模仿你代码的 2 秒轮询)
# ==========================================
# 只要有待结算订单，我们就检查逻辑
for od in st.session_state.orders:
    if od["状态"] == "待结算" and datetime.now() >= od["结算时间"]:
        win = (od["方向"] == "看涨" and price > od["开仓价"]) or \
              (od["方向"] == "看跌" and price < od["开仓价"])
        st.session_state.balance += (od["金额"] * 1.8) if win else 0
        od["状态"] = "已结算(W)" if win else "已结算(L)"

# 每 2 秒重新运行一次脚本，刷新价格
time.sleep(2)
st.rerun()
