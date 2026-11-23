# -*- coding: utf-8 -*-
"""
事件合约（二元期权风格）模拟交易终端 —— 云端原生版（plotly 同源渲染）
=================================================================
⚠️ 重要声明：
  1. 本程序仅为【模拟盘 / 教学演示】，所有资金均为虚拟，不接入任何真实交易。
  2. “二元期权 / 事件合约”在欧盟、英国等多地已被禁止向零售投资者提供，
     请勿将本代码用于任何真实资金场景。
  3. 赔率 1.8x 意味着长期期望为负（约 -10% 庄家优势），本程序不构成任何盈利策略。

云端架构（Streamlit Community Cloud / 本地 streamlit run 行为一致）：
  - 图表用 Streamlit 原生 st.plotly_chart，数据在进程内同源渲染，不依赖
    127.0.0.1 本地端口或 iframe，因此可直接部署到云端。
  - 图表本体在 @st.fragment(run_every=1s) 内每秒自动重绘；通过 uirevision
    在刷新间保持用户的缩放/平移状态，切换币种/周期时复位。
  - 开仓价线：看涨 CALL = 红色虚线，看跌 PUT = 绿色虚线，开仓后固定不动。
  - 技术指标自由叠加：MA / EMA / 布林带 BOLL（主图）+ RSI / KDJ / MACD（副图）。
  - 币安 + 火币 HTX + 欧易 OKX + Gate.io 四源并行，价格取中位数，断线自动重连。
  - 数据层（第 2 节）零 streamlit 依赖，可单独自检：python app.py

运行方式：
    pip install -r requirements.txt
    streamlit run app.py
"""

import gzip
import http.client
import json
import statistics
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
from collections import deque
from datetime import datetime

import pandas as pd
import websocket  # pip install websocket-client

# WebSocketApp.run_forever 在本版本(1.9.2)不支持 connect_timeout 参数，
# 连接阶段(TCP/SSL 握手)的 socket 超时由全局 default timeout 决定，默认 None=永久阻塞。
# 这里设为 10 秒：网络静默丢包时连接快速失败进入重连，而不是线程永久卡死。
websocket.setdefaulttimeout(10)

# ==========================================
# 1. 核心配置
# ==========================================
DB_FILE = "trading_db.json"
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
BACKFILL_RETRY_SEC = 30      # 历史 K 线未满时，自动重新回填的最小间隔（秒）

# 开仓价线样式（币安风格）：看涨红虚线 / 看跌绿虚线
CALL_LINE_COLOR = "#f6465d"
PUT_LINE_COLOR = "#0ecb81"
LINE_STYLE_DASHED = 2        # lightweight-charts: 0实线 1点线 2虚线

INDICATOR_OPTIONS = ["MA", "EMA", "BOLL", "MACD", "RSI", "KDJ"]

# 多源符号 / 周期映射（内部统一使用 BTCUSDT 与 1m/5m/15m/1h）
SYMBOL_MAP = {
    "binance": lambda s: s.upper(),                # BTCUSDT（原样）
    "gate": lambda s: f"{s[:-4]}_{s[-4:]}",        # BTC_USDT
    "htx": lambda s: s.lower(),                    # btcusdt
    "okx": lambda s: f"{s[:-4]}-{s[-4:]}",         # BTC-USDT
}
INTERVAL_MAP = {
    "binance": {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"},
    "gate": {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h"},
    "htx": {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "60min"},
    "okx": {"1m": "candle1m", "5m": "candle5m", "15m": "candle15m", "1h": "candle1H"},
}
OKX_REST_BAR = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H"}
SOURCE_NAMES = {"binance": "币安 Binance", "gate": "Gate.io", "htx": "火币 HTX", "okx": "欧易 OKX"}

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (event-contract-demo/3.0)"}

# 副图窗格基础配置（数据层内置一份，避免依赖 UI 主题变量）
SUB_CHART_CONFIG = {
    "layout": {"background": {"type": "solid", "color": "#0b0e11"}, "textColor": "#eaecef"},
    "grid": {"vertLines": {"color": "#2b3139"}, "horzLines": {"color": "#2b3139"}},
    "crosshair": {"mode": 0},
    "timeScale": {"timeVisible": True, "secondsVisible": False, "rightOffset": 5},
}


# ==========================================
# 2. 行情数据层（多源并行，零 streamlit 依赖，可独立自测）
# ==========================================
def _http_get_json(url, timeout=8, retries=4):
    """极简 HTTP GET（标准库实现，避免额外依赖）。

    不稳定网络下，较大的 chunked 响应容易在读取中途被对端关闭，标准库会抛
    http.client.IncompleteRead（小响应正常、大响应随机失败）。这里：
      1) IncompleteRead 时先用已收到的 partial 尝试解析；
      2) 解析不了或连接类错误，则有限次重试并线性退避，全部失败才抛出。
    """
    last_exc = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except http.client.IncompleteRead as exc:
            last_exc = exc
            try:                                # 已收到的部分若恰好是完整 JSON 直接用
                return json.loads(exc.partial.decode("utf-8"))
            except Exception:
                pass
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, OSError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))
    raise last_exc


def _extract_complete_elements(text, data_key=None):
    """从可能被截断的 JSON 文本里提取所有【完整】的内层数组元素。

    差网络下大响应常在传输中途被对端关闭（IncompleteRead），末尾一条记录不完整，
    但前面的记录通常已完整到达。跳过外层数组括号，逐字符扫描内层元素、尊重
    字符串内括号，只返回能成功 json.loads 的完整元素，从而把“整段失败”降级为
    “只丢最后一两条”。

    data_key=None：整个响应就是数组（binance/gate）；
    data_key="data"：先定位对象内 "data":[ 数组起点（htx/okx）。
    """
    body = text
    if data_key:
        idx = body.find(f'"{data_key}":[')
        if idx < 0:
            return []
        body = body[idx + len(f'"{data_key}":'):]
    open_idx = body.find('[')                  # 外层数组的左括号
    if open_idx < 0:
        return []

    elements = []
    i, n = open_idx + 1, len(body)             # 从外层 [ 之后开始扫描内层元素
    while i < n:
        ch = body[i]
        if ch not in '[':
            i += 1
            continue
        depth, in_str, esc, j, complete = 1, False, False, i + 1, False
        while j < n:
            c = body[j]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        complete = True
                        break
            j += 1
        if complete:
            try:
                elements.append(json.loads(body[i:j + 1]))
            except Exception:
                pass
            i = j + 1
        else:
            break                              # 末尾截断元素，其后不可能再有完整记录
    return elements


def _http_get_text(url, timeout=8, retries=4):
    """GET 并返回 (text, truncated)。

    连接类错误有限重试；全部失败时，若最后一次收到过部分数据（IncompleteRead），
    则把 partial 文本连同 truncated=True 返回，交给容错提取，而不是整段判失败。
    完全没有数据才抛出最后一个异常。
    """
    last_exc, partial_text = None, None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8"), False
        except http.client.IncompleteRead as exc:
            last_exc = exc
            try:
                partial_text = exc.partial.decode("utf-8")
            except Exception:
                partial_text = None
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, OSError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))
    if partial_text:
        return partial_text, True
    raise last_exc


def rest_klines(source, symbol, interval, limit=KLINE_MAXLEN):
    """按源回填历史 K 线，统一返回 [{'time','open','high','low','close'}]，失败返回 None。"""
    try:
        data_key = None
        if source == "binance":
            # data-api.binance.vision 与 api2 间歇 RemoteDisconnected，主域名 api.binance.com 实测稳定
            url = (f"https://api.binance.com/api/v3/klines"
                   f"?symbol={SYMBOL_MAP['binance'](symbol)}&interval={INTERVAL_MAP['binance'][interval]}"
                   f"&limit={min(limit, 1000)}")
        elif source == "htx":
            url = (f"https://api.huobi.pro/market/history/kline"
                   f"?symbol={SYMBOL_MAP['htx'](symbol)}&period={INTERVAL_MAP['htx'][interval]}&size={limit}")
            data_key = "data"
        elif source == "okx":
            url = (f"https://www.okx.com/api/v5/market/candles"
                   f"?instId={SYMBOL_MAP['okx'](symbol)}&bar={OKX_REST_BAR[interval]}&limit={min(limit, 300)}")
            data_key = "data"
        elif source == "gate":
            url = (f"https://api.gateio.ws/api/v4/spot/candlesticks"
                   f"?currency_pair={SYMBOL_MAP['gate'](symbol)}&interval={INTERVAL_MAP['gate'][interval]}&limit={limit}")
        else:
            return None

        text, truncated = _http_get_text(url)
        if truncated:
            # 大响应传输中途被断开：提取已完整到达的记录，只丢最后一两条
            records = _extract_complete_elements(text, data_key)
        elif data_key:
            obj = json.loads(text)
            if source == "okx" and str(obj.get("code")) != "0":
                return None
            records = obj.get("data") or []
        else:
            records = json.loads(text)

        if source == "binance":
            # 币安记录 [时间戳ms, 开, 高, 低, 收, 成交量, ...]
            bars = [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4])} for r in records]
        elif source == "gate":
            # Gate 记录 [t秒, 成交额, close, high, low, open, 成交量, 是否完结]
            bars = [{"time": int(r[0]), "open": float(r[5]), "high": float(r[3]),
                     "low": float(r[4]), "close": float(r[2])} for r in records]
        elif source == "htx":
            # 火币记录为对象 {id, open, high, low, close}
            bars = [{"time": int(r["id"]), "open": float(r["open"]), "high": float(r["high"]),
                     "low": float(r["low"]), "close": float(r["close"])} for r in records]
        else:  # okx 记录 [时间戳ms, 开, 高, 低, 收, ...]
            bars = [{"time": int(r[0]) // 1000, "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4])} for r in records]

        bars.sort(key=lambda x: x["time"])
        return bars
    except Exception:
        return None


def rest_price(source, symbol):
    """按源取最新成交价（结算兜底用），失败返回 0。"""
    try:
        if source == "binance":
            d = _http_get_json(
                f"https://data-api.binance.vision/api/v3/ticker/price?symbol={SYMBOL_MAP['binance'](symbol)}",
                timeout=6)
            return float(d.get("price", 0))
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
        self.open_ts = 0.0                # 最近一次连接建立（on_open）时间
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
            url = {"binance": "wss://data-stream.binance.vision/ws",
                   "gate": "wss://api.gateio.ws/ws/v4/",
                   "htx": "wss://api.huobi.pro/ws",
                   # OKX K线频道已迁移至 /business，且 8443 端口退役，统一走 443
                   "okx": "wss://ws.okx.com/ws/v5/business"}[self.name]
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # ping_interval=0：禁用协议层 ping；各源的应用层心跳由本类处理
                # 连接超时由模块级 websocket.setdefaulttimeout(10) 统一控制，
                # 网络静默丢包时 10 秒内握手失败、进入下方重连退避，线程不会永久卡死。
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
        self.open_ts = time.time()
        iv = INTERVAL_MAP[self.name][self.interval]
        if self.name == "binance":
            # 币安WebSocket订阅K线
            streams = [f"{SYMBOL_MAP['binance'](c).lower()}@kline_{iv}" for c in SUPPORTED_COINS]
            self._send({"method": "SUBSCRIBE", "params": streams, "id": 1})
        elif self.name == "htx":
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
            if self.name == "binance":
                d = json.loads(message)
                # 订阅应答消息跳过
                if "result" in d or "id" in d:
                    return
                # 两种消息包装都要兼容：
                #   /stream 组合流：{"stream":"btcusdt@kline_1m","data":{"k":...}}
                #   /ws 动态订阅：原始事件 {"e":"kline","s":"BTCUSDT","k":...}（无 stream/data 包装）
                payload = d.get("data") or d
                kline = payload.get("k")
                if not kline:
                    return
                stream = d.get("stream", "")
                if stream:
                    # 从 stream 名解析交易对：btcusdt@kline_1m
                    symbol = stream.split("@")[0].upper()
                else:
                    symbol = kline.get("s", "").upper()
                if symbol not in SUPPORTED_COINS:
                    return
                bar = {"time": int(kline["t"]) // 1000, "open": float(kline["o"]),
                       "high": float(kline["h"]), "low": float(kline["l"]),
                       "close": float(kline["c"])}
                self._emit(symbol, bar)
            elif self.name == "htx":
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
    """四源并行行情中枢：价格取中位数，K 线取最优活跃源，REST 回填多源兜底。"""

    SOURCES = ["binance", "gate", "htx", "okx"]

    def __init__(self):
        self._lock = threading.Lock()
        self.quotes = {s: {} for s in self.SOURCES}          # source -> {symbol: (price, ts)}
        self.klines = {c: deque(maxlen=KLINE_MAXLEN) for c in SUPPORTED_COINS}
        self.kline_src = {c: None for c in SUPPORTED_COINS}  # 当前图表数据源
        self.interval = None
        self.workers = {s: SourceWorker(s, self._on_bar) for s in self.SOURCES}
        self._watchdog_started = False
        self._backfilling = False         # 最新代际回填线程是否在运行
        self._backfill_thread = None     # 回填线程对象（诊断/存活检查）
        self._backfill_gen = 0           # 回填代际：每次切换周期 +1，过期线程静默退出
        self._last_backfill_try = 0.0   # 最近一次发起回填的时间，用于限流自动重试

    # ---------- 生命周期 ----------
    def ensure_running(self, interval):
        if interval != self.interval:
            with self._lock:
                self.interval = interval
                for dq in self.klines.values():
                    dq.clear()
                self.kline_src = {c: None for c in SUPPORTED_COINS}
            # 新周期强制启动新一代回填；旧代际线程检测到 gen 变化会自行退出，
            # 不会再把旧周期 REST 数据写回（否则会出现切到 5m 却填入 1m K线）。
            self._start_backfill(force=True)
        # 由 worker 自己检测 interval 变化并 close 重连，
        # 切勿在此提前赋值 w.interval（会跳过 worker 的重连，旧周期数据将污染新周期）。
        for w in self.workers.values():
            w.ensure_running(interval)
        if not self._watchdog_started:
            self._watchdog_started = True
            threading.Thread(target=self._watchdog, daemon=True).start()

    def _start_backfill(self, force=False):
        """启动后台回填线程。

        force=True（切换周期）：递增代际并启动新线程，旧线程在检查点自行退出；
        force=False（同周期首次启动）：已有回填在跑则跳过，避免重复。
        """
        if force:
            self._backfill_gen += 1
        elif self._backfilling:
            return
        else:
            self._backfill_gen += 1
        gen = self._backfill_gen
        self._backfilling = True
        self._last_backfill_try = time.time()

        def _run():
            try:
                self._backfill_all(gen)
            finally:
                # 只有最新代际线程才能复位标志，旧线程退出不影响新线程状态
                if gen == self._backfill_gen:
                    self._backfilling = False

        self._backfill_thread = threading.Thread(target=_run, daemon=True)
        self._backfill_thread.start()

    def _watchdog(self):
        """每 15 秒巡检：连接在线但 K 线停滞（含从未收到数据）→ 主动重启该源连接。"""
        while True:
            time.sleep(15)
            # 整体容错：单次巡检中任何异常（含回填启动失败）都不得杀死本线程，
            # 否则看门狗一旦静默退出，所有“连上但不收数据”的僵死连接将永远无法被重启。
            try:
                for w in self.workers.values():
                    if w.status != "online":
                        continue
                    # 基准时间：收到过行情用 last_msg；从未收到则用连接建立时间
                    base_ts = w.last_msg or w.open_ts
                    if base_ts and time.time() - base_ts > STALE_KLINE_SEC:
                        w.mark_stale_and_restart()
                # 回填自愈：任一币种历史未满且当前无回填、距上次尝试超过 30 秒，则重新回填。
                # 回填写入按时间戳去重，重复执行只补缺失、不产生重复；填满 KLINE_MAXLEN 后自然停止。
                if (not self._backfilling
                        and time.time() - self._last_backfill_try > BACKFILL_RETRY_SEC
                        and any(len(self.klines[c]) < KLINE_MAXLEN for c in SUPPORTED_COINS)):
                    self._start_backfill(force=True)
            except Exception:
                pass

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
    def _backfill_all(self, gen):
        with self._lock:
            interval = self.interval
        priority = self._rest_priority()
        for symbol in SUPPORTED_COINS:
            if gen != self._backfill_gen:        # 已被新周期取代：静默退出，不写入
                return
            bars = None
            used = None
            for src in priority:
                if gen != self._backfill_gen:
                    return
                bars = rest_klines(src, symbol, interval)
                if bars:
                    used = src
                    break
            if not bars:
                continue
            if gen != self._backfill_gen:        # 写入前最后确认，过期数据绝不落盘
                return
            with self._lock:
                if gen != self._backfill_gen:    # 拿到锁后再复检：消除“检查后、获锁前被切换”的竞态
                    return
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


# ==========================================
# 2.5 技术指标计算（纯 pandas，零 streamlit 依赖）
# ==========================================
def _line_series(times, values, color, title, width=1):
    """把一组与 K 线时间对齐的数值包装成 Line 系列（自动跳过 NaN）。"""
    data = [{"time": int(t), "value": round(float(v), 4)}
            for t, v in zip(times, values)
            if v is not None and not pd.isna(v)]
    return {"type": "Line", "data": data,
            "options": {"color": color, "lineWidth": width, "title": title,
                        "priceLineVisible": False, "lastValueVisible": True}}


def build_indicator_series(klines, selected):
    """按用户选择计算指标，返回 (主图叠加系列列表, 副图窗格列表)。

    主图叠加：MA(5/10/20)、EMA(12/26)、BOLL(20,2)
    副图窗格：RSI(14)（带 70/50/30 参考线）、KDJ(9,3,3)、MACD(12,26,9)
    """
    if not klines:
        return [], []
    df = pd.DataFrame(klines)
    times = df["time"].tolist()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    main_series, sub_panes = [], []

    if "MA" in selected:
        for n, color in [(5, "#ffffff"), (10, "#f0b90b"), (20, "#e040fb")]:
            main_series.append(_line_series(times, close.rolling(n).mean().tolist(),
                                            color, f"MA{n}"))
    if "EMA" in selected:
        for n, color in [(12, "#2196f3"), (26, "#ff9800")]:
            main_series.append(_line_series(times, close.ewm(span=n, adjust=False).mean().tolist(),
                                            color, f"EMA{n}"))
    if "BOLL" in selected:
        mid = close.rolling(20).mean()
        std = close.rolling(20).std(ddof=0)
        main_series.append(_line_series(times, (mid + 2 * std).tolist(), "#f6465d", "BOLL上"))
        main_series.append(_line_series(times, mid.tolist(), "#f0b90b", "BOLL中"))
        main_series.append(_line_series(times, (mid - 2 * std).tolist(), "#0ecb81", "BOLL下"))
    if "RSI" in selected:
        delta = close.diff()
        avg_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = (100 - 100 / (1 + rs)).fillna(50.0)
        rsi_series = _line_series(times, rsi.tolist(), "#e040fb", "RSI14")
        rsi_series["priceLines"] = [
            {"price": 70, "color": "#f6465d", "lineWidth": 1, "lineStyle": LINE_STYLE_DASHED,
             "axisLabelVisible": True, "title": ""},
            {"price": 50, "color": "#848e9c", "lineWidth": 1, "lineStyle": 1,
             "axisLabelVisible": True, "title": ""},
            {"price": 30, "color": "#0ecb81", "lineWidth": 1, "lineStyle": LINE_STYLE_DASHED,
             "axisLabelVisible": True, "title": ""},
        ]
        sub_panes.append({"chart": dict(SUB_CHART_CONFIG, height=140), "series": [rsi_series]})
    if "KDJ" in selected:
        low_n = low.rolling(9).min()
        high_n = high.rolling(9).max()
        rsv = ((close - low_n) / (high_n - low_n).replace(0, float("nan")) * 100).fillna(50.0)
        k_val = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        d_val = k_val.ewm(alpha=1 / 3, adjust=False).mean()
        j_val = 3 * k_val - 2 * d_val
        sub_panes.append({"chart": dict(SUB_CHART_CONFIG, height=160), "series": [
            _line_series(times, k_val.tolist(), "#ffffff", "K"),
            _line_series(times, d_val.tolist(), "#f0b90b", "D"),
            _line_series(times, j_val.tolist(), "#e040fb", "J"),
        ]})
    if "MACD" in selected:
        dif_list, dea_list, hist_list = calc_macd(klines)
        for p in hist_list:
            p["color"] = "#0ecb81" if p["value"] >= 0 else "#f6465d"
        sub_panes.append({"chart": dict(SUB_CHART_CONFIG, height=160), "series": [
            {"type": "Histogram", "data": hist_list,
             "options": {"color": "#0ecb81", "title": "MACD",
                         "priceLineVisible": False, "lastValueVisible": True}},
            {"type": "Line", "data": dif_list,
             "options": {"color": "#f0b90b", "lineWidth": 1, "title": "DIF",
                         "priceLineVisible": False, "lastValueVisible": True}},
            {"type": "Line", "data": dea_list,
             "options": {"color": "#2196f3", "lineWidth": 1, "title": "DEA",
                         "priceLineVisible": False, "lastValueVisible": True}},
        ]})
    return main_series, sub_panes


def calc_macd(klines, fast=12, slow=26, signal=9):
    """计算MACD指标：DIF = EMA_fast - EMA_slow, DEA = EMA_signal(DIF), MACD柱 = (DIF-DEA)*2"""
    closes = [k["close"] for k in klines]
    times = [k["time"] for k in klines]
    if len(closes) < slow + signal:
        return [], [], []
    
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = (dif - dea) * 2
    
    dif_list = [{"time": int(t), "value": round(float(v), 4)} for t, v in zip(times, dif)]
    dea_list = [{"time": int(t), "value": round(float(v), 4)} for t, v in zip(times, dea)]
    hist_list = [{"time": int(t), "value": round(float(v), 4)} for t, v in zip(times, macd_hist)]
    return dif_list, dea_list, hist_list


def plot_candlestick_chart(klines, indicators, symbol="BTCUSDT", height=560):
    """用plotly绘制原生K线图 + 技术指标（Streamlit 原生，云端/本地同源可用）"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if not klines:
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", height=height,
                          plot_bgcolor="#0b0e11", paper_bgcolor="#0b0e11")
        return fig
    
    # 准备数据
    df = pd.DataFrame(klines)
    df["datetime"] = pd.to_datetime(df["time"], unit="s")
    
    # 确定副图数量
    subplot_count = 1
    row_heights = [0.7]
    if "RSI" in indicators:
        subplot_count += 1
        row_heights.append(0.15)
    if "KDJ" in indicators:
        subplot_count += 1
        row_heights.append(0.15)
    if "MACD" in indicators:
        subplot_count += 1
        row_heights.append(0.2)
    
    fig = make_subplots(
        rows=subplot_count, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=row_heights,
    )
    
    # 1. K线主图
    fig.add_trace(go.Candlestick(
        x=df["datetime"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="K线",
        increasing_line_color="#0ecb81",
        decreasing_line_color="#f6465d",
    ), row=1, col=1)
    
    # 2. 主图叠加指标
    closes = df["close"]
    times = df["datetime"]
    
    if "MA" in indicators:
        for period, color in [(5, "#f0b90b"), (10, "#848e9c"), (20, "#e64980")]:
            ma = closes.rolling(window=period).mean()
            fig.add_trace(go.Scatter(
                x=times, y=ma, mode="lines",
                name=f"MA{period}", line=dict(color=color, width=1),
            ), row=1, col=1)
    
    if "EMA" in indicators:
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        fig.add_trace(go.Scatter(x=times, y=ema12, mode="lines", name="EMA12",
                                line=dict(color="#f0b90b", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=times, y=ema26, mode="lines", name="EMA26",
                                line=dict(color="#e64980", width=1)), row=1, col=1)
    
    if "BOLL" in indicators:
        ma20 = closes.rolling(window=20).mean()
        std20 = closes.rolling(window=20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        fig.add_trace(go.Scatter(x=times, y=upper, mode="lines", name="BOLL上轨",
                                line=dict(color="#848e9c", width=1, dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=times, y=ma20, mode="lines", name="BOLL中轨",
                                line=dict(color="#f0b90b", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=times, y=lower, mode="lines", name="BOLL下轨",
                                line=dict(color="#848e9c", width=1, dash="dash"), fill="tonexty"), row=1, col=1)
    
    current_row = 2
    
    # 3. RSI副图
    if "RSI" in indicators:
        delta = closes.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        fig.add_trace(go.Scatter(x=times, y=rsi, mode="lines", name="RSI(14)",
                                line=dict(color="#e64980", width=1.5)), row=current_row, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="#f6465d", row=current_row, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#0ecb81", row=current_row, col=1)
        fig.update_yaxes(title_text="RSI", row=current_row, col=1, range=[0, 100])
        current_row += 1
    
    # 4. KDJ副图
    if "KDJ" in indicators:
        low_list = df["low"].rolling(window=9).min()
        high_list = df["high"].rolling(window=9).max()
        rsv = (closes - low_list) / (high_list - low_list) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        
        fig.add_trace(go.Scatter(x=times, y=k, mode="lines", name="K",
                                line=dict(color="#f0b90b", width=1)), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=times, y=d, mode="lines", name="D",
                                line=dict(color="#e64980", width=1)), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=times, y=j, mode="lines", name="J",
                                line=dict(color="#0ecb81", width=1)), row=current_row, col=1)
        fig.update_yaxes(title_text="KDJ", row=current_row, col=1)
        current_row += 1
    
    # 5. MACD副图
    if "MACD" in indicators:
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = (dif - dea) * 2
        
        colors = ["#0ecb81" if v >= 0 else "#f6465d" for v in macd_hist]
        fig.add_trace(go.Bar(x=times, y=macd_hist, name="MACD柱", marker_color=colors),
                      row=current_row, col=1)
        fig.add_trace(go.Scatter(x=times, y=dif, mode="lines", name="DIF",
                                line=dict(color="#f0b90b", width=1.5)), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=times, y=dea, mode="lines", name="DEA",
                                line=dict(color="#e64980", width=1.5)), row=current_row, col=1)
        fig.add_hline(y=0, line_dash="solid", line_color="#848e9c", row=current_row, col=1)
        fig.update_yaxes(title_text="MACD", row=current_row, col=1)
    
    # 6. 开仓价线（pending 订单固定水平线：看涨红虚线 / 看跌绿虚线）
    pending_lines = _get_pending_price_lines(symbol)
    if pending_lines:
        for ln in pending_lines:
            fig.add_hline(
                y=ln["price"], row=1, col=1,
                line=dict(color=ln["color"], width=1, dash="dash"),
                annotation_text=ln["title"], annotation_position="top left",
                annotation_font=dict(color=ln["color"], size=11),
            )

    # 7. 布局设置
    # uirevision：同币种+同指标下每秒刷新保持不变，用户的缩放/平移状态不会被重置；
    # 切换币种或周期时该值变化，视图自动复位。
    fig.update_layout(
        title=f"{symbol} 实时行情",
        template="plotly_dark",
        height=height,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor="#0b0e11",
        paper_bgcolor="#0b0e11",
        font=dict(color="#eaecef"),
        uirevision=f"{symbol}-{','.join(indicators)}",
    )
    fig.update_xaxes(gridcolor="#2b3139")
    fig.update_yaxes(gridcolor="#2b3139")

    return fig


def hub_selftest(seconds=15):
    """脱离 streamlit 的连通性自检：python event_contract_pro_v6.py"""
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
    if kl:
        ms, sp = build_indicator_series(kl, ["MA", "EMA", "BOLL", "RSI", "KDJ"])
        print(f"[自检] 指标：主图叠加 {len(ms)} 条线，副图 {len(sp)} 个窗格")
        for s_ in ms:
            print(f"    主图 {s_['options']['title']:<7} 末值={s_['data'][-1]['value'] if s_['data'] else '-'}")
        for p in sp:
            for s_ in p["series"]:
                print(f"    副图 {s_['options']['title']:<7} 末值={s_['data'][-1]['value'] if s_['data'] else '-'}")


if __name__ == "__main__" and "streamlit" not in sys.modules:
    # 直接 `python event_contract_pro_v6.py` = 数据源+指标自检模式（无需安装 streamlit）
    # `streamlit run` 启动时 streamlit 已在 sys.modules 中，不会误入此分支
    hub_selftest()
    sys.exit(0)


# ==========================================
# ==========================================

# ==========================================
# 3. Streamlit 应用层（云端原生版：plotly 同源渲染）
# ==========================================
# 图表采用 Streamlit 原生 st.plotly_chart，数据在进程内直接生成、同源渲染，
# 不依赖任何 127.0.0.1 本地端口或 iframe，因此在 Streamlit Community Cloud
# 与本地 streamlit run 下行为完全一致。
#   - 图表本体放在 @st.fragment(run_every=1s) 内，每秒自动重绘最新 K 线；
#   - 通过 uirevision 在刷新间保持用户的缩放/平移状态，切换币种/周期时复位；
#   - 文字区（余额、最新价、倒计时、源状态、结算）同样用各自的 @st.fragment 刷新。
# ==========================================
import os

import streamlit as st

# ---- Page config & theme ----
st.set_page_config(page_title="事件合约模拟终端", layout="wide", page_icon="📈")

theme = {
    "bg": "#0b0e11", "text": "#eaecef", "card": "#181a20", "border": "#2b3139",
    "win": "#0ecb81", "loss": "#f6465d", "muted": "#848e9c", "brand": "#f0b90b",
}

st.markdown(
    f"""<style>
.stApp {{ background-color: {theme['bg']}; color: {theme['text']}; }}
.metric-card {{ background: {theme['card']}; padding: 15px; border-radius: 8px;
                border: 1px solid {theme['border']}; margin-bottom: 10px; }}
.winning {{ border-left: 4px solid {theme['win']}; }}
.losing  {{ border-left: 4px solid {theme['loss']}; }}
.section-note {{ color: {theme['muted']}; font-size: 13px; }}
</style>""",
    unsafe_allow_html=True,
)


# ---- Hub ----
@st.cache_resource
def get_hub():
    """全应用唯一行情中枢（跨 rerun / 跨会话共享）。"""
    return HUB


MANAGER = get_hub()
# 关键：每次 rerun 都会重新执行模块级 `HUB = MarketDataHub()`（见数据层），
# 产生一个新的空实例并覆盖全局名；而 get_hub() 经 cache_resource 始终返回首次
# 实例（worker / 回填线程都挂在它上面）。这里把全局名 HUB 复位到缓存实例，
# 否则本地数据服务 handler 查到的是 rerun 后的空 HUB，图表永远拿不到 K 线。
HUB = MANAGER


# ---- DB ----
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
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"balance": st.session_state.balance, "orders": st.session_state.orders},
                      f, ensure_ascii=False)
        os.replace(tmp, DB_FILE)  # 原子替换：数据服务线程读到的永远是完整文件
    except Exception as exc:
        st.toast(f"⚠️ 保存失败：{exc}", icon="⚠️")


# ---- Session state ----
if "balance" not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
st.session_state.setdefault("coin", "BTCUSDT")
st.session_state.setdefault("interval", "1m")
st.session_state.setdefault("duration", "5分钟")
st.session_state.setdefault("bet_amt", 100.0)

MANAGER.ensure_running(st.session_state.interval)


# ---- Trading logic ----
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
            continue
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


def fmt_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---- 价格线数据（从 DB 文件读取，供数据服务线程使用） ----
def _get_pending_price_lines(symbol):
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        lines = []
        for o in data.get("orders", []):
            if o.get("status") == "pending" and o.get("asset") == symbol:
                is_call = o.get("direction") == "call"
                lines.append({
                    "price": o["open_price"],
                    "color": CALL_LINE_COLOR if is_call else PUT_LINE_COLOR,
                    "lineWidth": 1,
                    "lineStyle": LINE_STYLE_DASHED,
                    "axisLabelVisible": True,
                    "title": f"{'CALL' if is_call else 'PUT'} {o.get('amount', 0):.0f}U",
                })
        return lines
    except Exception:
        return None  # 读取失败（如写入瞬间）→ None=未知，前端保持现有线不动


# ==========================================
# 3.3 局部刷新片段（文字区，不碰图表）
# ==========================================
@st.fragment(run_every=AUTO_REFRESH_SEC)
def live_account_panel():
    settle_due_orders()
    cur_price = MANAGER.get_price(st.session_state.coin)
    pending_orders = [o for o in st.session_state.orders if o["status"] == "pending"]
    closed_orders = [o for o in st.session_state.orders if o["status"] == "closed"]
    wins = len([o for o in closed_orders if o.get("result") == "win"])
    win_rate = f"{wins / len(closed_orders) * 100:.1f}%" if closed_orders else "-"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("账户余额 (USDT)", f"{st.session_state.balance:,.2f}")
    c2.metric(f"{st.session_state.coin} 最新价",
              f"{cur_price:,.4f}" if cur_price > 0 else "加载中…")
    c3.metric("待结算订单", len(pending_orders))
    c4.metric("历史胜率", win_rate)


@st.fragment(run_every=AUTO_REFRESH_SEC)
def live_holdings():
    pending_orders = [o for o in st.session_state.orders if o["status"] == "pending"]
    with st.container():
        st.subheader("持仓监控")
        if not pending_orders:
            st.markdown("<div class='section-note'>当前没有待结算订单</div>",
                        unsafe_allow_html=True)
        for o in pending_orders:
            now = time.time()
            remaining = o["settle_ts"] - now
            p_now = MANAGER.get_price(o["asset"])
            in_profit = ((o["direction"] == "call" and p_now > o["open_price"])
                         or (o["direction"] == "put" and p_now < o["open_price"])) if p_now > 0 else False
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


@st.fragment(run_every=AUTO_REFRESH_SEC)
def live_source_status():
    status_icon = {"online": "🟢", "connecting": "🟡", "reconnecting": "🟠",
                   "error": "🔴", "init": "⚪"}
    sources_status = MANAGER.get_status()
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


# ==========================================
# 3.4 主脚本
# ==========================================
st.title("📈 事件合约模拟交易终端")


@st.fragment(run_every=AUTO_REFRESH_SEC)
def health_banner():
    # 健康指示每秒随 fragment 自动刷新，避免启动早期（worker 尚未收数据）算出 0/4 后
    # 一直停在过期值；与侧边栏 live_source_status 保持同一刷新节奏。
    healthy = MANAGER.health()
    health_icon = "🟢" if healthy >= 2 else ("🟡" if healthy == 1 else "🔴")
    st.caption(
        f"数据源：币安 Binance + Gate.io + 火币 HTX + 欧易 OKX · 可用源 {health_icon} {healthy}/4"
        f" · 实时价=四源中位数 · 本终端为虚拟资金模拟盘，非真实交易"
    )


@st.fragment(run_every=AUTO_REFRESH_SEC)
def live_chart():
    """图表区每秒自动刷新：Streamlit 原生 plotly，数据在进程内，云端/本地同源可用。"""
    klines, chart_src = MANAGER.get_klines(st.session_state.coin)
    src_label = SOURCE_NAMES.get(chart_src, "-")
    selected = st.session_state.get("indicators", ["MA"])
    pane_count = sum(1 for x in ("RSI", "KDJ", "MACD") if x in selected)
    chart_height = 520 + pane_count * 170
    if klines:
        fig = plot_candlestick_chart(
            klines, selected, symbol=st.session_state.coin, height=chart_height)
        st.plotly_chart(
            fig, width="stretch",
            config={"displaylogo": False, "scrollZoom": True})
    else:
        st.info("📡 行情连接中，K 线加载后自动显示…")
    st.caption(f"K线源：{src_label} · 四家交易所实时价中位数 · 工具栏可缩放 / 平移 / 框选 / 复位")


health_banner()

live_account_panel()

# ---- 极速交易 ----
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
        f"<div class='section-note'>命中赔付 {PAYOUT_RATE}x（含本金）：潜在回款 "
        f"<b style='color:{theme['brand']}'>{potential:,.2f}U</b>，"
        f"单笔上限为余额的 {MAX_POSITION_RATIO:.0%}</div>",
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    col1.button("🟢 看涨 CALL", on_click=commit_order, args=("call",),
                type="primary", width="stretch")
    col2.button("🔴 看跌 PUT", on_click=commit_order, args=("put",),
                type="secondary", width="stretch")

# ---- 图表区域 ----
with st.container():
    hcol, icol = st.columns([2.2, 1])
    hcol.subheader(f"实时行情 · {st.session_state.coin} · {st.session_state.interval}")
    icol.multiselect(
        "技术指标（可叠加）", INDICATOR_OPTIONS, default=["MA"], key="indicators",
        label_visibility="collapsed", placeholder="选择技术指标：MA / EMA / BOLL / MACD / RSI / KDJ")

    # 图表本体在 fragment 内每秒自动刷新（plotly 原生，数据在进程内，云端/本地同源；
    # 用户的缩放/平移状态由 uirevision 在刷新间保持）。
    live_chart()

# ---- 持仓监控 ----
live_holdings()

# ---- 结算记录 ----
with st.container():
    st.subheader("结算记录")
    closed_orders = [o for o in st.session_state.orders if o["status"] == "closed"]
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
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.markdown("<div class='section-note'>暂无已结算订单</div>", unsafe_allow_html=True)

# ---- 侧边栏 ----
with st.sidebar:
    st.markdown("### 📜 规则说明")
    st.markdown(f"""
    - 赔率：**{PAYOUT_RATE}x**（命中含本金回款，未中归零，平局退款）
    - 风控：单笔 ≤ 余额的 **{MAX_POSITION_RATIO:.0%}**
    - 方向：**看涨**=结算价高于开仓价获胜；**看跌**=低于获胜
    - 价格口径：四家交易所实时价**中位数**，抗单源插针
    - 开仓价线：<span style='color:{CALL_LINE_COLOR}'>看涨=红虚线</span> /
      <span style='color:{PUT_LINE_COLOR}'>看跌=绿虚线</span>，开仓后固定不动
    - ⚠️ 1.8x 赔率 ⇒ 长期期望约 **-10%**，仅为模拟演示
    """, unsafe_allow_html=True)

    st.markdown("### 📊 图表指标")
    st.caption("MA(5/10/20)、EMA(12/26)、BOLL(20,2) 叠加主图；MACD(12,26,9)、RSI(14)、KDJ(9,3,3) 独立副图。"
               "在图表右上方下拉框自由勾选组合。图表支持滚轮缩放、拖拽平移、双指捏合，宽度自适应屏幕。")

    st.markdown("### 🔌 数据源状态")
    live_source_status()

    st.markdown("### 🔧 数据管理")
    st.caption("一键重置余额与全部订单（无需授权码）")
    if st.button("🔥 重置模拟账户", width="stretch"):
        st.session_state.balance = 10000.0
        st.session_state.orders = []
        save_db()
        st.toast("✅ 已重置为初始状态", icon="✅")
        time.sleep(0.5)
        st.rerun()

    st.markdown("---")
    st.markdown("""
    <div class='section-note'>
    ⚠️ 本终端为<b>虚拟资金模拟盘</b>，行情来自 币安 / HTX / OKX / Gate.io 公开接口，仅用于学习演示。
    二元期权类产品在多个司法辖区被禁止向零售投资者提供，请勿用于真实资金。
    </div>
    """, unsafe_allow_html=True)


