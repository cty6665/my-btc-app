import hashlib
import hmac
import json
import threading
import time
import urllib.request
import uuid
from collections import deque
from datetime import datetime

import streamlit as st
import websocket  # pip install websocket-client
from streamlit_lightweight_charts import renderLightweightCharts

# ==========================================
# 1. 核心配置
# ==========================================
st.set_page_config(page_title="事件合约模拟终端", layout="wide", page_icon="📈")

DB_FILE = "trading_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e"
SUPPORTED_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVALS = ["1m", "5m", "15m", "1h"]
DURATION_MAP = {"5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60}
PAYOUT_RATE = 1.8           # 命中赔付倍数（含本金）；1.8x ⇒ 长期期望约 -10%
MAX_POSITION_RATIO = 0.30   # 单笔最大占余额比例（风控）
KLINE_MAXLEN = 300          # 图表保留的 K 线数量
AUTO_REFRESH_SEC = 1        # 界面自动刷新间隔（秒）
WS_BASE = "wss://stream.binance.com:9443"
# REST 备用域名：部分地区 api.binance.com 不可达时自动切换到 data-api.binance.vision
REST_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]

theme = {
    "bg": "#0b0e11", "text": "#eaecef", "card": "#181a20", "border": "#2b3139",
    "win": "#0ecb81", "loss": "#f6465d", "muted": "#848e9c", "brand": "#f0b90b",
}

st.markdown(f"""
<style>
.stApp {{ background-color: {theme['bg']}; color: {theme['text']}; }}
.metric-card {{ background: {theme['card']}; padding: 15px; border-radius: 8px;
                border: 1px solid {theme['border']}; margin-bottom: 10px; }}
.winning {{ border-left: 4px solid {theme['win']}; }}
.losing  {{ border-left: 4px solid {theme['loss']}; }}
.section-note {{ color: {theme['muted']}; font-size: 13px; }}
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. 行情数据层（全局共享、线程安全）
#    关键修复：不在 WebSocket 回调线程里碰 st.session_state，
#    行情写入进程级单例，UI 线程每次 rerun 时读取快照。
# ==========================================
def _http_get_json(url, timeout=8):
    """极简 HTTP GET（标准库实现，避免额外依赖）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "event-contract-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rest_klines(symbol, interval, limit=KLINE_MAXLEN):
    """REST 回填历史 K 线；多域名自动兜底，失败返回 None。"""
    for host in REST_HOSTS:
        try:
            raw = _http_get_json(
                f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            )
            return [
                {
                    "time": int(r[0]) // 1000,
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                }
                for r in raw
            ]
        except Exception:
            continue
    return None


def rest_price(symbol):
    """REST 最新价兜底（仅 WebSocket 无数据时用于结算）。"""
    for host in REST_HOSTS:
        try:
            data = _http_get_json(f"{host}/api/v3/ticker/price?symbol={symbol}", timeout=6)
            return float(data["price"])
        except Exception:
            continue
    return 0.0


class MarketDataManager:
    """进程级行情单例：一条合并流订阅全部币种，按币种分桶存储。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.prices = {c: 0.0 for c in SUPPORTED_COINS}
        self.klines = {c: deque(maxlen=KLINE_MAXLEN) for c in SUPPORTED_COINS}
        self.interval = None
        self.status = "init"          # init / connecting / online / reconnecting / error
        self.last_update = 0.0
        self.last_error = ""
        self._thread = None
        self._ws = None

    # ---------- 生命周期 ----------
    def ensure_running(self, interval):
        """每次脚本 rerun 调用：周期变化则回填+重连；线程死了则拉起。"""
        if interval != self.interval:
            with self._lock:
                self.interval = interval
                for dq in self.klines.values():
                    dq.clear()
            self._backfill_all()
            try:
                if self._ws is not None:
                    self._ws.close()  # 触发 _run_loop 用新周期重连
            except Exception:
                pass
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if not alive:
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()

    def _run_loop(self):
        """断线自动重连：Binance 连接 24h 强制断开，必须循环重连。"""
        while True:
            with self._lock:
                interval = self.interval
                self.status = "connecting"
            streams = "/".join(f"{c.lower()}@kline_{interval}" for c in SUPPORTED_COINS)
            url = f"{WS_BASE}/stream?streams={streams}"
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # ping_interval=0：不主动 ping；库会自动回复服务端 ping 帧
                self._ws.run_forever(ping_interval=0)
            except Exception as exc:
                with self._lock:
                    self.status = "error"
                    self.last_error = str(exc)
            with self._lock:
                if self.status != "error":
                    self.status = "reconnecting"
            time.sleep(5)  # 重连退避

    # ---------- WebSocket 回调（只写共享存储，绝不调用 st.*） ----------
    def _on_message(self, ws, message):
        try:
            msg = json.loads(message)
            data = msg.get("data", msg)          # 合并流外层包装 {"stream","data"}
            k = data.get("k")
            if not k:
                return
            symbol = k.get("s")
            if symbol not in self.klines:
                return
            bar = {
                "time": int(k["t"]) // 1000,
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
            }
            with self._lock:
                self.prices[symbol] = bar["close"]
                dq = self.klines[symbol]
                if dq and dq[-1]["time"] == bar["time"]:
                    dq[-1] = bar                      # 同一根 K 线：原地刷新
                elif not dq or bar["time"] > dq[-1]["time"]:
                    dq.append(bar)                    # 新 K 线：追加
                # 乱序帧直接丢弃，保证时间严格递增（图表库要求）
                self.status = "online"
                self.last_update = time.time()
        except Exception:
            pass  # 单条坏帧不应杀死行情线程

    def _on_error(self, ws, error):
        with self._lock:
            self.last_error = str(error)

    def _on_close(self, ws, *args):
        with self._lock:
            self.status = "reconnecting"

    # ---------- 数据回填 ----------
    def _backfill_all(self):
        with self._lock:
            interval = self.interval
        for symbol in SUPPORTED_COINS:
            bars = rest_klines(symbol, interval)
            if not bars:
                continue
            with self._lock:
                dq = self.klines[symbol]
                existing = {b["time"] for b in dq}
                for b in bars:
                    if b["time"] not in existing:
                        dq.append(b)
                merged = sorted(dq, key=lambda x: x["time"])  # 保证升序唯一
                dq.clear()
                dq.extend(merged[-KLINE_MAXLEN:])
                if self.prices.get(symbol, 0.0) <= 0:
                    self.prices[symbol] = merged[-1]["close"]

    # ---------- 读快照（UI 线程使用） ----------
    def get_price(self, symbol):
        with self._lock:
            return self.prices.get(symbol, 0.0)

    def get_klines(self, symbol):
        with self._lock:
            return list(self.klines.get(symbol, []))

    def get_status(self):
        with self._lock:
            return self.status, self.last_update, self.last_error


@st.cache_resource
def get_market_manager():
    """全应用唯一行情单例（跨 rerun / 跨会话共享，天然适合行情数据）。"""
    return MarketDataManager()


MANAGER = get_market_manager()


# ==========================================
# 3. 数据持久化（订单时间一律存 epoch 秒，JSON 安全）
#    注意：单文件 DB 意味着所有访问者共享同一账户。
#    仅适合单机单人演示；多人使用请换 SQLite/真实数据库并按用户隔离。
# ==========================================
def load_db():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        orders = [o for o in data.get("orders", []) if isinstance(o.get("open_ts"), (int, float))]
        return float(data.get("balance", 10000.0)), orders
    except Exception:
        return 10000.0, []


def save_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"balance": st.session_state.balance, "orders": st.session_state.orders},
                f, ensure_ascii=False,
            )
    except Exception as exc:
        st.toast(f"⚠️ 保存失败：{exc}", icon="⚠️")


# ==========================================
# 4. 会话状态初始化
# ==========================================
if "balance" not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
st.session_state.setdefault("coin", "BTCUSDT")
st.session_state.setdefault("interval", "1m")
st.session_state.setdefault("duration", "5分钟")
st.session_state.setdefault("bet_amt", 100.0)

# 启动 / 切换行情流（周期变化时自动回填历史 + 重连）
MANAGER.ensure_running(st.session_state.interval)


# ==========================================
# 5. 核心交易逻辑
# ==========================================
def commit_order(direction):
    price = MANAGER.get_price(st.session_state.coin)
    amt = float(st.session_state.bet_amt)

    if price <= 0:
        st.toast("⚠️ 行情未就绪，请稍后重试", icon="⚠️")
        return
    if amt > st.session_state.balance:
        st.toast("⚠️ 余额不足", icon="⚠️")
        return
    if amt > st.session_state.balance * MAX_POSITION_RATIO:
        st.toast(f"⚠️ 超过单笔风控上限（余额的 {MAX_POSITION_RATIO:.0%}）", icon="⚠️")
        return

    now = time.time()
    st.session_state.balance -= amt
    st.session_state.orders.append({
        "id": uuid.uuid4().hex[:8],
        "asset": st.session_state.coin,
        "direction": direction,                    # call=看涨 / put=看跌
        "amount": amt,
        "open_price": price,
        "open_ts": now,                            # epoch 秒（JSON 可序列化）
        "settle_ts": now + DURATION_MAP[st.session_state.duration] * 60,
        "status": "pending",
    })
    save_db()
    label = "看涨" if direction == "call" else "看跌"
    st.toast(f"✅ 已开仓 {label} {st.session_state.coin} {amt:.0f}U @ {price:.4f}", icon="✅")


def settle_due_orders():
    """在渲染前统一结算：全部币种实时价，REST 兜底，无价则留待下轮（不强制误判）。"""
    now = time.time()
    changed = False
    for o in st.session_state.orders:
        if o["status"] != "pending" or now < o["settle_ts"]:
            continue
        price = MANAGER.get_price(o["asset"])
        if price <= 0:
            price = rest_price(o["asset"])
        if price <= 0:
            continue  # 行情中断时不强制结算，避免冤判

        if price == o["open_price"]:
            payout, result = o["amount"], "tie"    # 平局退还本金
        elif ((o["direction"] == "call" and price > o["open_price"])
              or (o["direction"] == "put" and price < o["open_price"])):
            payout, result = o["amount"] * PAYOUT_RATE, "win"
        else:
            payout, result = 0.0, "loss"

        st.session_state.balance += payout
        o.update(status="closed", settle_price=price, result=result,
                 payout=payout, closed_ts=now)
        changed = True
        toast_map = {"win": "✅ 命中", "loss": "❌ 未中", "tie": "➖ 平局退款"}
        st.toast(f"{toast_map[result]}：{o['asset']} {o['amount']:.0f}U "
                 f"@ {o['open_price']:.4f} → {price:.4f}")
    if changed:
        save_db()


settle_due_orders()


# ==========================================
# 6. 界面渲染
# ==========================================
def fmt_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


st.title("📈 事件合约模拟交易终端")

status, last_update, last_error = MANAGER.get_status()
status_map = {
    "online": "🟢 行情已连接", "connecting": "🟡 连接中",
    "reconnecting": "🟠 重连中", "error": "🔴 连接错误", "init": "⚪ 初始化",
}
lag = int(time.time() - last_update) if last_update else "-"
st.caption(
    f"数据源：Binance WebSocket · {status_map.get(status, status)}"
    f" · 最后更新 {lag}s 前 · 本终端为虚拟资金模拟盘，非真实交易"
    + (f" · 最近错误：{last_error}" if last_error and status != "online" else "")
)

# ---- 账户面板 ----
cur_price = MANAGER.get_price(st.session_state.coin)
pending_orders = [o for o in st.session_state.orders if o["status"] == "pending"]
closed_orders = [o for o in st.session_state.orders if o["status"] == "closed"]
wins = len([o for o in closed_orders if o.get("result") == "win"])
win_rate = f"{wins / len(closed_orders) * 100:.1f}%" if closed_orders else "-"

col1, col2, col3, col4 = st.columns(4)
col1.metric("账户余额 (USDT)", f"{st.session_state.balance:,.2f}")
col2.metric(f"{st.session_state.coin} 最新价",
            f"{cur_price:,.4f}" if cur_price > 0 else "加载中…")
col3.metric("待结算订单", len(pending_orders))
col4.metric("历史胜率", win_rate)

# ---- 交易面板 ----
with st.container():
    st.subheader("极速交易")
    col1, col2, col3, col4 = st.columns([1.2, 1, 1, 1.4])
    col1.selectbox("交易对", SUPPORTED_COINS, key="coin")
    col2.selectbox("K线周期", INTERVALS, key="interval")
    col3.selectbox("合约时长", list(DURATION_MAP.keys()), key="duration")
    col4.number_input("下注金额 (USDT)", min_value=10.0, max_value=10000.0,
                      step=10.0, key="bet_amt")

    potential = st.session_state.bet_amt * PAYOUT_RATE
    st.markdown(
        f"<div class='section-note'>命中赔付 {PAYOUT_RATE}x（含本金）："
        f"潜在回款 <b style='color:{theme['brand']}'>{potential:,.2f}U</b>，"
        f"单笔上限为余额的 {MAX_POSITION_RATIO:.0%}</div>",
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    col1.button("🟢 看涨 CALL", on_click=commit_order, args=("call",),
                type="primary", use_container_width=True)
    col2.button("🔴 看跌 PUT", on_click=commit_order, args=("put",),
                type="secondary", use_container_width=True)

# ---- 图表区域 ----
with st.container():
    st.subheader(f"实时行情 · {st.session_state.coin} · {st.session_state.interval}")
    chart_data = MANAGER.get_klines(st.session_state.coin)

    price_lines = []
    for o in pending_orders:
        if o["asset"] == st.session_state.coin:
            color = theme["win"] if o["direction"] == "call" else theme["loss"]
            price_lines.append({
                "price": o["open_price"],
                "color": color,
                "lineWidth": 1,
                "lineStyle": 1,
                "axisLabelVisible": True,
                "title": f"{'CALL' if o['direction'] == 'call' else 'PUT'} {o['amount']:.0f}U",
            })

    chart_config = {
        "height": 480,
        "layout": {
            "background": {"type": "solid", "color": theme["bg"]},
            "textColor": theme["text"],
        },
        "grid": {
            "vertLines": {"color": theme["border"]},
            "horzLines": {"color": theme["border"]},
        },
        "crosshair": {"mode": 0},
        "timeScale": {"timeVisible": True, "secondsVisible": False, "rightOffset": 5},
    }

    if chart_data:
        renderLightweightCharts([{
            "chart": chart_config,
            "series": [{
                "type": "Candlestick",
                "data": chart_data,
                "options": {
                    "upColor": theme["win"], "downColor": theme["loss"],
                    "borderUpColor": theme["win"], "borderDownColor": theme["loss"],
                    "wickUpColor": theme["win"], "wickDownColor": theme["loss"],
                },
                "priceLines": price_lines,
            }],
        }], key="main_chart")
    else:
        st.info("行情数据加载中…（如长时间空白，请检查网络是否能访问 Binance）")

# ---- 持仓监控 ----
with st.container():
    st.subheader("持仓监控")
    if not pending_orders:
        st.markdown("<div class='section-note'>当前没有待结算订单</div>",
                    unsafe_allow_html=True)
    for o in pending_orders:
        now = time.time()
        remaining = o["settle_ts"] - now           # 修复：负数不再回绕成 24 小时
        p_now = MANAGER.get_price(o["asset"])
        in_profit = (
            (o["direction"] == "call" and p_now > o["open_price"])
            or (o["direction"] == "put" and p_now < o["open_price"])
        ) if p_now > 0 else False
        status_color = theme["win"] if in_profit else theme["loss"]
        dir_label = "🟢 看涨" if o["direction"] == "call" else "🔴 看跌"
        st.markdown(f"""
        <div class="metric-card {'winning' if in_profit else 'losing'}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><b>{dir_label}</b> · {o['asset']} · {o['amount']:.0f}U
                     <span style="color:{theme['muted']};font-size:12px;">#{o['id']}</span></div>
                <div style="color:{status_color};font-weight:bold;">⏳ {fmt_hms(remaining)}</div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:8px;">
                <div>开仓价：{o['open_price']:,.4f}</div>
                <div style="color:{status_color};">当前价：{p_now:,.4f}</div>
                <div>到期回款：{o['amount'] * PAYOUT_RATE:,.2f}U / 0U</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ---- 历史记录 ----
with st.container():
    st.subheader("结算记录")
    if closed_orders:
        result_map = {"win": "✅ 胜", "loss": "❌ 负", "tie": "➖ 平"}
        rows = []
        for o in sorted(closed_orders, key=lambda x: x.get("closed_ts", 0), reverse=True)[:15]:
            pnl = o.get("payout", 0.0) - o["amount"]
            rows.append({
                "结算时间": datetime.fromtimestamp(o.get("closed_ts", o["settle_ts"])).strftime("%m-%d %H:%M:%S"),
                "交易对": o["asset"],
                "方向": "看涨" if o["direction"] == "call" else "看跌",
                "金额U": round(o["amount"], 2),
                "开仓价": round(o["open_price"], 4),
                "结算价": round(o.get("settle_price", 0.0), 4),
                "结果": result_map.get(o.get("result"), "-"),
                "盈亏U": round(pnl, 2),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.markdown("<div class='section-note'>暂无已结算订单</div>", unsafe_allow_html=True)

# ---- 侧边栏 ----
with st.sidebar:
    st.markdown("### 📜 规则说明")
    st.markdown(f"""
    - 赔率：**{PAYOUT_RATE}x**（命中含本金回款，未中归零，平局退款）
    - 风控：单笔 ≤ 余额的 **{MAX_POSITION_RATIO:.0%}**
    - 方向：**看涨**=结算价高于开仓价获胜；**看跌**=低于获胜
    - ⚠️ 1.8x 赔率 ⇒ 长期期望约 **-10%**，仅为模拟演示
    """)

    st.markdown("### 🔌 系统状态")
    st.write(f"行情状态：{status_map.get(status, status)}")
    st.write(f"待结算 / 已结算：{len(pending_orders)} / {len(closed_orders)}")

    st.markdown("### 🔧 数据管理")
    if st.checkbox("重置模拟账户"):
        password = st.text_input("授权码", type="password")
        if password:
            ok = hmac.compare_digest(
                hashlib.sha256(password.encode()).hexdigest(), AUTH_HASH
            )
            if ok:
                if st.button("🔥 确认重置"):
                    st.session_state.balance = 10000.0
                    st.session_state.orders = []
                    save_db()
                    st.toast("✅ 已重置为初始状态", icon="✅")
                    time.sleep(0.5)
                    st.rerun()
            else:
                st.error("授权码错误")

    st.markdown("---")
    st.markdown("""
    <div class='section-note'>
    ⚠️ 本终端为<b>虚拟资金模拟盘</b>，行情来自 Binance 公开接口，仅用于学习演示。
    二元期权类产品在多个司法辖区被禁止向零售投资者提供，请勿用于真实资金。
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 7. 自动刷新（倒计时 / 实时价驱动）
#    WebSocket 线程持续更新全局行情；此处定时 rerun 让 UI 读最新快照。
# ==========================================
time.sleep(AUTO_REFRESH_SEC)
st.rerun()
