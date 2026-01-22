import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 样式配置
# ==========================================
st.set_page_config(page_title="Binance Terminal", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    .price-text { font-family: 'Consolas', monospace; font-size: 34px; font-weight: bold; color: #02C076; }
    .pos-card { border-left: 5px solid #FCD535; padding: 10px; background: #F8F9FA; border-radius: 8px; border: 1px solid #EEE; color: #000; }
    div[data-testid="stMetricValue"] { color: #000000 !important; }
    .stButton button { width: 100%; height: 55px; font-size: 20px !important; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="binance_refresh")

# ==========================================
# 2. 核心：币安 API 调用 (带浏览器伪装)
# ==========================================
def fetch_binance_data(symbol, interval):
    # 模拟真实浏览器的 Header
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    base_url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 60}
    
    try:
        # 增加超时控制，防止程序卡死
        response = requests.get(base_url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data, columns=['time','open','high','low','close','v','ct','qa','tr','tb','tq','ig'])
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for col in ['open','high','low','close']: df[col] = df[col].astype(float)
            
            # 获取最新价
            ticker_url = "https://api.binance.com/api/v3/ticker/price"
            price_res = requests.get(ticker_url, params={"symbol": symbol}, headers=headers, timeout=3).json()
            curr_price = float(price_res['price'])
            return curr_price, df
    except Exception as e:
        st.sidebar.warning(f"正在切换节点... {e}")
    return None, None

# ==========================================
# 3. 初始化与逻辑
# ==========================================
if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

with st.sidebar:
    st.header("⚙️ 交易设置")
    coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    k_type = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"])
    unit_map = {"5分钟": 5, "10分钟": 10, "30分钟": 30}
    dur_label = st.radio("结算时长", list(unit_map.keys()), index=1)
    duration_mins = unit_map[dur_label]
    if st.button("重置数据"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        st.rerun()

price, df = fetch_binance_data(coin, k_type)
now = datetime.now()

if price:
    # 自动结算
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "看涨" and price > od["开仓价"]) or (od["方向"] == "看跌" and price < od["开仓价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "WIN", "颜色": "#02C076"})
            else:
                od.update({"状态": "已结算", "结果": "LOSS", "颜色": "#CF304A"})

    # UI 渲染
    c1, c2, c3 = st.columns(3)
    c1.metric("余额", f"${st.session_state.balance:.1f}")
    c2.metric("当前价", f"${price:,.2f}")
    c3.metric("单数", len(st.session_state.orders))

    # K线图
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#02C076', decreasing_line_color='#CF304A'
    )])
    fig.update_layout(height=400, template="plotly_white", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 下单
    order_val = st.number_input("下单金额 (U)", 10.0, 5000.0, 50.0)
    col1, col2 = st.columns(2)
    if col1.button("🟢 看涨", type="primary"):
        if st.session_state.balance >= order_val:
            st.session_state.balance -= order_val
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "看涨", "开仓价": price, "金额": order_val, "状态": "待结算", "结果": None
            })
            st.rerun()
    if col2.button("🔴 看跌"):
        if st.session_state.balance >= order_val:
            st.session_state.balance -= order_val
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "看跌", "开仓价": price, "金额": order_val, "状态": "待结算", "结果": None
            })
            st.rerun()
else:
    st.error("⚠️ 币安接口连接中，请稍候...")

st.divider()
for od in reversed(st.session_state.orders[-3:]):
    color = od.get("颜色", "#FCD535")
    st.markdown(f"<div class='pos-card' style='border-left-color:{color}'>{od['方向']} ${od['开仓价']} | {od['金额']}U | {od['状态']}</div>", unsafe_allow_html=True)
