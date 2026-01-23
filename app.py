import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置与数据存储
# ==========================================
st.set_page_config(page_title="Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "user_data.json"

if 'balance' not in st.session_state:
    st.session_state.balance = 1000.0
    st.session_state.orders = []

# ==========================================
# 2. 你的“必通”报价逻辑 (复刻自 app.py.txt)
# ==========================================
def get_verified_price(symbol):
    try:
        # 使用你验证过的 klines 接口
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, params=params, timeout=1.5)
        if res.status_code == 200:
            return float(res.json()[-1][4])
    except:
        return None
    return None

# ==========================================
# 3. 页面布局
# ==========================================
# --- 顶部固定区 ---
st.markdown(f"<h2 style='text-align:center;'>账户余额: ${st.session_state.balance:,.2f}</h2>", unsafe_allow_html=True)

# 侧边栏
with st.sidebar:
    coin = st.selectbox("交易品种", ["BTCUSDT", "ETHUSDT"], index=0)
    duration = st.selectbox("周期(分钟)", [1, 5, 10, 30, 60], index=2)
    amt = st.number_input("下单金额", 10.0, 2000.0, 50.0)
    if st.button("🚨 清空记录"):
        st.session_state.orders = []
        st.rerun()

# 获取最新报价
price = get_verified_price(coin)

# --- 主交互区 ---
col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # 【关键】使用缓存保护 TV 图表，确保它不随价格刷新而变
    @st.cache_resource
    def display_tv_chart(symbol):
        tv_html = f"""
            <div id="tv-chart" style="height:500px;"></div>
            <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
            <script type="text/javascript">
            new TradingView.widget({{
              "autosize": true, "symbol": "BINANCE:{symbol}", "interval": "1",
              "theme": "light", "style": "1", "locale": "zh_CN",
              "container_id": "tv-chart", "hide_side_toolbar": false,
              "allow_symbol_change": true, "details": true,
              "studies": ["MAExp@tv-basicstudies"]
            }});
            </script>
        """
        return components.html(tv_html, height=520)
    
    display_tv_chart(coin)

with col_trade:
    # 价格跳动区
    if price:
        st.markdown(f"""
            <div style="background:#f0f2f6; padding:15px; border-radius:10px; text-align:center; border:2px solid #02C076;">
                <p style="margin:0; font-size:14px; color:#666;">实时执行价</p>
                <h1 style="margin:0; color:#02C076; font-family:monospace;">{price:,.2f}</h1>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.error("报价重连中...")

    st.write("") # 间距

    # 下单按钮
    if st.button("🟢 看涨 (UP)", use_container_width=True):
        if price:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "time": datetime.now(), "end": datetime.now() + timedelta(minutes=duration),
                "dir": "涨", "p": price, "amt": amt, "status": "待结算"
            })
            st.toast("下单成功!")
            st.rerun()

    if st.button("🔴 看跌 (DOWN)", use_container_width=True):
        if price:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "time": datetime.now(), "end": datetime.now() + timedelta(minutes=duration),
                "dir": "跌", "p": price, "amt": amt, "status": "待结算"
            })
            st.toast("下单成功!")
            st.rerun()

# ==========================================
# 4. 自动化结算逻辑 (后台运行)
# ==========================================
now = datetime.now()
if price:
    for od in st.session_state.orders:
        if od["status"] == "待结算" and now >= od["end"]:
            win = (od["dir"] == "涨" and price > od["p"]) or (od["dir"] == "跌" and price < od["p"])
            st.session_state.balance += (od["amt"] * 1.8) if win else 0
            od["status"] = "WIN" if win else "LOSS"

# 简易记录
st.write("---")
for od in reversed(st.session_state.orders[-3:]):
    st.write(f"【{od['status']}】{od['dir']} @{od['p']} (到期:{od['end'].strftime('%H:%M:%S')})")

# 2秒一次强制刷新（只刷价格和状态，不刷图表）
time.sleep(2)
st.rerun()


