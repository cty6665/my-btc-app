import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# =========================
# 1. 页面配置 & 样式（Binance 亮色）
# =========================
st.set_page_config(page_title="Pro Trade Simulator", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
.stApp { background:#ffffff; color:#000; }
.price { font-size:36px; font-weight:700; color:#02C076; font-family:Consolas; }
.win { color:#02C076; font-weight:700; }
.loss { color:#CF304A; font-weight:700; }
.card { background:#F8F9FA; border-radius:8px; padding:10px; border:1px solid #EEE; margin-bottom:6px; color:#000; }
.stButton button { height:56px; font-size:20px; font-weight:bold; }
div[data-testid="stMetricValue"] { color: #000 !important; }
p, span, label { color: #000 !important; }
</style>
""", unsafe_allow_html=True)

# 自动刷新（5秒，保证性能与实时的平衡）
st_autorefresh(interval=5000, key="binance_refresh")

# =========================
# 2. Binance API (修复时差与报错)
# =========================
def fetch_klines(symbol, interval, limit=100):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            headers=headers, timeout=5
        )
        if r.status_code == 200:
            df = pd.DataFrame(r.json(), columns=[
                "time","open","high","low","close","vol","ct","qa","n","tb","tq","ig"
            ])
            # 修复：加上 8 小时时差，匹配北京时间
            df["time"] = pd.to_datetime(df["time"], unit="ms") + timedelta(hours=8)
            for c in ["open","high","low","close"]:
                df[c] = df[c].astype(float)
            return df
    except:
        pass
    return pd.DataFrame()

def fetch_price(symbol):
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol}, timeout=3)
        return float(r.json()["price"])
    except:
        return None

# =========================
# 3. 指标计算 (确保变量名准确)
# =========================
def add_indicators(df):
    if df.empty: return df
    # BOLL
    df["MA20"] = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    df["BOLL_UP"] = df["MA20"] + 2 * std
    df["BOLL_DN"] = df["MA20"] - 2 * std
    # MACD
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(span=9).mean()
    df["MACD_HIST"] = df["DIF"] - df["DEA"]
    # MACD BOLL
    m_ma = df["MACD_HIST"].rolling(20).mean()
    m_std = df["MACD_HIST"].rolling(20).std()
    df["M_UP"] = m_ma + 2 * m_std
    df["M_DN"] = m_ma - 2 * m_std
    return df

# =========================
# 4. 初始化状态
# =========================
if "balance" not in st.session_state: st.session_state.balance = 1000.0
if "orders" not in st.session_state: st.session_state.orders = []

# =========================
# 5. 侧边栏 & 数据获取
# =========================
with st.sidebar:
    st.header("⚙️ 合约设置")
    symbol = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT"], index=0)
    interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=1)
    duration = st.radio("结算时长", [5, 10, 30, 60], index=0)
    bet = st.number_input("下单金额 (U)", 1.0, 5000.0, 50.0)
    if st.button("🔄 重置账户"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        st.rerun()

df = fetch_klines(symbol, interval)
df = add_indicators(df)
price = fetch_price(symbol)
# 修复：获取带时区的时间，确保结算准确
now = datetime.now() + timedelta(hours=0) 

# =========================
# 6. 自动结算逻辑
# =========================
if price:
    for od in st.session_state.orders:
        if od["status"] == "OPEN" and now >= od["settle"]:
            win = (od["side"] == "UP" and price > od["entry"]) or (od["side"] == "DOWN" and price < od["entry"])
            if win:
                st.session_state.balance += od["amount"] * 1.8
                od["result"] = "WIN"
            else:
                od["result"] = "LOSS"
            od["status"] = "DONE"

# =========================
# 7. UI 渲染
# =========================
if not df.empty and price:
    c1, c2, c3 = st.columns(3)
    c1.metric("可用余额", f"${st.session_state.balance:.2f}")
    c2.markdown(f"<div class='price'>${price:,.2f}</div>", unsafe_allow_html=True)
    
    # 统计胜率
    done_orders = [o for o in st.session_state.orders if o["status"] == "DONE"]
    wins = len([o for o in done_orders if o["result"] == "WIN"])
    wr = (wins / len(done_orders) * 100) if done_orders else 0
    c3.metric("胜率", f"{wr:.0f}%")

    # --- 专业图表 ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    # 主图
    fig.add_trace(go.Candlestick(x=df["time"], open=df["open"], high=df['high'], low=df['low'], close=df['close'], name="K线"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["time"], y=df["BOLL_UP"], line=dict(color="#FCD535", width=1), name="上轨"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["time"], y=df["BOLL_DN"], line=dict(color="#FCD535", width=1), name="下轨"), row=1, col=1)
    # 副图 (MACD)
    fig.add_trace(go.Bar(x=df["time"], y=df["MACD_HIST"], name="MACD柱"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df["time"], y=df["DIF"], line=dict(color="#2962FF"), name="DIF"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df["time"], y=df["DEA"], line=dict(color="#FF6D00"), name="DEA"), row=2, col=1)
    
    fig.update_layout(height=500, margin=dict(l=0,r=0,t=10,b=0), xaxis_rangeslider_visible=False, template="plotly_white", showlegend=False)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 下单区
    col_up, col_down = st.columns(2)
    if col_up.button("🟢 看涨 (UP)", use_container_width=True):
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"side": "UP", "entry": price, "amount": bet, "settle": now + timedelta(minutes=duration), "status": "OPEN", "result": None})
            st.rerun()

    if col_down.button("🔴 看跌 (DOWN)", use_container_width=True):
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"side": "DOWN", "entry": price, "amount": bet, "settle": now + timedelta(minutes=duration), "status": "OPEN", "result": None})
            st.rerun()
else:
    st.warning("🚀 正在连接币安行情，请稍后...")

# 历史记录
st.markdown("### 📜 交易记录")
for od in reversed(st.session_state.orders[-5:]):
    res = od["result"] if od["result"] else "等待结算..."
    color_class = "win" if od["result"] == "WIN" else "loss" if od["result"] == "LOSS" else ""
    st.markdown(f"""
    <div class="card">
        {od['side']} | 开仓: {od['entry']:.2f} | 金额: {od['amount']}U <br>
        结果: <span class="{color_class}">{res}</span>
    </div>
    """, unsafe_allow_html=True)
