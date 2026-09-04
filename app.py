# -*- coding: utf-8 -*-
"""
事件合约（二元期权风格）模拟交易终端 —— V2 多数据源版
=================================================================
⚠️ 重要声明：
  1. 本程序仅为【模拟盘 / 教学演示】，所有资金均为虚拟，不接入任何真实交易。
  2. “二元期权 / 事件合约”在欧盟、英国等多地已被禁止向零售投资者提供，
     请勿将本代码用于任何真实资金场景。
  3. 赔率 1.8x 意味着长期期望为负（约 -10% 庄家优势），本程序不构成任何盈利策略。

V2 核心改进 —— 三源并行行情（解决单一数据源被地区封锁 / 卡顿 / 断连）：
  - 火币 HTX + 欧易 OKX + Gate.io 三家 WebSocket 同时连接，独立线程 + 心跳
    + 断线自动重连 + 停滞看门狗；任意一家可用行情即不中断。
  - 实时价格 = 三家新鲜报价的【中位数】，可抵御单源插针 / 异常报价。
  - K 线自动取“当前最优活跃源”，REST 历史回填按优先级多源兜底。
  - 数据层（第 2 节）完全不依赖 streamlit，可单独执行本文件自检连通性：
        python event_contract_pro_v2.py

运行方式：
    pip install streamlit websocket-client streamlit-lightweight-charts
    streamlit run event_contract_pro_v2.py
"""

import gzip
import hashlib
import hmac
import json
import statistics
import sys
import threading
import time
import urllib.request
import uuid
from collections import deque
from datetime import datetime

import websocket  # pip install websocket-client

# ==========================================
# 1. 核心配置
# ==========================================
DB_FILE = "trading_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e"  # 弱口令示例，请自行更换
SUPPORTED_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVALS = ["1m", "5m", "15m", "1h"]
DURATION_MAP = {"5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60}
PAYOUT_RATE = 1.8            # 命中赔付倍数（含本金）；1.8x ⇒ 长期期望约 -10%
MAX_POSITION_RATIO = 0.30    # 单笔最大占余额比例（风控）
KLINE_MAXLEN = 300           # 图表保留的 K 线数量
AUTO_REFRESH_SEC = 1         # 界面自动刷新间隔（秒）
PRICE_STALE_SEC = 30         # 某源报价超过该秒数视为失效，不参与中位数
STALE_KLINE_SEC = 120        # 某源 K 线超过该秒数无更新视为停滞，触发看门狗重连
BACKOFF_BASE = 5             # 重连退避基数（秒），指数增长，封顶 120

# 三源符号 / 周期映射（内部统一使用 BTCUSDT 与 1m/5m/15m/1h）
SYMBOL_MAP = {
    "htx": lambda s: s.lower(),                    # btcusdt
    "okx": lambda s: f"{s[:-4]}-{s[-4:]}",         # BTC-USDT
    "gate": lambda s: f"{s[:-4]}_{s[-4:]}",        # BTC_USDT
}
INTERVAL_MAP = {
    "htx": {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "60min"},
    "okx": {"1m": "candle1m", "5m": "candle5m", "15m": "candle15m", "1h": "candle1H"},
    "gate": {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"},
}
OKX_REST_BAR = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H"}
SOURCE_NAMES = {"htx": "火币 HTX", "okx": "欧易 OKX", "gate": "Gate.io"}

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (event-contract-demo/2.0)"}


# ==========================================
# 2. 行情数据层（多源并行，零 streamlit 依赖，可独立自测）
# ==========================================
def _http_get_json(url, timeout=8):
    """极简 HTTP GET（标准库实现，避免额外依赖）。"""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rest_klines(source, symbol, interval, limit=KLINE_MAXLEN):
    """按源回填历史 K 线，统一返回 [{'time','open','high','low','close'}]，失败返回 None。"""
    try:
        if source == "htx":
            d = _http_get_json(
                f"https://api.huobi.pro/market/history/kline"
                f"?symbol={SYMBOL_MAP['htx'](symbol)}&period={INTERVAL_MAP['htx'][interval]}&size={limit}"
            )
            data = d.get("data") or []
            bars = [{"time": int(r["id"]), "open": float(r["open"]), "high": float(r["high"]),
                     "low": float(r["low"]), "close": float(r["close"])} for r in data]
        elif source == "okx":
            d = _http_get_json(
                f"https://www.okx.com/api/v5/market/candles"
                f"?instId={SYMBOL_MAP['okx'](symbol)}&bar={OKX_REST_BAR[interval]}&limit={min(limit, 300)}"
            )
            if str(d.get("code")) != "0":
                return None
            bars = [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4])} for r in (d.get("data") or [])]
        elif source == "gate":
            d = _http_get_json(
                f"https://api.gateio.ws/api/v4/spot/candlesticks"
                f"?currency_pair={SYMBOL_MAP['gate'](symbol)}&interval={INTERVAL_MAP['gate'][interval]}&limit={limit}"
            )
            # Gate 返回 [t秒, 成交额, close, high, low, open, 成交量, 是否完结]
            bars = [{"time": int(r[0]), "open": float(r[5]), "high": float(r[3]),
                     "low": float(r[4]), "close": float(r[2])} for r in d]
        else:
            return None
        bars.sort(key=lambda x: x["time"])
        return bars
    except Exception:
        return None


def rest_price(source, symbol):
    """按源取最新成交价（结算兜底用），失败返回 0。"""
    try:
        if source == "htx":
            d = _http_get_json(
                f"https://api.huobi.pro/market/trade?symbol={SYMBOL_MAP['htx'](symbol)}", timeout=6)
            tick = (d.get("tick") or {})
            data = (tick.get("data") or [{}])[0]
            return float(data.get("price", 0))
        if source == "okx":
            d = _http_get_json(
                f"https://www.okx.com/api/v5/market/ticker?instId={SYMBOL_MAP['okx'](symbol)}", timeout=6)
            return float((d.get("data") or [{}])[0].get("last", 0))
        if source == "gate":
            d = _http_get_json(
                f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={SYMBOL_MAP['gate'](symbol)}",
                timeout=6)
            return float((d or [{}])[0].get("last", 0))
    except Exception:
        return 0.0
    return 0.0


class SourceWorker:
    """单个数据源的 WebSocket 工作线程：订阅全部币种 K 线，心跳保活，断线自动重连。"""

    def __init__(self, name, on_bar):
        self.name = name                  # htx / okx / gate
        self.on_bar = on_bar              # 回调: (source_name, symbol, bar_dict)
        self.interval = "1m"
        self.status = "init"              # init/connecting/online/reconnecting/error
        self.last_msg = 0.0               # 最近一条有效行情时间
        self.last_error = ""
        self._thread = None
        self._ws = None
        self._send_lock = threading.Lock()

    # ---------- 生命周期 ----------
    def ensure_running(self, interval):
        if interval != self.interval:
            self.interval = interval
            self._safe_close()            # 触发重连以应用新周期
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def mark_stale_and_restart(self):
        """看门狗调用：连接假死时主动断开，触发重连。"""
        self._safe_close()

    def _safe_close(self):
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass

    def _run_loop(self):
        fails = 0
        while True:
            self.status = "connecting"
            url = {"htx": "wss://api.huobi.pro/ws",
                   "okx": "wss://ws.okx.com:8443/ws/v5/public",
                   "gate": "wss://api.gateio.ws/ws/v4/"}[self.name]
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # ping_interval=0：禁用协议层 ping；三家各自的应用层心跳由本类处理
                self._ws.run_forever(ping_interval=0)
                fails = 0
            except Exception as exc:
                self.last_error = str(exc)[:200]
                fails += 1
            if self.status != "error":
                self.status = "reconnecting"
            time.sleep(min(BACKOFF_BASE * max(1, fails), 120))  # 指数退避，封顶 120 秒

    # ---------- 订阅与心跳 ----------
    def _on_open(self, ws):
        iv = INTERVAL_MAP[self.name][self.interval]
        if self.name == "htx":
            for i, c in enumerate(SUPPORTED_COINS):
                self._send({"sub": f"market.{SYMBOL_MAP['htx'](c)}.kline.{iv}", "id": f"sub{i}"})
            # HTX 无需主动心跳：应答服务端 ping 即可（见 _on_message）
        elif self.name == "okx":
            args = [{"channel": iv, "instId": SYMBOL_MAP["okx"](c)} for c in SUPPORTED_COINS]
            self._send({"op": "subscribe", "args": args})
            self._start_heartbeat(25, ws)  # OKX 要求 <30s 发送文本 "ping"
        elif self.name == "gate":
            for c in SUPPORTED_COINS:
                self._send({"time": int(time.time()), "channel": "spot.candlesticks",
                            "event": "subscribe", "payload": [iv, SYMBOL_MAP["gate"](c)]})
            self._start_heartbeat(20, ws)  # Gate 应用层 spot.ping
        self.status = "online"

    def _send(self, obj):
        try:
            with self._send_lock:
                if self._ws is not None:
                    self._ws.send(json.dumps(obj) if not isinstance(obj, str) else obj)
        except Exception:
            pass

    def _start_heartbeat(self, period, ws):
        """心跳线程绑定当前连接实例：重连后旧心跳自动退出，避免线程堆积。"""
        def beat():
            while self._ws is ws:
                time.sleep(period)
                if self._ws is not ws or self.status != "online":
                    continue
                if self.name == "okx":
                    self._send("ping")
                elif self.name == "gate":
                    self._send({"time": int(time.time()), "channel": "spot.ping"})
        threading.Thread(target=beat, daemon=True).start()

    # ---------- 消息解析（只回调数据，绝不调用 st.*） ----------
    def _on_message(self, ws, message):
        try:
            if self.name == "htx":
                if isinstance(message, (bytes, bytearray)):
                    message = gzip.decompress(message).decode("utf-8")
                d = json.loads(message)
                if "ping" in d:                       # 必须应答，否则被断开
                    self._send({"pong": d["ping"]})
                    return
                ch = d.get("ch", "")
                tick = d.get("tick")
                if not (ch.startswith("market.") and ".kline." in ch and tick):
                    return
                symbol = ch.split(".")[1].upper()
                bar = {"time": int(tick["id"]), "open": float(tick["open"]),
                       "high": float(tick["high"]), "low": float(tick["low"]),
                       "close": float(tick["close"])}
                self._emit(symbol, bar)

            elif self.name == "okx":
                if message == "pong":
                    return
                d = json.loads(message)
                data = d.get("data")
                if not (isinstance(d, dict) and data):
                    return
                inst = (d.get("arg") or {}).get("instId", "")
                symbol = inst.replace("-", "")
                for r in data:                        # [ts_ms, o, h, l, c, ...]
                    bar = {"time": int(r[0]) // 1000, "open": float(r[1]),
                           "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
                    self._emit(symbol, bar)

            elif self.name == "gate":
                d = json.loads(message)
                if not (d.get("channel") == "spot.candlesticks" and d.get("event") == "update"):
                    return
                result = d.get("result")
                if isinstance(result, dict):
                    result = [result]
                for r in (result or []):
                    name = r.get("n") or r.get("currency_pair") or ""   # 形如 1m_BTC_USDT
                    pair = r.get("currency_pair") or (name.split("_", 1)[1] if "_" in name else "")
                    symbol = pair.replace("_", "")
                    bar = {"time": int(r["t"]), "open": float(r["o"]),
                           "high": float(r["h"]), "low": float(r["l"]), "close": float(r["c"])}
                    self._emit(symbol, bar)
        except Exception:
            pass  # 单条坏帧不应杀死行情线程

    def _emit(self, symbol, bar):
        if symbol in SUPPORTED_COINS and bar["close"] > 0:
            self.last_msg = time.time()
            self.status = "online"
            self.on_bar(self.name, symbol, bar)

    def _on_error(self, ws, error):
        self.last_error = str(error)[:200]

    def _on_close(self, ws, *args):
        if self.status != "error":
            self.status = "reconnecting"

    def snapshot(self):
        return {"status": self.status, "last_msg": self.last_msg, "last_error": self.last_error}


class MarketDataHub:
    """三源并行行情中枢：价格取中位数，K 线取最优活跃源，REST 回填多源兜底。"""

    SOURCES = ["htx", "okx", "gate"]

    def __init__(self):
        self._lock = threading.Lock()
        self.quotes = {s: {} for s in self.SOURCES}          # source -> {symbol: (price, ts)}
        self.klines = {c: deque(maxlen=KLINE_MAXLEN) for c in SUPPORTED_COINS}
        self.kline_src = {c: None for c in SUPPORTED_COINS}  # 当前图表数据源
        self.interval = None
        self.workers = {s: SourceWorker(s, self._on_bar) for s in self.SOURCES}
        self._watchdog_started = False

    # ---------- 生命周期 ----------
    def ensure_running(self, interval):
        if interval != self.interval:
            with self._lock:
                self.interval = interval
                for dq in self.klines.values():
                    dq.clear()
                self.kline_src = {c: None for c in SUPPORTED_COINS}
            self._backfill_all()
            for w in self.workers.values():
                w.interval = interval
        for w in self.workers.values():
            w.ensure_running(interval)
        if not self._watchdog_started:
            self._watchdog_started = True
            threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """每 15 秒巡检：某源在线但 K 线停滞 → 主动重启该源连接。"""
        while True:
            time.sleep(15)
            for w in self.workers.values():
                if w.status == "online" and w.last_msg and time.time() - w.last_msg > STALE_KLINE_SEC:
                    w.mark_stale_and_restart()

    # ---------- 数据写入 ----------
    def _on_bar(self, source, symbol, bar):
        with self._lock:
            self.quotes[source][symbol] = (bar["close"], time.time())
            if self.kline_src[symbol] is None:
                self.kline_src[symbol] = source          # 先到先得；源管理见 _pick_locked
            if source == self.kline_src[symbol]:
                dq = self.klines[symbol]
                if dq and dq[-1]["time"] == bar["time"]:
                    dq[-1] = bar                          # 同根 K 线：原地刷新
                elif not dq or bar["time"] > dq[-1]["time"]:
                    dq.append(bar)                        # 新 K 线：追加（乱序帧丢弃）

    def _pick_locked(self, symbol):
        """在锁内挑选 K 线源：现任源新鲜则保留，否则切换到最新有数据的源。"""
        now = time.time()
        cur = self.kline_src.get(symbol)
        if cur and self.quotes.get(cur, {}).get(symbol):
            if now - self.quotes[cur][symbol][1] <= STALE_KLINE_SEC:
                return cur
        best, best_ts = None, 0.0
        for s in self.SOURCES:
            q = self.quotes.get(s, {}).get(symbol)
            if q and q[1] > best_ts:
                best, best_ts = s, q[1]
        if best and now - best_ts <= STALE_KLINE_SEC:
            self.kline_src[symbol] = best
            return best
        return cur

    # ---------- REST 回填 ----------
    def _backfill_all(self):
        with self._lock:
            interval = self.interval
        priority = self._rest_priority()
        for symbol in SUPPORTED_COINS:
            bars = None
            used = None
            for src in priority:
                bars = rest_klines(src, symbol, interval)
                if bars:
                    used = src
                    break
            if not bars:
                continue
            with self._lock:
                dq = self.klines[symbol]
                existing = {b["time"] for b in dq}
                for b in bars:
                    if b["time"] not in existing:
                        dq.append(b)
                merged = sorted(dq, key=lambda x: x["time"])  # 升序唯一（图表库要求）
                dq.clear()
                dq.extend(merged[-KLINE_MAXLEN:])
                self.kline_src[symbol] = used
                for src in priority:                      # 无报价源先用回填收盘价顶着
                    self.quotes.setdefault(src, {}).setdefault(symbol, (merged[-1]["close"], time.time()))

    def _rest_priority(self):
        """REST 兜底优先级：近期有消息的源排前面。"""
        def key(s):
            return -self.workers[s].last_msg
        return sorted(self.SOURCES, key=key)

    # ---------- 读快照（UI 线程使用） ----------
    def get_price(self, symbol):
        """三源新鲜报价的中位数（抵御单源插针）；无新鲜报价返回 0。"""
        now = time.time()
        vals = []
        with self._lock:
            for s in self.SOURCES:
                q = self.quotes.get(s, {}).get(symbol)
                if q and now - q[1] <= PRICE_STALE_SEC and q[0] > 0:
                    vals.append(q[0])
        if not vals:
            return 0.0
        return float(statistics.median(vals))

    def get_quote_detail(self, symbol):
        now = time.time()
        detail = {}
        with self._lock:
            for s in self.SOURCES:
                q = self.quotes.get(s, {}).get(symbol)
                if q:
                    detail[s] = (q[0], int(now - q[1]))
        return detail

    def get_klines(self, symbol):
        with self._lock:
            self._pick_locked(symbol)
            return list(self.klines.get(symbol, [])), self.kline_src.get(symbol)

    def get_status(self):
        out = {}
        for s, w in self.workers.items():
            snap = w.snapshot()
            snap["lag"] = int(time.time() - snap["last_msg"]) if snap["last_msg"] else None
            out[s] = snap
        return out

    def health(self):
        """online 且数据新鲜的源数量。"""
        n = 0
        for s, w in self.workers.items():
            if w.status == "online" and w.last_msg and time.time() - w.last_msg <= STALE_KLINE_SEC:
                n += 1
        return n


HUB = MarketDataHub()          # 模块级单例（streamlit 模式下由 cache_resource 持有）


def hub_selftest(seconds=15):
    """脱离 streamlit 的连通性自检：python event_contract_pro_v2.py"""
    print(f"[自检] 启动三源连接，观察 {seconds} 秒 …")
    HUB.ensure_running("1m")
    t0 = time.time()
    while time.time() - t0 < seconds:
        time.sleep(2)
    print("[自检] 各源状态：")
    for s, snap in HUB.get_status().items():
        lag = f"{snap['lag']}s 前" if snap["lag"] is not None else "无数据"
        print(f"  - {SOURCE_NAMES[s]:<10} 状态={snap['status']:<12} 最近消息={lag}  错误={snap['last_error'] or '-'}")
    for c in SUPPORTED_COINS:
        print(f"[自检] {c} 中位价 = {HUB.get_price(c):,.4f}  明细={ {SOURCE_NAMES[k]: v for k, v in HUB.get_quote_detail(c).items()} }")
    kl, src = HUB.get_klines("BTCUSDT")
    print(f"[自检] BTCUSDT K线 {len(kl)} 根，图表源={SOURCE_NAMES.get(src, '-')}")


if __name__ == "__main__" and "streamlit" not in sys.modules:
    # 直接 `python event_contract_pro_v2.py` = 数据源自检模式（无需安装 streamlit）
    # `streamlit run` 启动时 streamlit 已在 sys.modules 中，不会误入此分支
    hub_selftest()
    sys.exit(0)


# ==========================================
# 3. Streamlit 应用层（界面与用户喜爱的 V1 保持一致）
# ==========================================
import streamlit as st
from streamlit_lightweight_charts import renderLightweightCharts

st.set_page_config(page_title="事件合约模拟终端", layout="wide", page_icon="📈")

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


@st.cache_resource
def get_hub():
    """全应用唯一行情中枢（跨 rerun / 跨会话共享）。"""
    return HUB


MANAGER = get_hub()


# ---- 数据持久化（订单时间一律存 epoch 秒，JSON 安全） ----
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
            json.dump({"balance": st.session_state.balance, "orders": st.session_state.orders},
                      f, ensure_ascii=False)
    except Exception as exc:
        st.toast(f"⚠️ 保存失败：{exc}", icon="⚠️")


# ---- 会话状态初始化 ----
if "balance" not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
st.session_state.setdefault("coin", "BTCUSDT")
st.session_state.setdefault("interval", "1m")
st.session_state.setdefault("duration", "5分钟")
st.session_state.setdefault("bet_amt", 100.0)

MANAGER.ensure_running(st.session_state.interval)


# ---- 核心交易逻辑 ----
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
        "direction": direction,
        "amount": amt,
        "open_price": price,
        "open_ts": now,
        "settle_ts": now + DURATION_MAP[st.session_state.duration] * 60,
        "status": "pending",
    })
    save_db()
    label = "看涨" if direction == "call" else "看跌"
    st.toast(f"✅ 已开仓 {label} {st.session_state.coin} {amt:.0f}U @ {price:,.4f}", icon="✅")


def settle_price_for(symbol):
    """结算价：三源中位价 → REST 多源兜底 → 0（无价不结算）。"""
    p = MANAGER.get_price(symbol)
    if p > 0:
        return p
    for src in MANAGER._rest_priority():
        p = rest_price(src, symbol)
        if p > 0:
            return p
    return 0.0


def settle_due_orders():
    now = time.time()
    changed = False
    for o in st.session_state.orders:
        if o["status"] != "pending" or now < o["settle_ts"]:
            continue
        price = settle_price_for(o["asset"])
        if price <= 0:
            continue  # 三源全断时不强制结算，避免冤判
        if price == o["open_price"]:
            payout, result = o["amount"], "tie"
        elif ((o["direction"] == "call" and price > o["open_price"])
              or (o["direction"] == "put" and price < o["open_price"])):
            payout, result = o["amount"] * PAYOUT_RATE, "win"
        else:
            payout, result = 0.0, "loss"
        st.session_state.balance += payout
        o.update(status="closed", settle_price=price, result=result, payout=payout, closed_ts=now)
        changed = True
        toast_map = {"win": "✅ 命中", "loss": "❌ 未中", "tie": "➖ 平局退款"}
        st.toast(f"{toast_map[result]}：{o['asset']} {o['amount']:.0f}U "
                 f"@ {o['open_price']:,.4f} → {price:,.4f}")
    if changed:
        save_db()


settle_due_orders()


# ---- 界面渲染 ----
def fmt_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


st.title("📈 事件合约模拟交易终端")

sources_status = MANAGER.get_status()
healthy = MANAGER.health()
health_icon = "🟢" if healthy >= 2 else ("🟡" if healthy == 1 else "🔴")
st.caption(
    f"数据源：火币 HTX + 欧易 OKX + Gate.io 三源并行 · 可用源 {health_icon} {healthy}/3"
    f" · 实时价=三源中位数 · 本终端为虚拟资金模拟盘，非真实交易"
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
    chart_data, chart_src = MANAGER.get_klines(st.session_state.coin)
    src_label = SOURCE_NAMES.get(chart_src, "-")
    st.subheader(f"实时行情 · {st.session_state.coin} · {st.session_state.interval}"
                 f"（K线源：{src_label}）")

    price_lines = []
    for o in pending_orders:
        if o["asset"] == st.session_state.coin:
            color = theme["win"] if o["direction"] == "call" else theme["loss"]
            price_lines.append({
                "price": o["open_price"], "color": color, "lineWidth": 1, "lineStyle": 1,
                "axisLabelVisible": True,
                "title": f"{'CALL' if o['direction'] == 'call' else 'PUT'} {o['amount']:.0f}U",
            })

    chart_config = {
        "height": 480,
        "layout": {"background": {"type": "solid", "color": theme["bg"]},
                   "textColor": theme["text"]},
        "grid": {"vertLines": {"color": theme["border"]},
                 "horzLines": {"color": theme["border"]}},
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
        st.info("行情数据加载中…（三家数据源正在连接，若长时间空白请检查网络）")

# ---- 持仓监控 ----
with st.container():
    st.subheader("持仓监控")
    if not pending_orders:
        st.markdown("<div class='section-note'>当前没有待结算订单</div>",
                    unsafe_allow_html=True)
    for o in pending_orders:
        now = time.time()
        remaining = o["settle_ts"] - now
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
    - 价格口径：三家交易所实时价**中位数**，抗单源插针
    - ⚠️ 1.8x 赔率 ⇒ 长期期望约 **-10%**，仅为模拟演示
    """)

    st.markdown("### 🔌 数据源状态")
    status_icon = {"online": "🟢", "connecting": "🟡", "reconnecting": "🟠",
                   "error": "🔴", "init": "⚪"}
    for s, snap in sources_status.items():
        lag = f"{snap['lag']}s前" if snap["lag"] is not None else "无数据"
        line = f"{status_icon.get(snap['status'], '⚪')} {SOURCE_NAMES[s]}：{snap['status']} · {lag}"
        if snap["last_error"] and snap["status"] != "online":
            line += f" · {snap['last_error'][:60]}"
        st.write(line)
    quote_detail = MANAGER.get_quote_detail(st.session_state.coin)
    if quote_detail:
        st.caption(f"{st.session_state.coin} 各源报价："
                   + " / ".join(f"{SOURCE_NAMES[k]} {v[0]:,.2f}({v[1]}s)"
                                for k, v in quote_detail.items()))

    st.markdown("### 🔧 数据管理")
    if st.checkbox("重置模拟账户"):
        password = st.text_input("授权码", type="password")
        if password:
            ok = hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), AUTH_HASH)
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
    ⚠️ 本终端为<b>虚拟资金模拟盘</b>，行情来自 HTX / OKX / Gate.io 公开接口，仅用于学习演示。
    二元期权类产品在多个司法辖区被禁止向零售投资者提供，请勿用于真实资金。
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 7. 自动刷新（倒计时 / 实时价驱动）
# ==========================================
time.sleep(AUTO_REFRESH_SEC)
st.rerun()
