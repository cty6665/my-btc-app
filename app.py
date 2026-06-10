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
# 1. 页面配置与专业深色 UI 注入 (保持原样)
# ==========================================
st.set_page_config(
    page_title="Binance Pro Terminal v2",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_FILE = "event_trading_ws_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e"  # SHA256("522087")
SUPPORTED_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
MAX_POSITION_RATIO = 0.30  # 风控：单笔委托不超过余额 30%

theme = {
    "bg": "#0b0e11",
    "text": "#eaecef",
    "card": "#181a20",
    "border": "#2b3139",
    "win": "#0ecb81",
    "loss": "#f6465d",
    "muted": "#848e9c",
    "brand": "#f0b90b"
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
# 2. 数据原子化落盘引擎 (保持原样)
# ==========================================
def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            orders = data.get("orders", [])
            for od in orders:
                for key in ["开仓时间", "结算time"]:
                    if od.get(key):
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
        os.replace(tmp_file, DB_FILE)  # OS 级原子替换，防止文件损坏
    except Exception as e:
        st.error(f"数据库保存错误: {e}")

# ==========================================
# 3. 状态管理与内存池初始化 (关键修改点)
# ==========================================
if "init_done" not in st.session_state:
    b, o = load_db()
    st.session_state.balance = b
    st.session_state.orders = o
    st.session_state.coin = "BTCUSDT"
    st.session_state.interval = "1m"
    st.session_state.contract_dur = "5分钟"
    st.session_state.bet_amt = 100.0
    # ✅ 新增：心跳计数器，用于强制触发 Streamlit 重绘
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
# 4. WebSocket 流管理 (关键修复)
# ==========================================
def fetch_price_rest(symbol: str) -> float:
    try:
        res = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=3
        ).json()
        return float(res.get("price", 0.0))
    except Exception:
        return 0.0

def fetch_klines_rest(symbol: str, interval: str):
    try:
        res = requests.get(
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}&limit=500",
            timeout=5
        ).json()
        pool["klines"].clear()
        for k in res:
            pool["klines"].append({
                "time": int(k[0]) // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4])
            })
        pool["prices"][symbol] = float(res[-1][4])
    except Exception:
        pass

# ✅ 修复核心：在 on_message 回调中直接修改 st.session_state 会导致线程冲突。
# 正确做法：使用一个全局计数器来“通知” Streamlit 有新数据到了。
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
                # ✅ 只有当前活跃流才写入 klines
                if pool["ws_active_key"] == stream_key:
                    bar = {
                        "time": k["t"] // 1000,
                        "open": float(k["o"]),
                        "high": float(k["h"]),
                        "low": float(k["l"]),
                        "close": close_price
                    }
                    if pool["klines"] and pool["klines"][-1]["time"] == bar["time"]:
                        pool["klines"][-1] = bar
                    else:
                        pool["klines"].append(bar)
                    # ✅ 关键修复：收到数据后，增加心跳计数器
                    # 这会强制依赖该状态的 @st.fragment 重新运行
                    st.session_state.ui_heartbeat += 1
        except Exception as e:
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
                # ✅ 同样增加心跳，确保非主图资产的价格更新也能触发结算逻辑
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
            new_t = threading.Thread(
                target=_kline_stream_worker, args=(symbol, interval), daemon=True
            )
            new_t.start()
            pool["ws_streams"][ws_key] = new_t

def ensure_ticker_streams_for_pending():
    active_non_primary = {
        o["资产"] for o in st.session_state.orders
        if o["状态"] == "待结算" and o["资产"] != st.session_state.coin
    }
    for asset in active_non_primary:
        key = f"ticker_{asset}"
        t = pool["ws_streams"].get(key)
        if t is None or not t.is_alive():
            if pool["prices"].get(asset, 0.0) == 0.0:
                pool["prices"][asset] = fetch_price_rest(asset)
            new_t = threading.Thread(
                target=_ticker_stream_worker, args=(asset,), daemon=True
            )
            new_t.start()
            pool["ws_streams"][key] = new_t

# ==========================================
# 5. 图表分片（关键修复：依赖心跳）
# ==========================================
# @st.fragment 依赖 ui_heartbeat，只要有新数据进来，图表就会刷新
@st.fragment(run_every=1)
def chart_fragment():
    # 强制依赖心跳计数器
    st.session_state.ui_heartbeat
    if not pool["klines"]:
        st.info("⏳ 正在连接 WebSocket 数据流，请稍候...")
        return

    series_data = list(pool["klines"])
    price_lines = []
    for o in st.session_state.orders:
        if o["状态"] == "待结算" and o["资产"] == st.session_state.coin:
            color = theme["win"] if o["方向"] == "看涨" else theme["loss"]
            price_lines.append({
                "price": float(o["开仓价"]),
                "color": color,
                "lineWidth": 1,
                "lineStyle": 1,
                "axisLabelVisible": True,
                "title": f"{o['方向']} {o['金额']}U"
            })

    chart_opts = {
        "layout": {"background_color": theme["bg"], "text_color": theme["muted"]},
        "grid": {"vertLines": {"color": "#1f2226"}, "horzLines": {"color": "#1f2226"}},
        "crosshair": {"mode": 0},
        "timeScale": {"timeVisible": True, "secondsVisible": False}
    }

    renderLightweightCharts([{
        "chart": chart_opts,
        "series": [{
            "type": "Candlestick",
            "data": series_data,
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
    }], key=f"lwc_{st.session_state.coin}_{st.session_state.interval}")

# ==========================================
# 6. 开仓回调（保持原样）
# ==========================================
def commit_order_callback(direction: str):
    c_price = pool["prices"].get(st.session_state.coin, 0.0)
    if c_price == 0:
        st.toast("⚠️ 价格数据未就绪，请稍后重试", icon="⚠️")
        return

    max_bet = st.session_state.balance * MAX_POSITION_RATIO
    if st.session_state.bet_amt > max_bet:
        st.toast(f"🛡️ 超出风控上限（最大 {max_bet:.2f} U = 余额30%）", icon="🛡️")
        return

    if st.session_state.balance < st.session_state.bet_amt:
        st.toast("⚠️ 余额不足，无法开仓", icon="⚠️")
        return

    dur_map = {
        "5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60,
        "4小时": 240, "12小时": 720, "24小时": 1440
    }

    st.session_state.balance -= st.session_state.bet_amt
    open_time = datetime.utcnow() + timedelta(hours=8)
    settle_time = open_time + timedelta(minutes=dur_map[st.session_state.contract_dur])

    st.session_state.orders.append({
        "资产": st.session_state.coin,
        "方向": direction,
        "开仓价": c_price,
        "金额": st.session_state.bet_amt,
        "开仓时间": open_time,
        "结算time": settle_time,
        "状态": "待结算"
    })

    save_db_atomic(st.session_state.balance, st.session_state.orders)
    emoji = "🟩" if direction == "看涨" else "🟥"
    st.toast(f"{emoji} 已开仓 {st.session_state.coin} {direction} @ {c_price:.4f}", icon="✅")

# ==========================================
# 7. 业务分片：实时结算 + 倒计时卡片 (关键修复：依赖心跳)
# ==========================================
@st.fragment(run_every=1)
def operations_fragment():
    # 强制依赖心跳计数器，确保价格变动时 UI 刷新
    st.session_state.ui_heartbeat
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

    # 结算逻辑 (保持原样)
    db_dirty = False
    settled_log = []
    for o in st.session_state.orders:
        if o["状态"] != "待结算" or now < o["结算time"]:
            continue

        settle_price = pool["prices"].get(o["资产"], 0.0)
        if settle_price == 0.0:
            if now - o["结算time"] < timedelta(minutes=2):
                continue
            settle_price = o["开仓价"]

        win = (
            (o["方向"] == "看涨" and settle_price > o["开仓价"]) or
            (o["方向"] == "看跌" and settle_price < o["开仓价"])
        )
        payout = o["金额"] * 1.80 if win else 0.0

        st.session_state.balance += payout
        o["状态"] = "已结算"
        o["平仓价"] = settle_price
        o["结果"] = "WIN" if win else "LOSS"
        settled_log.append((o["资产"], o["方向"], win, o["金额"]))
        db_dirty = True

    if db_dirty:
        save_db_atomic(st.session_state.balance, st.session_state.orders)
        for asset, direction, win, amt in settled_log:
            if win:
                st.toast(f"🏆 {asset} {direction} 盈利 +{amt * 0.8:.2f} U", icon="🏆")
            else:
                st.toast(f"💔 {asset} {direction} 亏损 -{amt:.2f} U", icon="💔")

    # 持仓监控卡片 (保持原样)
    st.markdown("### 实时持仓监控")
    pending = [o for o in st.session_state.orders if o["状态"] == "待结算"]
    if not pending:
        st.caption("暂无活跃合约，请在下方极速面板下达指令。")
    else:
        for o in pending:
            rem = max(0, int((o["结算time"] - now).total_seconds()))
            h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
            track_price = pool["prices"].get(o["资产"], o["开仓价"])
            is_win = (
                (o["方向"] == "看涨" and track_price > o["开仓价"]) or
                (o["方向"] == "看跌" and track_price < o["开仓价"])
            )
            card_cls = "winning-bg" if is_win else "losing-bg"
            status_text = "WINNING" if is_win else "LOSING"
            status_color = theme["win"] if is_win else theme["loss"]
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
# 8. 侧边栏：管理员控制台 (保持原样)
# ==========================================
with st.sidebar:
    st.markdown("### 高级控制台")
    if st.checkbox("🔑 激活超级管理员重置"):
        pwd = st.text_input("授权码", type="password")
        if pwd and hashlib.sha256(pwd.encode()).hexdigest() == AUTH_HASH:
            if st.button("🔥 确认格式化账本", type="primary"):
                st.session_state.balance = 1000                st.success("数据已原子化抹除！")

# ==========================================
# 9. 主界面：交易面板 + 图表
# ==========================================
st.title("💰 Binance 合约交易终端 v2")

# 交易对与周期选择
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.session_state.coin = st.selectbox("选择交易对", SUPPORTED_COINS, index=1)
with col2:
    st.session_state.interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=0)
with col3:
    st.session_state.contract_dur = st.selectbox("合约时长", ["5分钟", "10分钟", "30分钟", "1小时", "4小时", "12小时", "24小时"], index=0)
with col4:
    st.session_state.bet_amt = st.number_input("下单金额 (USDT)", min_value=10.0, max_value=10000.0, value=100.0, step=10.0)

# 启动对应数据流
ensure_kline_stream(st.session_state.coin, st.session_state.interval)
ensure_ticker_streams_for_pending()

# 渲染图表
chart_fragment()

# 渲染业务面板
operations_fragment()

# 极速开仓按钮
st.markdown("---")
col_buy, col_sell = st.columns(2)
with col_buy:
    st.button("🟩 看涨 (做多)", type="primary", use_container_width=True, on_click=commit_order_callback, args=("看涨",))
with col_sell:
    st.button("🟥 看跌 (做空)", type="secondary", use_container_width=True, on_click=commit_order_callback, args=("看跌",))

# 历史订单
st.markdown("---")
st.markdown("### 历史订单记录")
if st.session_state.orders:
    df = pd.DataFrame(st.session_state.orders)
    df["开仓时间"] = df["开仓时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df["结算time"] = df["结算time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(df.sort_values("开仓时间", ascending=False), use_container_width=True)
else:
    st.caption("暂无历史订单记录。")
