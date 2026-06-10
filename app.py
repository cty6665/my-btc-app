import streamlit as st
import pandas as pd
import json
import os
import time
import threading
import websocket
import requests
import hashlib
from collections import deque
from datetime import datetime, timedelta
from streamlit_lightweight_charts import renderLightweightCharts

# ==========================================
# 1. 页面配置与专业深色 UI 注入
# ==========================================
st.set_page_config(
    page_title="Binary Options Pro Terminal",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_FILE = "event_trading_ws_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e"  # SHA256("522087")
SUPPORTED_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
MAX_POSITION_RATIO = 0.30  # 风控：单笔委托不超过余额 30%

theme = {
    "bg": "#0b0e11", "text": "#eaecef", "card": "#181a20", "border": "#2b3139",
    "win": "#0ecb81", "loss": "#f6465d", "muted": "#848e9c", "brand": "#f0b90b"
}

st.markdown(f"""
<style>
.stApp {{ background-color: {theme['bg']}; color: {theme['text']}; }}
[data-testid="stStatusWidget"] {{ display: none !important; }}
.metric-card {{ background: {theme['card']}; padding: 15px; border-radius: 8px; border: 1px solid {theme['border']}; text-align: center; }}
.metric-label {{ color: {theme['muted']}; font-size: 0.8rem; margin-bottom: 4px; }}
.metric-value {{ font-size: 1.5rem; font-weight: bold; }}
.winning-bg {{ background: linear-gradient(90deg, {theme['win']}1A 0%, {theme['card']} 100%); border-left: 4px solid {theme['win']}; }}
.losing-bg {{ background: linear-gradient(90deg, {theme['loss']}1A 0%, {theme['card']} 100%); border-left: 4px solid {theme['loss']}; }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 数据原子化落盘引擎
# ==========================================
def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            orders = data.get("orders", [])
            for od in orders:
                for key in ["开仓时间", "结算time"]:
                    if od.get(key) and isinstance(od[key], str):
                        od[key] = datetime.strptime(od[key], "%Y-%m-%d %H:%M:%S")
            return data.get("balance", 10000.0), orders
    except Exception as e:
        st.error(f"数据库加载错误: {e}")
    return 10000.0, []

def save_db_atomic(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ["开仓时间", "结算time"]:
            if isinstance(tmp.get(key), datetime):
                tmp[key] = tmp[key].strftime("%Y-%m-%d %H:%M:%S")
        ser.append(tmp)
    tmp_file = f"{DB_FILE}.tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump({"balance": balance, "orders": ser}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, DB_FILE)
    except Exception as e:
        st.error(f"数据库保存错误: {e}")

# ==========================================
# 3. 状态管理与内存池初始化
# ==========================================
if "init_done" not in st.session_state:
    b, o = load_db()
    st.session_state.balance = b
    st.session_state.orders = o
    st.session_state.coin = "BTCUSDT"
    st.session_state.interval = "1m"
    st.session_state.contract_dur = "5分钟"
    st.session_state.bet_amt = 100.0
    # ✅ 核心修复：引入心跳计数器，解决 Streamlit 后台线程不刷新 UI 的问题
    st.session_state.ui_heartbeat = 0
    st.session_state.memory_pool = {
        "klines": deque(maxlen=500),
        "prices": {c: 0.0 for c in SUPPORTED_COINS},
        "ws_active_key": "",
        "ws_streams": {},
    }
    st.session_state.init_done = True

pool = st.session_state.memory_pool

# ==========================================
# 4. WebSocket 流管理 (解决行情不刷新)
# ==========================================
def fetch_price_rest(symbol: str) -> float:
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=3).json()
        return float(res.get("price", 0.0))
    except Exception:
        return 0.0

def fetch_klines_rest(symbol: str, interval: str):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=500", timeout=5).json()
        pool["klines"].clear()
        for k in res:
            pool["klines"].append({"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])})
        pool["prices"][symbol] = float(res[-1][4])
    except Exception:
        pass

def _kline_stream_worker(symbol: str, interval: str):
    ws_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
    stream_key = f"{symbol}_{interval}"

    def on_message(ws, message):
        try:
            data = json.loads(message)
            if "k" in data:
                k = data["k"]
                close_price = float(k["c"])
                pool["prices"][symbol] = close_price
                if pool["ws_active_key"] == stream_key:
                    bar = {"time": k["t"] // 1000, "open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]), "close": close_price}
                    if pool["klines"] and pool["klines"][-1]["time"] == bar["time"]:
                        pool["klines"][-1] = bar
                    else:
                        pool["klines"].append(bar)
                    # ✅ 触发 UI 刷新
                    st.session_state.ui_heartbeat += 1
        except Exception:
            pass

    while True:
        try:
            ws = websocket.WebSocketApp(ws_url, on_message=on_message)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception:
            pass
        time.sleep(3)

def _ticker_stream_worker(symbol: str):
    ws_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@ticker"

    def on_message(ws, message):
        try:
            data = json.loads(message)
            if "c" in data:
                pool["prices"][symbol] = float(data["c"])
                st.session_state.ui_heartbeat += 1
        except Exception:
            pass

    while True:
        try:
            ws = websocket.WebSocketApp(ws_url, on_message=on_message)
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception:
            pass
        time.sleep(3)

def ensure_kline_stream(symbol: str, interval: str):
    ws_key = f"{symbol}_{interval}"
    if pool["ws_active_key"] != ws_key:
        fetch_klines_rest(symbol, interval)
        pool["ws_active_key"] = ws_key
        t = pool["ws_streams"].get(ws_key)
        if t is None or not t.is_alive():
            new_t = threading.Thread(target=_kline_stream_worker, args=(symbol, interval), daemon=True)
            new_t.start()
            pool["ws_streams"][ws_key] = new_t

def ensure_ticker_streams_for_pending():
    active_non_primary = {o["资产"] for o in st.session_state.orders if o["状态"] == "待结算" and o["资产"] != st.session_state.coin}
    for asset in active_non_primary:
        key = f"ticker_{asset}"
        t = pool["ws_streams"].get(key)
        if t is None or not t.is_alive():
            if pool["prices"].get(asset, 0.0) == 0.0:
                pool["prices"][asset] = fetch_price_rest(asset)
            new_t = threading.Thread(target=_ticker_stream_worker, args=(asset,), daemon=True)
            new_t.start()
            pool["ws_streams"][key] = new_t

# ==========================================
# 5. 图表分片 (依赖心跳刷新)
# ==========================================
@st.fragment(run_every=1)
def chart_fragment():
    _ = st.session_state.ui_heartbeat  # 强制依赖
    if not pool["klines"]:
        st.info("⏳ 正在连接 WebSocket 数据流，请稍候...")
        return

    series_data = list(pool["klines"])
    price_lines = []
    for o in st.session_state.orders:
        if o["状态"] == "待结算" and o["资产"] == st.session_state.coin:
            color = theme["win"] if o["方向"] == "看涨" else theme["loss"]
            price_lines.append({"price": float(o["开仓价"]), "color": color, "lineWidth": 1, "lineStyle": 1, "axisLabelVisible": True, "title": f"{o['方向']} {o['金额']}U"})

    chart_opts = {"layout": {"background_color": theme["bg"], "text_color": theme["muted"]}, "grid": {"vertLines": {"color": "#1f2226"}, "horzLines": {"color": "#1f2226"}}, "crosshair": {"mode": 0}, "timeScale": {"timeVisible": True, "secondsVisible": False}}
    renderLightweightCharts([{"chart": chart_opts, "series": [{"type": "Candlestick", "data": series_data, "options": {"upColor": theme["win"], "downColor": theme["loss"], "borderUpColor": theme["win"], "borderDownColor": theme["loss"], "wickUpColor": theme["win"], "wickDownColor": theme["loss"]}, "priceLines": price_lines}]}], key=f"lwc_{st.session_state.coin}_{st.session_state.interval}")

# ==========================================
# 6. 开仓回调 (二元期权逻辑)
# ==========================================
def commit_order_callback(direction: str):
    c_price = pool["prices"].get(st.session_state.coin, 0.0)
    if c_price == 0:
        st.toast("⚠️ 价格数据未就绪，请稍后重试", icon="⚠️")
        return

    max_bet = st.session_state.balance * MAX_POSITION_RATIO
    if st.session_state.bet_amt > max_bet:
        st.toast(f"🛡️ 超出风控上限（最大 {max_bet:.2f} U）", icon="🛡️")
        return

    if st.session_state.balance < st.session_state.bet_amt:
        st.toast("⚠️ 余额不足", icon="⚠️")
        return

    dur_map = {"5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60, "4小时": 240, "12小时": 720, "24小时": 1440}

    st.session_state.balance -= st.session_state.bet_amt
    open_time = datetime.utcnow() + timedelta(hours=8)
    settle_time = open_time + timedelta(minutes=dur_map[st.session_state.contract_dur])

    st.session_state.orders.append({
        "资产": st.session_state.coin, "方向": direction, "开仓价": c_price, "金额": st.session_state.bet_amt,
        "开仓时间": open_time, "结算time": settle_time, "状态": "待结算"
    })

    save_db_atomic(st.session_state.balance, st.session_state.orders)
    st.toast(f"✅ 已开仓 {st.session_state.coin} {direction} @ {c_price:.4f}", icon="🎯")

# ==========================================
# 7. 业务分片：结算 + 持仓卡片 (依赖心跳刷新)
# ==========================================
@st.fragment(run_every=1)
def operations_fragment():
    _ = st.session_state.ui_heartbeat  # 强制依赖
    live_price = pool["prices"].get(st.session_state.coin, 0.0)
    now = datetime.utcnow() + timedelta(hours=8)

    c1, c2, c3 = st.columns(3)
    c1.markdown(
        f'<div class="metric-card"><div class="metric-label">账户余额 (USDT)</div><div class="metric-value">{st.session_state.balance:.2f}</div></div>',
        unsafe_allow_html=True
    )
    c2.markdown(
        f'<div class="metric-card"><div class="metric-label">当前价格 ({st.session_state.coin})</div><div class="metric-value">{live_price:.4f}</div></div>',
        unsafe_allow_html=True
    )
    c3.markdown(
        f'<div class="metric-card"><div class="metric-label">待结算订单</div><div class="metric-value">{len([o for o in st.session_state.orders if o["状态"] == "待结算"])}</div></div>',
        unsafe_allow_html=True
    )

    # 结算逻辑
    db_dirty = False
    for o in st.session_state.orders:
        if o["状态"] != "待结算" or now < o["结算time"]:
            continue

        settle_price = pool["prices"].get(o["资产"], 0.0)
        if settle_price == 0.0:
            if now - o["结算time"] < timedelta(minutes=2):
                continue
            settle_price = o["开仓价"]

        win = (o["方向"] == "看涨" and settle_price > o["开仓价"]) or (o["方向"] == "看跌" and settle_price < o["开仓价"])
        payout = o["金额"] * 1.80 if win else 0.0

        st.session_state.balance += payout
        o["状态"], o["平仓价"], o["结果"] = "已结算", settle_price, "WIN" if win else "LOSS"
        db_dirty = True
        st.toast(f"🏆 {o['资产']} 盈利 +{o['金额']*0.8:.2f} U" if win else f"💔 {o['资产']} 亏损 -{o['金额']:.2f} U", icon="🏆" if win else "💔")

    if db_dirty:
        save_db_atomic(st.session_state.balance, st.session_state.orders)

    # 持仓监控卡片
    st.markdown("### 实时持仓监控")
    pending = [o for o in st.session_state.orders if o["状态"] == "待结算"]
    if not pending:
        st.caption("暂无活跃合约。")
    else:
        for o in pending:
            rem = max(0, int((o["结算time"] - now).total_seconds()))
            h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
            track_price = pool["prices"].get(o["资产"], o["开仓价"])
            is_win = (o["方向"] == "看涨" and track_price > o["开仓价"]) or (o["方向"] == "看跌" and track_price < o["开仓价"])
            card_cls = "winning-bg" if is_win else "losing-bg"
            status_text, status_color = ("WINNING", theme["win"]) if is_win else ("LOSING", theme["loss"])
            pnl_pct = (track_price - o["开仓价"]) / o["开仓价"] * 100
            pnl_str = f"+{pnl_pct:.3f}%" if pnl_pct >= 0 else f"{pnl_pct:.3f}%"
            pnl_color = theme["win"] if pnl_pct >= 0 else theme["loss"]
            est_pnl = f"+{o['金额'] * 0.8:.2f}" if is_win else f"-{o['金额']:.2f}"

            st.markdown(f"""
            <div class="metric-card {card_cls}" style="margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div><b>{o['资产']} {o['方向']}</b> | {o['金额']}U @ {o['开仓价']:.4f}</div>
                    <div style="color: {status_color}; font-weight: bold;">{status_text}</div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px;">
                    <div>剩余时间: <b>{h:02d}:{m:02d}:{s:02d}</b></div>
                    <div>当前价: <b>{track_price:.4f}</b></div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                    <div>浮动盈亏: <b style="color: {pnl_color};">{pnl_str}</b></div>
                    <div>预计收益: <b style="color: {status_color};">{est_pnl} U</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ==========================================
# 8. 主界面渲染拼装
# ==========================================
st.title("💰 二元期权专业交易终端")
chart_fragment()
operations_fragment()

st.markdown("### 极速交易面板")
tc1, tc2, tc3, tc4, tc5 = st.columns([1, 1, 1, 1.5, 1.5])
with tc1:
    st.session_state.coin = st.selectbox("交易资产", SUPPORTED_COINS, index=SUPPORTED_COINS.index(st.session_state.coin))
with tc2:
    st.session_state.interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h", "4h"], index=0)
with tc3:
    st.session_state.contract_dur = st.selectbox("合约时长", ["5分钟", "10分钟", "30分钟", "1小时", "4小时", "12小时", "24小时"], index=0)
with tc4:
    st.session_state.bet_amt = st.number_input("下注金额 (U)", min_value=10.0, max_value=5000.0, value=st.session_state.bet_amt, step=10.0)
with tc5:
    st.write(""); st.write("")
    bc1, bc2 = st.columns(2)
    with bc1:
        st.button("🟢 买入看涨 (CALL)", on_click=commit_order_callback, args=("看涨",), use_container_width=True, type="primary")
    with bc2:
        st.button("🔴 买入看跌 (PUT)", on_click=commit_order_callback, args=("看跌",), use_container_width=True)

ensure_kline_stream(st.session_state.coin, st.session_state.interval)
ensure_ticker_streams_for_pending()

st.markdown("### 历史结算记录")
history_orders = [o for o in reversed(st.session_state.orders) if o["状态"] == "已结算"]
if not history_orders:
    st.info("暂无历史结算记录。")
else:
    df_data = [{"资产": o["资产"], "方向": o["方向"], "开仓价": f"{o['开仓价']:.4f}", "平仓价": f"{o.get('平仓价', 0):.4f}", "金额": f"{o['金额']} U", "结果": o.get("结果", "N/A"), "时间": o["开仓时间"].strftime("%m-%d %H:%M") if isinstance(o["开仓时间"], datetime) else o["开仓时间"]} for o in history_orders[:50]]
    st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)

# ==========================================
# 9. 侧边栏：管理员控制台 (语法已修复)
# ==========================================
with st.sidebar:
    st.markdown("### 高级控制台")
    if st.checkbox("🔑 激活超级管理员重置"):
        pwd = st.text_input("授权码", type="password")
        if pwd and hashlib.sha256(pwd.encode()).hexdigest() == AUTH_HASH:
            if st.button("🔥 确认格式化账本", type="primary"):
                st.session_state.balance = 10000.0
                st.session_state.orders = []
                save_db_atomic(10000.0, [])
                st.success("数据已原子化抹除！")
                st.rerun()
        elif pwd:
            st.error("授权码错误！")
