import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置
# ==========================================
st.set_page_config(page_title="Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

if 'balance' not in st.session_state:
    st.session_state.balance = 1000.0
    st.session_state.orders = []

# ==========================================
# 2. 核心：四重渠道抓取价格 (解决重连问题)
# ==========================================
def get_price_final_solution(symbol):
    # 渠道 1: 币安 K 线接口 (你验证过的)
    try:
        res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1", timeout=0.8)
        return float(res.json()[-1][4])
    except: pass

    # 渠道 2: 币安备用 API 节点 (api3)
    try:
        res = requests.get(f"https://api3.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=0.8)
        return float(res.json()['price'])
    except: pass

    # 渠道 3: Crypto.com 公共接口 (不容易被封)
    try:
        res = requests.get(f"https://api.crypto.com/v2/public/get-ticker?instrument_name={symbol.replace('USDT', '_USDT')}", timeout=0.8)
        return float(res.json()['result']['data'][0]['a'])
    except: pass

    # 渠道 4: Gate.io 公共接口 (极稳)
    try:
        res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={symbol.replace('USDT', '_USDT')}", timeout=0.8)
        return float(res.json()[0]['last'])
    except: pass

    return None

# ==========================================
# 3. 界面布局 (TV图表 + 实时价格)
# ==========================================
# 获取最新价
coin = st.sidebar.selectbox("品种", ["BTCUSDT", "ETHUSDT"], index=0)
price = get_price_multi_source = get_price_final_solution(coin)

col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # 保持 TV 图表不变，且不随刷新重置
    @st.cache_resource
    def load_tv(s):
        html = f"""
            <div id="tv-chart" style="height:500px;"></div>
            <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
            <script type="text/javascript">
            new TradingView.widget({{
              "autosize": true, "symbol": "BINANCE:{s}", "interval": "1",
              "theme": "light", "style": "1", "locale": "zh_CN",
              "container_id": "tv-chart", "hide_side_toolbar": false,
              "allow_symbol_change": true, "details": true
            }});
            </script>
        """
        return components.html(html, height=520)
    load_tv(coin)

with col_trade:
    st.metric("余额", f"${st.session_state.balance:,.2f}")
    
    if price:
        st.markdown(f"""
            <div style="background:#02C076; padding:15px; border-radius:10px; text-align:center;">
                <p style="color:white; margin:0;">实时执行价</p>
                <h1 style="color:white; margin:0; font-size:35px;">{price:,.2f}</h1>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.error("🆘 所有接口均被拦截，请尝试刷新页面或检查网络")

    # 下单区
    duration = st.selectbox("周期", [1, 5, 10, 30, 60])
    amt = st.number_input("金额", 10, 1000, 50)
    
    if st.button("🟢 看涨", use_container_width=True) and price:
        st.session_state.balance -= amt
        st.session_state.orders.append({
            "dir": "涨", "p": price, "amt": amt, 
            "end": datetime.now() + timedelta(minutes=duration), "status": "待结算"
        })
        st.rerun()

    if st.button("🔴 看跌", use_container_width=True) and price:
        st.session_state.balance -= amt
        st.session_state.orders.append({
            "dir": "跌", "p": price, "amt": amt, 
            "end": datetime.now() + timedelta(minutes=duration), "status": "待结算"
        })
        st.rerun()

# ==========================================
# 4. 自动结算
# ==========================================
if price:
    now = datetime.now()
    for od in st.session_state.orders:
        if od["status"] == "待结算" and now >= od["end"]:
            win = (od["dir"] == "涨" and price > od["p"]) or (od["dir"] == "跌" and price < od["p"])
            st.session_state.balance += (od["amt"] * 1.8) if win else 0
            od["status"] = "WIN" if win else "LOSS"

# 2秒自动重跑刷新价格
time.sleep(2)
st.rerun()
