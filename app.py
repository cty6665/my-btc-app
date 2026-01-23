import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
#from websocket import create_connection

# ==================================================
# 页面设置 & 样式（Binance 亮色）
# ==================================================
st.set_page_config(page_title="Event Contract Simulator", layout="wide")

st.markdown("""
<style>
.stApp { background:#ffffff; color:#000; }
.price { font-size:38px; font-weight:700; color:#02C076; font-family:Consolas; }
.win { color:#02C076; font-weight:700; }
.loss { color:#CF304A; font-weight:700; }
.card { background:#F8F9FA; border-radius:8px; padding:8px; border:1px solid #EEE; }
.stButton button { height:56px; font-size:20px; }
</style>
""", unsafe_allow_html=True)

# 页面刷新（只负责 UI & 结算）
st_autorefresh(interval=1000, key="refresh")

# ==================================================
# WebSocket 最新价（稳定核心）
# ==================================================
@st.cache_resource
def price_socket(symbol):
    ws = create_connection(f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade")
    return ws

def get_realtime_price(ws):
    try:
        msg = json.loads(ws.recv())
        return float(msg["p"])
    except:
        return None

# ==================================================
# REST：K线（低频，安全）
# ==================================================
@st.cache_data(ttl=10)
def fetch_klines(symbol, interval, limit=200):
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=5
    )
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","vol",
        "ct","qa","n","tb","tq","ig"
    ])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    for c in ["open","high","low","close"]:
        df[c] = df[c].astype(float)
    return df

# ==================================================
# 指标：BOLL + MACD + MACD-BOLL
# ==================================================
def add_indicators(df):
    # BOLL（主图）
    df["MA20"] = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    df["BOLL_UP"] = df["MA20"] + 2 * std
    df["BOLL_DN"] = df["MA20"] - 2 * std

    # MACD
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(span=9).mean()
    df["MACD"] = df["DIF"] - df["DEA"]

    # MACD 上的 BOLL（你要求的）
    macd_ma = df["MACD"].rolling(20).mean()
    macd_std = df["MACD"].rolling(20).std()
    df["MACD_UP"] = macd_ma + 2 * macd_std
    df["MACD_DN"] = macd_ma - 2 * macd_std

    return df

# ==================================================
# Session State
# ==================================================
if "balance" not in st.session_state:
    st.session_state.balance = 100.0
if "orders" not in st.session_state:
    st.session_state.orders = []
if "ws" not in st.session_state:
    st.session_state.ws = None

# ==================================================
# Sidebar
# ==================================================
with st.sidebar:
    st.header("⚙️ 合约设置")
    symbol = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT"])
    interval = st.selectbox("K线周期", ["1m","5m","15m","30m","1h"], index=1)
    duration = st.radio("结算时间（分钟）", [1,5,15,30,60], index=1)
    bet = st.number_input("下注金额(U)", 1.0, 100.0, 10.0)

    if st.button("🔄 重置账户"):
        st.session_state.balance = 100.0
        st.session_state.orders = []
        st.rerun()

# ==================================================
# 初始化 WebSocket
# ==================================================
if st.session_state.ws is None:
    st.session_state.ws = price_socket(symbol)

price = get_realtime_price(st.session_state.ws)
if price is None:
    st.stop()

now = datetime.now()

# ==================================================
# 自动结算（事件合约核心）
# ==================================================
for od in st.session_state.orders:
    if od["status"] == "OPEN" and now >= od["settle"]:
        win = (od["side"]=="UP" and price > od["entry"]) or \
              (od["side"]=="DOWN" and price < od["entry"])
        if win:
            st.session_state.balance += od["amount"] * 1.8
            od["result"] = "W"
        else:
            od["result"] = "L"
        od["status"] = "DONE"

# ==================================================
# 顶部信息
# ==================================================
c1,c2,c3 = st.columns(3)
c1.metric("余额", f"{st.session_state.balance:.2f} U")
c2.markdown(f"<div class='price'>{price:,.2f}</div>", unsafe_allow_html=True)
c3.metric("当前周期", interval)

# ==================================================
# 图表
# ==================================================
df = add_indicators(fetch_klines(symbol, interval))

fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    row_heights=[0.7, 0.3]
)

# K线 + BOLL
fig.add_candlestick(
    x=df["time"], open=df["open"], high=df["high"],
    low=df["low"], close=df["close"],
    increasing_line_color="#02C076",
    decreasing_line_color="#CF304A",
    row=1, col=1
)
fig.add_scatter(x=df["time"], y=df["BOLL_UP"], line=dict(color="#FCD535"), row=1, col=1)
fig.add_scatter(x=df["time"], y=df["BOLL_DN"], line=dict(color="#FCD535"), row=1, col=1)
fig.add_scatter(x=df["time"], y=df["MA20"], line=dict(color="#888"), row=1, col=1)

# MACD + MACD-BOLL
fig.add_bar(x=df["time"], y=df["MACD"], row=2, col=1)
fig.add_scatter(x=df["time"], y=df["DIF"], line=dict(color="#2962FF"), row=2, col=1)
fig.add_scatter(x=df["time"], y=df["DEA"], line=dict(color="#FF6D00"), row=2, col=1)
fig.add_scatter(x=df["time"], y=df["MACD_UP"], line=dict(color="#FCD535", dash="dot"), row=2, col=1)
fig.add_scatter(x=df["time"], y=df["MACD_DN"], line=dict(color="#FCD535", dash="dot"), row=2, col=1)

fig.update_layout(
    height=650,
    margin=dict(l=0,r=0,t=10,b=0),
    xaxis_rangeslider_visible=False,
    template="plotly_white"
)

st.plotly_chart(fig, use_container_width=True)

# ==================================================
# 下单
# ==================================================
col1,col2 = st.columns(2)

if col1.button("🟢 看涨 UP"):
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "side":"UP",
            "entry":price,
            "amount":bet,
            "settle":now+timedelta(minutes=duration),
            "status":"OPEN",
            "result":None
        })
        st.rerun()

if col2.button("🔴 看跌 DOWN"):
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "side":"DOWN",
            "entry":price,
            "amount":bet,
            "settle":now+timedelta(minutes=duration),
            "status":"OPEN",
            "result":None
        })
        st.rerun()

