"""Streamlit app entrypoint. Keep this file pure Python source (no shell patch snippets)."""

import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 样式与配置 (极致币安官方化 UI)
# ==========================================
st.set_page_config(page_title="Binance Event Contracts", layout="centered", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

STYLE_BLOCK = '''
<style>
    /* 全局重置与移动端比例锁定 */
    html, body, [class*="css"] {
        font-family: "BinancePlex", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    }
    .stApp { background-color: #FAFAFA; }
    .block-container { 
        padding: 0 !important; /* 彻底去除自带边距 */
        max-width: 480px !important; 
        margin: auto; 
        background-color: #FFFFFF;
        min-height: 100vh;
        box-shadow: 0 0 20px rgba(0,0,0,0.05); /* 在 PC 上也能有手机壳的阴影感 */
    }
    
    /* 隐藏所有多余的 Streamlit 原生组件 */
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stStatusWidget"], footer { display: none !important; }

    /* --- 币安官方头部栏 --- */
    .binance-header {
        background-color: #181A20;
        padding: 12px 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #EAECEF;
        position: sticky;
        top: 0;
        z-index: 999;
    }
    .binance-logo { font-weight: 800; font-size: 1.1rem; color: #FCD535; letter-spacing: 0.5px; display: flex; align-items: center; }
    .binance-logo span { color: #EAECEF; margin-left: 4px; font-weight: 600; font-size: 0.9rem; }
    .header-right { font-size: 0.8rem; font-weight: 500; color: #848E9C; }

    /* --- 核心资产与行情区 --- */
    .market-panel { padding: 16px; background: #FFFFFF; border-bottom: 1px solid #EAECEF; }
    .asset-row { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 4px; }
    .asset-name { font-size: 1.6rem; font-weight: 800; color: #1E2329; line-height: 1; }
    .balance-label { font-size: 0.75rem; color: #848E9C; margin-bottom: 2px; text-align: right; }
    .balance-val { font-size: 1rem; font-weight: 700; color: #1E2329; }
    
    .price-display { font-size: 2.2rem; font-weight: 700; line-height: 1.1; margin: 8px 0 4px 0; font-family: "SF Pro Display", sans-serif; }
    .price-up { color: #0ECB81; }
    .price-down { color: #F6465D; }
    .price-meta { font-size: 0.7rem; color: #B7BDC6; }

    /* --- 图表与时间选择 --- */
    .stPlotlyChart { min-height: 380px; margin-top: -10px; }
    div[data-testid="stHorizontalBlock"] { align-items: center !important; }
    
    /* 时间周期按钮样式重构 (更像原生 Tab) */
    .interval-tabs div[data-testid="column"] button {
        background-color: transparent !important;
        color: #848E9C !important;
        border: none !important;
        box-shadow: none !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        padding: 4px 0 !important;
        border-radius: 0 !important;
    }
    .interval-tabs div[data-testid="column"] button:focus, .interval-tabs div[data-testid="column"] button:hover {
        color: #1E2329 !important;
    }
    /* 强行注入选中态样式逻辑(依托主程序逻辑配合) */

    /* --- 交易面板区 --- */
    .trading-panel { padding: 16px; background: #FFFFFF; border-top: 4px solid #FAFAFA; }
    
    /* 彻底重构 Number Input 外观 */
    button[data-testid="stNumberInputStepUp"], button[data-testid="stNumberInputStepDown"] { display: none !important; }
    input[type=number]::-webkit-inner-spin-button, input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
    input[type=number] { -moz-appearance: textfield; }
    div[data-testid="stNumberInput"] input {
        height: 44px !important;
        text-align: center !important;
        font-weight: 700 !important;
        font-size: 1.1rem !important;
        background: #F5F5F5 !important;
        border: 1px solid transparent !important;
        border-radius: 4px !important;
        color: #1E2329 !important;
    }
    div[data-testid="stNumberInput"] input:focus { border-color: #FCD535 !important; background: #FFF !important; }

    /* 加减号按钮 */
    .amt-btn button {
        height: 44px !important; background: #F5F5F5 !important; border: none !important; border-radius: 4px !important; color: #1E2329 !important; font-weight: bold !important;
    }
    .amt-btn button:active { background: #EAECEF !important; }

    /* 看涨/看跌 按钮 */
    .action-btns div[data-testid="column"]:nth-of-type(1) button {
        background-color: #0ECB81 !important; color: white !important; font-size: 1rem !important; font-weight: 700 !important; border: none !important; border-radius: 4px !important; height: 48px !important;
    }
    .action-btns div[data-testid="column"]:nth-of-type(2) button {
        background-color: #F6465D !important; color: white !important; font-size: 1rem !important; font-weight: 700 !important; border: none !important; border-radius: 4px !important; height: 48px !important;
    }
    .action-btns button:active { transform: scale(0.98); }

    /* --- 订单卡片 (官方持仓样式) --- */
    .orders-section { padding: 16px; background: #FAFAFA; min-height: 200px; }
    .section-title { font-size: 1rem; font-weight: 700; color: #1E2329; margin-bottom: 12px; }
    
    .binance-card {
        background: #FFFFFF; border-radius: 4px; padding: 12px; margin-bottom: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02); border: 1px solid #EAECEF;
    }
    .card-header { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: center; }
    .card-title { font-weight: 700; font-size: 1rem; display: flex; align-items: center; }
    .tag-up { background: rgba(14, 203, 129, 0.1); color: #0ECB81; padding: 2px 6px; border-radius: 2px; font-size: 0.7rem; margin-right: 6px; }
    .tag-down { background: rgba(246, 70, 93, 0.1); color: #F6465D; padding: 2px 6px; border-radius: 2px; font-size: 0.7rem; margin-right: 6px; }
    .card-status { font-size: 0.8rem; font-weight: 500; }
    
    .data-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    .data-item { display: flex; flex-direction: column; }
    .d-label { font-size: 0.7rem; color: #848E9C; margin-bottom: 2px; }
    .d-val { font-size: 0.85rem; font-weight: 600; color: #1E2329; }
    
    /* 官方 Toast 弹窗 */
    .toast-overlay {
        position: fixed; top: 40%; left: 50%; transform: translate(-50%, -50%);
        background: rgba(30, 35, 41, 0.9); color: white; padding: 16px 24px;
        border-radius: 8px; z-index: 9999; text-align: center; font-weight: 600;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); animation: fadein 0.2s;
    }
    @keyframes fadein { from { opacity: 0; transform: translate(-50%, -40%); } to { opacity: 1; transform: translate(-50%, -50%); } }

    /* 顶部细线统计 */
    .stats-line { display: flex; justify-content: space-between; font-size: 0.75rem; color: #848E9C; padding-bottom: 12px; border-bottom: 1px solid #EAECEF; margin-bottom: 12px; }
    .stats-line span { font-weight: 600; }
</style>
'''
st.markdown(STYLE_BLOCK, unsafe_allow_html=True)

# ==========================================
# 2. 基础逻辑 (绝对保持不变，确保数据和交易功能准确)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)
def symbol_to_gate(symbol): return symbol.replace("USDT", "_USDT")
def symbol_to_okx(symbol): return symbol.replace("USDT", "-USDT")
def okx_bar(interval): return 
def fetch_json(url, timeout=1.5):
    res = requests.get(url, timeout=timeout)
    if res.status_code != 200: return None
    return res.json()

def fetch_price_binance(symbol):
    data = fetch_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
    if data and data.get('price'): return float(data['price']), "Binance"
    return None

def fetch_price_gate(symbol):
    g_sym = symbol_to_gate(symbol)
    data = fetch_json(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}")
    if data and isinstance(data, list) and data[0].get('last'): return float(data[0]['last']), "Gate"
    return None

def fetch_price_okx(symbol):
    okx_sym = symbol_to_okx(symbol)
    data = fetch_json(f"https://www.okx.com/api/v5/market/ticker?instId={okx_sym}")
    rows = (data or {}).get("data", [])
    if rows and rows[0].get('last'): return float(rows[0]['last']), "OKX"
    return None

def get_median_price(price_rows):
    prices = sorted([r[0] for r in price_rows])
    n = len(prices)
    if n == 1: return prices[0]
    if n % 2 == 1: return prices[n // 2]
    return (prices[n // 2 - 1] + prices[n // 2]) / 2

def get_price(symbol):
    providers = [fetch_price_binance, fetch_price_gate, fetch_price_okx]
    price_rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(fn, symbol) for fn in providers]
        for task in as_completed(tasks):
            try:
                row = task.result()
                if row: price_rows.append(row)
            except: pass

    if price_rows:
        median_price = get_median_price(price_rows)
        src = min(price_rows, key=lambda x: abs(x[0] - median_price))[1]
        st.session_state.last_price_meta = {
            "source": src, "nodes": len(price_rows),
            "spread_pct": ((max([p[0] for p in price_rows]) - min([p[0] for p in price_rows])) / median_price * 100) if len(price_rows) > 1 else 0.0,
            "time": get_beijing_time().strftime('%H:%M:%S'),
        }
        st.session_state.price_cache[symbol] = median_price
        return median_price
    return st.session_state.price_cache.get(symbol)

def normalize_df(df):
    if df.empty: return df
    for c in ['open', 'high', 'low', 'close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['time', 'open', 'high', 'low', 'close']).sort_values('time')
    return df.tail(100).reset_index(drop=True)

def fetch_klines_binance(symbol, interval='1m'):
    data = fetch_json(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100", timeout=2.5)
    if not data or not isinstance(data, list): return pd.DataFrame(), None
    df = pd.DataFrame(data).iloc[:, :6]
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
    df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
    return normalize_df(df), "Binance"

def fetch_klines_gate(symbol, interval='1m'):
    g_sym = symbol_to_gate(symbol)
    data = fetch_json(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100", timeout=2.5)
    if not data or not isinstance(data, list): return pd.DataFrame(), None
    df = pd.DataFrame(data).iloc[:, [0, 5, 3, 4, 2, 1]]
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
    df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
    return normalize_df(df), "Gate"

def fetch_klines_okx(symbol, interval='1m'):
    okx_sym = symbol_to_okx(symbol)
    bar = okx_bar(interval)
    data = fetch_json(f"https://www.okx.com/api/v5/market/candles?instId={okx_sym}&bar={bar}&limit=100", timeout=2.5)
    rows = (data or {}).get("data", [])
    if not rows: return pd.DataFrame(), None
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
    df['time'] = pd.to_datetime(df['time'].astype('int64'), unit='ms') + timedelta(hours=8)
    return normalize_df(df), "OKX"

def get_klines_smart_source(symbol, interval='1m'):
    providers = [fetch_klines_binance, fetch_klines_gate, fetch_klines_okx]
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(fn, symbol, interval) for fn in providers]
        for task in as_completed(tasks):
            try:
                df, source = task.result()
                if not df.empty: rows.append((df, source))
            except: pass
    if rows:
        best_df, best_source = max(rows, key=lambda x: (x[0]['time'].iloc[-1], len(x[0])))
        st.session_state.last_kline_meta = {
            "source": best_source, "nodes": len(rows), "time": get_beijing_time().strftime('%H:%M:%S'),
        }
        return best_df
    return pd.DataFrame()
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f); orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if od.get(key) and isinstance(od[key], str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

def sync_bet_from_input(): st.session_state.bet = max(10.0, float(st.session_state.bet_input))

def step_bet(delta):
    base = float(st.session_state.get('bet_input', st.session_state.bet))
    nxt = max(10.0, base + delta)
    st.session_state.bet_input = nxt
    st.session_state.bet = nxt

def interval_seconds(interval): return {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}.get(interval, 60)

def get_bucket_time(interval, now=None):
    now = now or get_beijing_time()
    step = interval_seconds(interval)
    bucket_sec = int(now.timestamp() // step * step)
    return pd.to_datetime(bucket_sec, unit='s')

def build_incremental_indicators(history_df):
    if history_df.empty: return history_df.copy()
    ind_df = history_df.copy()
    ind_df['ma'] = ind_df['close'].rolling(20).mean()
    ind_df['std'] = ind_df['close'].rolling(20).std()
    ind_df['up'] = ind_df['ma'] + 2 * ind_df['std']
    ind_df['dn'] = ind_df['ma'] - 2 * ind_df['std']
    ema12 = ind_df['close'].ewm(span=12, adjust=False).mean()
    ema26 = ind_df['close'].ewm(span=26, adjust=False).mean()
    ind_df['dif'] = ema12 - ema26
    ind_df['dea'] = ind_df['dif'].ewm(span=9, adjust=False).mean()
    ind_df['hist'] = ind_df['dif'] - ind_df['dea']
    return ind_df

def get_live_klines_incremental(symbol, interval, curr_p):
    cache_key = f"{symbol}_{interval}"
    now = get_beijing_time()
    now_ts = time.time()
    bucket_time = get_bucket_time(interval, now)
    runtime = st.session_state.kline_runtime.setdefault(cache_key, {
        'last_sync_ts': 0.0, 'history_df': pd.DataFrame(), 'active_candle': None, 'active_bucket': None, 'indicator_df': pd.DataFrame(), 'indicator_sig': None,
    })
if (now_ts - runtime['last_sync_ts']) >= 10:
        fresh_df = get_klines_smart_source(symbol, interval)
        if not fresh_df.empty:
            closed_df = fresh_df[fresh_df['time'] < bucket_time].copy().tail(119).reset_index(drop=True)
            bucket_df = fresh_df[fresh_df['time'] == bucket_time]
            runtime['history_df'] = closed_df
            if not bucket_df.empty:
                row = bucket_df.iloc[-1]
                runtime['active_candle'] = {'time': row['time'], 'open': float(row['open']), 'high': float(row['high']), 'low': float(row['low']), 'close': float(row['close']), 'vol': float(row.get('vol', 0) or 0)}
                runtime['active_bucket'] = bucket_time
            elif not closed_df.empty:
                px = float(closed_df['close'].iloc[-1])
                runtime['active_candle'] = {'time': bucket_time, 'open': px, 'high': px, 'low': px, 'close': px, 'vol': 0.0}
                runtime['active_bucket'] = bucket_time
            runtime['last_sync_ts'] = now_ts

    active = runtime['active_candle']
    if active is None:
        hist = runtime['history_df']
        if hist.empty: return pd.DataFrame(), pd.DataFrame(), None
        px = float(hist['close'].iloc[-1])
        active = {'time': bucket_time, 'open': px, 'high': px, 'low': px, 'close': px, 'vol': 0.0}
        runtime['active_candle'] = active
        runtime['active_bucket'] = bucket_time

    if runtime['active_bucket'] is not None and bucket_time > runtime['active_bucket']:
        old_active = runtime['active_candle']
        old_row = pd.DataFrame([old_active])
        runtime['history_df'] = pd.concat([runtime['history_df'], old_row], ignore_index=True).tail(120).reset_index(drop=True)
        new_open = float(old_active['close'])
        seed = curr_p if curr_p is not None else new_open
        runtime['active_candle'] = {'time': bucket_time, 'open': new_open, 'high': max(new_open, float(seed)), 'low': min(new_open, float(seed)), 'close': float(seed), 'vol': 0.0}
        runtime['active_bucket'] = bucket_time

    if curr_p is not None:
        runtime['active_candle']['close'] = float(curr_p)
        runtime['active_candle']['high'] = max(float(runtime['active_candle']['high']), float(curr_p))
        runtime['active_candle']['low'] = min(float(runtime['active_candle']['low']), float(curr_p))

    history_df = runtime['history_df'].copy()
    sig = (len(history_df), str(history_df['time'].iloc[-1]) if not history_df.empty else '-')
    if sig != runtime['indicator_sig']:
        runtime['indicator_df'] = build_incremental_indicators(history_df)
        runtime['indicator_sig'] = sig

    active_df = pd.DataFrame([runtime['active_candle']])
    merged_df = pd.concat([history_df, active_df], ignore_index=True)
    return merged_df, runtime['indicator_df'].copy(), runtime['active_candle'].copy()

# ==========================================
# 3. 状态初始化
# ==========================================
if 'balance' not in st.session_state: st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'bet_input' not in st.session_state: st.session_state.bet_input = st.session_state.bet
if 'price_cache' not in st.session_state: st.session_state.price_cache = {}
if 'kline_cache' not in st.session_state: st.session_state.kline_cache = {}
if 'kline_runtime' not in st.session_state: st.session_state.kline_runtime = {}
if 'last_price_meta' not in st.session_state: st.session_state.last_price_meta = {"source": "-", "nodes": 0, "spread_pct": 0.0, "time": "-"}
if 'last_kline_meta' not in st.session_state: st.session_state.last_kline_meta = {"source": "-", "nodes": 0, "time": "-"}
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval = "1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5
if 'show_success' not in st.session_state: st.session_state.show_success = False
# ==========================================
# 4. UI 渲染与组装
# ==========================================

# 成功的 Toast 提示 (官方感)
if st.session_state.show_success:
    st.markdown('<div class="toast-overlay">✅ 委托提交成功</div>', unsafe_allow_html=True)
    time.sleep(0.8); st.session_state.show_success = False; st.rerun()

# 官方顶部导航栏
st.markdown('''
<div class="binance-header">
    <div class="binance-logo">BINANCE <span>PRO</span></div>
    <div class="header-right">Event Contracts</div>
</div>
''', unsafe_allow_html=True)

@st.fragment
def chart_fragment():
    st_autorefresh(interval=1500, key="chart_refresh") 
    curr_p = get_price(st.session_state.coin)
    
    # 颜色判断逻辑
    prev_p = st.session_state.get('prev_p_for_color', curr_p)
    if curr_p and prev_p and curr_p != prev_p:
        color_class = "price-up" if curr_p > prev_p else "price-down"
        st.session_state.prev_p_for_color = curr_p
    else:
        color_class = "price-up"

    # 行情面板
    st.markdown(f'''
        <div class="market-panel">
            <div class="asset-row">
                <div class="asset-name">{st.session_state.coin.replace('USDT','/USDT')}</div>
                <div>
                    <div class="balance-label">可用保证金 (USDT)</div>
                    <div class="balance-val">{st.session_state.balance:,.2f}</div>
                </div>
            </div>
            <div class="price-display {color_class}">{f"{curr_p:,.2f}" if curr_p else "0.00"}</div>
            <div class="price-meta">指数源: {st.session_state.last_price_meta['source']} | 节点延迟: 极低 | 汇差: {st.session_state.last_price_meta['spread_pct']:.3f}%</div>
        </div>
    ''', unsafe_allow_html=True)

    # 时间周期 Tabs (伪装成原生的无边框文字 Tab)
    st.markdown('<div class="interval-tabs" style="padding: 4px 16px; background: #FFFFFF; border-bottom: 1px solid #EAECEF;">', unsafe_allow_html=True)
    ints = ["1m", "3m", "5m", "15m", "30m", "1h"]
    cols = st.columns(len(ints), gap="small")
    for i, n in enumerate(ints):
        # 如果是选中状态，强行用 inline CSS 标记颜色
        color = "#1E2329" if st.session_state.interval == n else "#848E9C"
        weight = "700" if st.session_state.interval == n else "500"
        border = "2px solid #FCD535" if st.session_state.interval == n else "2px solid transparent"
        
        # 通过在外部包裹 div 来实现底部黄线效果，因为 Streamlit 按钮不好改
        st.markdown(f"""
        <style>
        div[data-testid="column"]:nth-of-type({i+1}) button {{ color: {color} !important; font-weight: {weight} !important; border-bottom: {border} !important; }}
        </style>
        """, unsafe_allow_html=True)
        
        if cols[i].button(n, use_container_width=True, key=f"tab_{n}"):
            st.session_state.interval = n; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # 图表区
    if st.session_state.mode == "TradingView":
        tv_i = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60"}.get(st.session_state.interval, "1")
        tv_html = f'<div style="height:380px; overflow:hidden;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","hide_top_toolbar":true,"hide_legend":true,"container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>'
        components.html(tv_html, height=380)
    else:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        df_k, indicator_df, active_candle = get_live_klines_incremental(st.session_state.coin, st.session_state.interval, curr_p)
        if not df_k.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.0, row_heights=[0.75, 0.25])

            if not indicator_df.empty:
                fig.add_trace(go.Scatter(x=indicator_df['time'], y=indicator_df['up'], line=dict(color='rgba(41, 98, 255, 0.2)', width=1)), row=1, col=1)
                fig.add_trace(go.Scatter(x=indicator_df['time'], y=indicator_df['dn'], line=dict(color='rgba(41, 98, 255, 0.2)', width=1), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.03)'), row=1, col=1)
                fig.add_trace(go.Scatter(x=indicator_df['time'], y=indicator_df['ma'], line=dict(color='#FCD535', width=1.5)), row=1, col=1)

                colors = ['#0ECB81' if v >= 0 else '#F6465D' for v in indicator_df['hist']]
                fig.add_trace(go.Bar(x=indicator_df['time'], y=indicator_df['hist'], marker_color=colors), row=2, col=1)
                fig.add_trace(go.Scatter(x=indicator_df['time'], y=indicator_df['dif'], line=dict(color='#2962FF', width=1)), row=2, col=1)
                fig.add_trace(go.Scatter(x=indicator_df['time'], y=indicator_df['dea'], line=dict(color='#FF6D00', width=1)), row=2, col=1)

            fig.add_trace(go.Candlestick(
                            x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
                increasing_line_color='#0ECB81', decreasing_line_color='#F6465D',
                increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'
            ), row=1, col=1)

            if active_candle is not None:
                fig.add_hline(y=active_candle['close'], line_width=1, line_dash='dash', line_color='#1E2329', row=1, col=1)

            # 极简官方风格坐标轴
            fig.update_xaxes(showgrid=True, gridcolor='#F5F5F5', zeroline=False, visible=False, row=1, col=1)
            fig.update_xaxes(showgrid=False, zeroline=False, visible=False, row=2, col=1)
            fig.update_yaxes(showgrid=True, gridcolor='#F5F5F5', zeroline=False, side='right', tickfont=dict(size=10, color='#848E9C'), row=1, col=1)
            fig.update_yaxes(showgrid=False, zeroline=False, visible=False, row=2, col=1)

            fig.update_layout(
                height=380, margin=dict(t=10, b=0, l=0, r=0),
                xaxis_rangeslider_visible=False, plot_bgcolor='white', paper_bgcolor='white',
                showlegend=False, dragmode='pan',
                uirevision=f"{st.session_state.coin}_{st.session_state.interval}", transition=dict(duration=0)
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': True}, key="native_kline_chart")

chart_fragment()

# ==========================================
# 交易控制区 (Trading Panel)
# ==========================================
st.markdown('<div class="trading-panel">', unsafe_allow_html=True)

# 快速设置栏 (隐藏在流式布局中)
t1, t2, t3 = st.columns([1,1,1.2], gap="small")
new_mode = t1.selectbox("引擎", ["原生 K 线", "TradingView"], index=0 if st.session_state.mode=="原生 K 线" else 1, label_visibility="collapsed")
if new_mode != st.session_state.mode: st.session_state.mode = new_mode; st.rerun()
st.session_state.coin = t2.selectbox("资产", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0, key="coin_select", label_visibility="collapsed")
st.session_state.dur = t3.selectbox("交割", [5, 10, 30, 60], format_func=lambda x: f"{x}分钟交割", key="dur_select", label_visibility="collapsed")

# 官方风格的数量输入框
a1, a2, a3 = st.columns([1, 2.5, 1], gap="small")
with a1:
    st.markdown('<div class="amt-btn">', unsafe_allow_html=True)
    st.button("一", use_container_width=True, key="bet_minus_btn", on_click=step_bet, args=(-10.0,))
    st.markdown('</div>', unsafe_allow_html=True)
with a2:
    amt_val = st.number_input("AMT", min_value=10.0, step=10.0, key="bet_input", on_change=sync_bet_from_input, label_visibility="collapsed")
    st.session_state.bet = max(10.0, float(amt_val))
with a3:
    st.markdown('<div class="amt-btn">', unsafe_allow_html=True)
    st.button("十", use_container_width=True, key="bet_plus_btn", on_click=step_bet, args=(10.0,))
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div style="margin-top: 8px;"></div>', unsafe_allow_html=True)

# 操作大按钮
st.markdown('<div class="action-btns">', unsafe_allow_html=True)
o1, o2 = st.columns(2, gap="small")
def buy(dir):
    p = get_price(st.session_state.coin)
    if st.session_state.balance >= st.session_state.bet and p:
        st.session_state.balance -= st.session_state.bet
        st.session_state.orders.append({"资产": st.session_state.coin, "方向": dir, "开仓价": p, "金额": st.session_state.bet, "开仓时间": get_beijing_time(), "结算时间": get_beijing_time() + timedelta(minutes=st.session_state.dur), "状态": "待结算", "平仓价": None})
        save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

if o1.button("买入做多 (Call)", use_container_width=True): buy("看涨")
if o2.button("卖出做空 (Put)", use_container_width=True): buy("看跌")
st.markdown('</div></div>', unsafe_allow_html=True)

# ==========================================
# 订单流列表 (Positions / History)
# ==========================================
@st.fragment
def order_flow_fragment():
    st_autorefresh(interval=1000, key="flow_refresh")
    now = get_beijing_time()
    
    upd = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            p_final = get_price(od['资产'])
            if p_final:
                od['平仓价'] = p_final
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                upd = True
    if upd: save_db(st.session_state.balance, st.session_state.orders)

    all_settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
    today_settled = [o for o in all_settled if o['结算时间'].date() == now.date()]
    today_p = sum([(o['金额']*0.8 if o['结果']=="W" else -o['金额']) for o in today_settled])
    today_win_rate = (len([o for o in today_settled if o['结果']=="W"]) / len(today_settled) * 100) if today_settled els
            if o['状态'] == "待结算":
            total_sec = (o['结算时间'] - o['开仓时间']).total_seconds()
            past_sec = (now - o['开仓时间']).total_seconds()
            pct = min(100, max(0, int((past_sec / total_sec) * 100))) if total_sec > 0 else 100
            
            # 使用边框左侧的高亮来标识方向，就像原生 App 一样
            border_color = "#0ECB81" if is_up else "#F6465D"
            status_html = f'<span class="card-status" style="color:#1E2329;">倒计时 {100-pct}%</span>'
            pnl_val = "交割中"
            pnl_color = "#1E2329"
            close_price = "---"
        else:
            win = o.get('结果') == "W"
            border_color = "#EAECEF" # 结平后恢复灰边
            status_html = '<span class="card-status" style="color:#848E9C;">已结算</span>'
            pnl_num = o['金额'] * 0.8 if win else -o['金额']
            pnl_val = f"{pnl_num:+.2f} USDT"
            pnl_color = "#0ECB81" if win else "#F6465D"
            close_price = f"{o['平仓价']:,.2f}"

        st.markdown(f"""
        <div class="binance-card" style="border-left: 3px solid {border_color};">
            <div class="card-header">
                <div class="card-title"><span class="{tag_class}">{tag_text}</span> {o['资产']}</div>
                {status_html}
            </div>
            <div class="data-grid">
                <div class="data-item"><span class="d-label">数量 (USDT)</span><span class="d-val">{o['金额']:.2f}</span></div>
                <div class="data-item"><span class="d-label">开仓价格</span><span class="d-val">{o['开仓价']:,.2f}</span></div>
                <div class="data-item"><span class="d-label">结算价格</span><span class="d-val">{close_price}</span></div>
                <div class="data-item"><span class="d-label">预估强平</span><span class="d-val" style="color:#848E9C;">--</span></div>
                <div class="data-item"><span class="d-label">保证金比率</span><span class="d-val" style="color:#848E9C;">100%</span></div>
                <div class="data-item"><span class="d-label">盈亏</span><span class="d-val" style="color:{pnl_color};">{pnl_val}</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

order_flow_fragment()

# 侧边栏清理工具 (隐藏使用)
with st.sidebar:
    st.markdown("<br>"*10, unsafe_allow_html=True)
    pwd = st.text_input("重置授权", type="password")
    if pwd == "522087" and st.button("🔴 清空数据"):
        st.session_state.balance = 1000.0; st.session_state.orders = []; save_db(1000.0, []); st.rerun()
        
