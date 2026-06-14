import streamlit as st
import pandas as pd
import json
import time
import threading
import websocket
from datetime import datetime, timedelta
from collections import deque
from streamlit_lightweight_charts import renderLightweightCharts

# ==========================================
# 1. 核心配置与状态初始化
# ==========================================
st.set_page_config(page_title="Binary Options Pro", layout="wide")

DB_FILE = "trading_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e"
SUPPORTED_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
MAX_POSITION_RATIO = 0.30

theme = {
    "bg": "#0b0e11", "text": "#eaecef", "card": "#181a20", "border": "#2b3139",
    "win": "#0ecb81", "loss": "#f6465d", "muted": "#848e9c", "brand": "#f0b90b"
}

st.markdown(f"""
<style>
.stApp {{ background-color: {theme['bg']}; color: {theme['text']}; }}
.metric-card {{ background: {theme['card']}; padding: 15px; border-radius: 8px; border: 1px solid {theme['border']}; }}
.winning {{ border-left: 4px solid {theme['win']}; }}
.losing {{ border-left: 4px solid {theme['loss']}; }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 数据持久化与初始化
# ==========================================
def load_db():
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
        return data.get("balance", 10000.0), data.get("orders", [])
    except:
        return 10000.0, []

def save_db(balance, orders):
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": orders}, f)

if "init" not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
    st.session_state.coin = "BTCUSDT"
    st.session_state.interval = "1m"
    st.session_state.duration = "5分钟"
    st.session_state.bet_amt = 100.0
    st.session_state.prices = {c: 0.0 for c in SUPPORTED_COINS}
    st.session_state.klines = deque(maxlen=500)
    st.session_state.ws_active = False
    st.session_state.ui_heartbeat = 0
    st.session_state.init = True

# ==========================================
# 3. WebSocket 流管理
# ==========================================
def connect_ws():
    def on_message(ws, message):
        data = json.loads(message)
        if "k" in data:
            kline = data["k"]
            close_price = float(kline["c"])
            st.session_state.prices[st.session_state.coin] = close_price
            new_bar = {
                "time": int(kline["t"]) // 1000,
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": close_price
            }
            if st.session_state.klines and st.session_state.klines[-1]["time"] == new_bar["time"]:
                st.session_state.klines[-1] = new_bar
            else:
                st.session_state.klines.append(new_bar)
            st.session_state.ui_heartbeat += 1

    def on_error(ws, error):
        st.error(f"WebSocket Error: {error}")

    def on_close(ws, *args):
        st.warning("WebSocket disconnected, reconnecting...")
        threading.Timer(5, connect_ws).start()

    ws_url = f"wss://stream.binance.com:9443/ws/{st.session_state.coin.lower()}@kline_{st.session_state.interval}"
    ws = websocket.WebSocketApp(ws_url,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    wst = threading.Thread(target=ws.run_forever, daemon=True)
    wst.start()
    st.session_state.ws_active = True

if not st.session_state.ws_active:
    connect_ws()

# ==========================================
# 4. 核心交易逻辑
# ==========================================
def commit_order(direction):
    if st.session_state.bet_amt > st.session_state.balance * MAX_POSITION_RATIO:
        st.toast("⚠️ 超过风控限制", icon="⚠️")
        return

    if st.session_state.bet_amt > st.session_state.balance:
        st.toast("⚠️ 余额不足", icon="⚠️")
        return

    duration_map = {"5分钟":5, "10分钟":10, "30分钟":30, "1小时":60}
    settle_time = datetime.utcnow() + timedelta(minutes=duration_map[st.session_state.duration])
    
    st.session_state.balance -= st.session_state.bet_amt
    st.session_state.orders.append({
        "asset": st.session_state.coin,
        "direction": direction,
        "amount": st.session_state.bet_amt,
        "open_price": st.session_state.prices[st.session_state.coin],
        "open_time": datetime.utcnow(),
        "settle_time": settle_time,
        "status": "pending"
    })
    save_db(st.session_state.balance, st.session_state.orders)
    st.toast(f"✅ 已开仓 {direction} {st.session_state.coin} {st.session_state.bet_amt}U", icon="✅")

# ==========================================
# 5. 界面渲染
# ==========================================
st.title("📈 二元期权模拟交易终端")

# 实时数据面板
col1, col2, col3 = st.columns(3)
col1.metric("账户余额", f"${st.session_state.balance:.2f}", delta_color="off")
col2.metric("当前价格", f"${st.session_state.prices[st.session_state.coin]:.4f}")
col3.metric("待结算订单", len([o for o in st.session_state.orders if o["status"] == "pending"]))

# 交易面板
with st.container():
    st.subheader("极速交易")
    col1, col2, col3 = st.columns([1, 1, 1])
    st.session_state.coin = col1.selectbox("交易对", SUPPORTED_COINS)
    st.session_state.interval = col2.selectbox("K线周期", ["1m", "5m", "15m", "1h"])
    st.session_state.duration = col3.selectbox("合约时长", ["5分钟", "10分钟", "30分钟", "1小时"])
    
    col1, col2 = st.columns([2, 1])
    st.session_state.bet_amt = col1.number_input("下注金额", min_value=10.0, max_value=10000.0, value=100.0, step=10.0)
    col2.button("🟢 看涨", on_click=commit_order, args=("call",), type="primary", use_container_width=True)
    col2.button("🔴 看跌", on_click=commit_order, args=("put",), type="secondary", use_container_width=True)

# 图表区域
with st.container():
    st.subheader("实时行情")
    chart_data = list(st.session_state.klines)
    price_lines = []
    for order in st.session_state.orders:
        if order["status"] == "pending" and order["asset"] == st.session_state.coin:
            color = theme["win"] if order["direction"] == "call" else theme["loss"]
            price_lines.append({
                "price": order["open_price"],
                "color": color,
                "lineWidth": 1,
                "lineStyle": 1,
                "axisLabelVisible": True,
                "title": f"{order['direction']} {order['amount']}U"
            })
    
    chart_config = {
        "layout": {"background": theme["bg"], "textColor": theme["text"]},
        "grid": {"vertLines": {"color": theme["border"]}, "horzLines": {"color": theme["border"]}},
        "crosshair": {"mode": 0},
        "timeScale": {"timeVisible": True, "secondsVisible": False}
    }
    renderLightweightCharts([{
        "chart": chart_config,
        "series": [{
            "type": "Candlestick",
            "data": chart_data,
            "options": {
                "upColor": theme["win"],
                "downColor": theme["loss"],
                "borderUpColor": theme["win"],
                "borderDownColor": theme["loss"],
                "wickUpColor": theme["win"],
                "wickDownColor": theme["loss"]
            },
            "priceLines": price_lines
        }]
    }], key="chart")

# 持仓管理
with st.container():
    st.subheader("持仓监控")
    now = datetime.utcnow()
    for order in st.session_state.orders:
        if order["status"] == "pending":
            remaining = max(0, (order["settle_time"] - now).seconds)
            h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
            status_color = theme["win"] if (
                (order["direction"] == "call" and st.session_state.prices[order["asset"]] > order["open_price"]) or
                (order["direction"] == "put" and st.session_state.prices[order["asset"]] < order["open_price"])
            ) else theme["loss"]
            
            st.markdown(f"""
            <div class="metric-card {'winning' if status_color == theme['win'] else 'losing'}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div><b>{order['direction'].upper()}</b> {order['asset']} {order['amount']}U</div>
                    <div style="color: {status_color}; font-weight: bold;">
                        {h:02d}:{m:02d}:{s:02d}
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px;">
                    <div>开仓价: ${order['open_price']:.4f}</div>
                    <div>当前价: ${st.session_state.prices[order['asset']]:.4f}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# 结算逻辑
for order in st.session_state.orders:
    if order["status"] == "pending" and datetime.utcnow() >= order["settle_time"]:
        settle_price = st.session_state.prices[order["asset"]] or order["open_price"]
        win = (
            (order["direction"] == "call" and settle_price > order["open_price"]) or
            (order["direction"] == "put" and settle_price < order["open_price"])
        )
        st.session_state.balance += order["amount"] * 1.8 if win else 0
        order["status"] = "closed"
        order["settle_price"] = settle_price
        save_db(st.session_state.balance, st.session_state.orders)
        st.experimental_rerun()

# 侧边栏管理
with st.sidebar:
    st.markdown("### 系统管理")
    if st.checkbox("🔧 重置数据"):
        password = st.text_input("授权码", type="password")
        if password and hashlib.sha256(password.encode()).hexdigest() == AUTH_HASH:
            if st.button("🔥 确认重置"):
                st.session_state.balance = 10000.0
                st.session_state.orders = []
                save_db(10000.0, [])
                st.experimental_rerun()
        elif password:
            st.error("授权码错误")

# 部署说明
st.sidebar.markdown("""
### 侧边栏说明
- 功能1：实时行情
- 功能2：持仓统计
""") 
