import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
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
# 1. 样式与配置
# ==========================================
st.set_page_config(page_title="Binance Pro", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    
    /* 核心补丁：隐藏右上角 Running 状态 */
    [data-testid="stStatusWidget"] { display: none !important; }

    /* 居中对齐补丁 */
    [data-testid="stHorizontalBlock"] { align-items: center !important; }

    /* 【核心需求】：隐藏 st.number_input 自带的加减按钮 */
    button[data-testid="stNumberInputStepUp"], 
    button[data-testid="stNumberInputStepDown"] {
        display: none !important;
    }
    /* 移除输入框内的数字滚动箭轴 */
    input[type=number]::-webkit-inner-spin-button, 
    input[type=number]::-webkit-outer-spin-button { 
@@ -70,138 +71,273 @@ st.markdown("""
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .checkmark-circle {
        width: 100px; height: 100px; border-radius: 50%; border: 5px solid #0ECB81;
        position: relative; animation: scale .3s ease-in-out;
    }
    .checkmark {
        display: block; width: 50px; height: 25px; border-bottom: 5px solid #0ECB81;
        border-left: 5px solid #0ECB81; transform: rotate(-45deg);
        position: absolute; top: 30px; left: 25px;
        animation: checkmark-anim 0.4s ease-in-out;
    }
    @keyframes checkmark-anim { 0% { width: 0; height: 0; } 100% { width: 50px; height: 25px; } }
    @keyframes scale { 0% { transform: scale(0); } 100% { transform: scale(1); } }
    
    .stButton button { border-radius: 12px !important; font-weight: bold !important; height: 45px !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 基础逻辑 (原封不动)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=1).json()
            return float(res[0]['last'])
        except: return None

def get_klines_smart_source(symbol, interval='1m'):
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
            res = requests.get(url, timeout=2).json()
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df
        except: return pd.DataFrame()
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def symbol_to_gate(symbol): return symbol.replace("USDT", "_USDT")

def symbol_to_okx(symbol): return symbol.replace("USDT", "-USDT")

def okx_bar(interval): return {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H"}.get(interval, "1m")

def fetch_json(url, timeout=1.5):
    res = requests.get(url, timeout=timeout)
    if res.status_code != 200:
        return None
    return res.json()

def fetch_price_binance(symbol):
    data = fetch_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
    if data and data.get('price'):
        return float(data['price']), "Binance"
    return None

def fetch_price_gate(symbol):
    g_sym = symbol_to_gate(symbol)
    data = fetch_json(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}")
    if data and isinstance(data, list) and data[0].get('last'):
        return float(data[0]['last']), "Gate"
    return None

def fetch_price_okx(symbol):
    okx_sym = symbol_to_okx(symbol)
    data = fetch_json(f"https://www.okx.com/api/v5/market/ticker?instId={okx_sym}")
    rows = (data or {}).get("data", [])
    if rows and rows[0].get('last'):
        return float(rows[0]['last']), "OKX"
    return None

def get_median_price(price_rows):
    prices = sorted([r[0] for r in price_rows])
    n = len(prices)
    if n == 1:
        return prices[0]
    if n % 2 == 1:
        return prices[n // 2]
    return (prices[n // 2 - 1] + prices[n // 2]) / 2

def get_price(symbol):
    providers = [fetch_price_binance, fetch_price_gate, fetch_price_okx]
    price_rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(fn, symbol) for fn in providers]
        for task in as_completed(tasks):
            try:
                row = task.result()
                if row:
                    price_rows.append(row)
            except:
                pass

    if price_rows:
        median_price = get_median_price(price_rows)
        src = min(price_rows, key=lambda x: abs(x[0] - median_price))[1]
        st.session_state.last_price_meta = {
            "source": src,
            "nodes": len(price_rows),
            "spread_pct": ((max([p[0] for p in price_rows]) - min([p[0] for p in price_rows])) / median_price * 100) if len(price_rows) > 1 else 0.0,
            "time": get_beijing_time().strftime('%H:%M:%S'),
        }
        st.session_state.price_cache[symbol] = median_price
        return median_price

    return st.session_state.price_cache.get(symbol)

def normalize_df(df):
    if df.empty:
        return df
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['time', 'open', 'high', 'low', 'close']).sort_values('time')
    return df.tail(100).reset_index(drop=True)

def fetch_klines_binance(symbol, interval='1m'):
    data = fetch_json(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100", timeout=2.5)
    if not data or not isinstance(data, list):
        return pd.DataFrame(), None
    df = pd.DataFrame(data).iloc[:, :6]
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
    df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
    return normalize_df(df), "Binance"

def fetch_klines_gate(symbol, interval='1m'):
    g_sym = symbol_to_gate(symbol)
    data = fetch_json(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100", timeout=2.5)
    if not data or not isinstance(data, list):
        return pd.DataFrame(), None
    df = pd.DataFrame(data).iloc[:, [0, 5, 3, 4, 2, 1]]
    df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
    df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
    return normalize_df(df), "Gate"

def fetch_klines_okx(symbol, interval='1m'):
    okx_sym = symbol_to_okx(symbol)
    bar = okx_bar(interval)
    data = fetch_json(f"https://www.okx.com/api/v5/market/candles?instId={okx_sym}&bar={bar}&limit=100", timeout=2.5)
    rows = (data or {}).get("data", [])
    if not rows:
        return pd.DataFrame(), None
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
                if not df.empty:
                    rows.append((df, source))
            except:
                pass

    if rows:
        best_df, best_source = max(rows, key=lambda x: (x[0]['time'].iloc[-1], len(x[0])))
        st.session_state.last_kline_meta = {
            "source": best_source,
            "nodes": len(rows),
            "time": get_beijing_time().strftime('%H:%M:%S'),
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

def save_db(balance, orders):␍␊
def save_db(balance, orders):␊
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

if 'balance' not in st.session_state: st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

def sync_bet_from_input():
    st.session_state.bet = max(10.0, float(st.session_state.bet_input))

def step_bet(delta):
    nxt = max(10.0, st.session_state.bet + delta)
    st.session_state.bet = nxt
    st.session_state.bet_input = nxt

def apply_live_price_to_latest_candle(df_k, curr_p):
    if df_k.empty or curr_p is None:
        return df_k
    live_df = df_k.copy()
    live_ts = get_beijing_time().replace(second=0, microsecond=0)
    if live_df['time'].iloc[-1] == live_ts:
        live_df.at[live_df.index[-1], 'close'] = curr_p
        live_df.at[live_df.index[-1], 'high'] = max(float(live_df['high'].iloc[-1]), curr_p)
        live_df.at[live_df.index[-1], 'low'] = min(float(live_df['low'].iloc[-1]), curr_p)
    else:
        new_row = {
            'time': live_ts,
            'open': float(live_df['close'].iloc[-1]),
            'high': curr_p,
            'low': curr_p,
            'close': curr_p,
            'vol': 0,
        }
        live_df = pd.concat([live_df, pd.DataFrame([new_row])], ignore_index=True)
    return live_df

if 'balance' not in st.session_state: st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'bet_input' not in st.session_state: st.session_state.bet_input = st.session_state.bet
if 'price_cache' not in st.session_state: st.session_state.price_cache = {}
if 'last_price_meta' not in st.session_state: st.session_state.last_price_meta = {"source": "-", "nodes": 0, "spread_pct": 0.0, "time": "-"}
if 'last_kline_meta' not in st.session_state: st.session_state.last_kline_meta = {"source": "-", "nodes": 0, "time": "-"}
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval = "1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5
if 'show_success' not in st.session_state: st.session_state.show_success = False

# ==========================================
# 3. 局部刷新组件
# ==========================================

@st.fragment
def chart_fragment():␍␊
    st_autorefresh(interval=3000, key="chart_refresh")
def chart_fragment():␊
    st_autorefresh(interval=1000, key="chart_refresh")
    now = get_beijing_time()
    curr_p = get_price(st.session_state.coin)
    
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    if st.session_state.mode == "TradingView":
        tv_i = "1" if st.session_state.interval == "1m" else st.session_state.interval.replace("m", "")
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)
    st.caption(f"价格源: {st.session_state.last_price_meta['source']} | 节点: {st.session_state.last_price_meta['nodes']}/3 | 偏差: {st.session_state.last_price_meta['spread_pct']:.4f}% | K线源: {st.session_state.last_kline_meta['source']}({st.session_state.last_kline_meta['nodes']}/3)")

    if st.session_state.mode == "TradingView":
        tv_i = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60"}.get(st.session_state.interval, "1")
        tv_html = f'<div style="height:450px;"><div id="tv" style="height:450px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>'
        components.html(tv_html, height=450)
    else:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        df_k = get_klines_smart_source(st.session_state.coin, st.session_state.interval)
        if not df_k.empty:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        df_k = get_klines_smart_source(st.session_state.coin, st.session_state.interval)
        df_k = apply_live_price_to_latest_candle(df_k, curr_p)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            ema12 = df_k['close'].ewm(span=12, adjust=False).mean()
            ema26 = df_k['close'].ewm(span=26, adjust=False).mean()
            df_k['dif'] = ema12 - ema26; df_k['dea'] = df_k['dif'].ewm(span=9, adjust=False).mean()
            df_k['hist'] = df_k['dif'] - df_k['dea']

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(41, 98, 255, 0.2)', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(41, 98, 255, 0.2)', width=1), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.03)') , row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1)), row=1, col=1)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'), row=1, col=1)
            
            for o in st.session_state.orders:
                if o['状态'] == "待结算" and o['资产'] == st.session_state.coin:
                    color = "#0ECB81" if o['方向'] == "看涨" else "#F6465D"
                    rem_sec = int((o['结算时间'] - now).total_seconds())
                    if rem_sec > 0:
                        # 【修正了这里的 KeyError，确保使用开仓价】
                        fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=color, line_width=1, row=1, col=1)
                        fig.add_annotation(x=df_k['time'].iloc[-3], y=o['开仓价'], text=f"{'↑' if o['方向']=='看涨' else '↓'} {rem_sec}s", 
                                           showarrow=False, font=dict(size=9, color=color), bgcolor="white", opacity=0.8, row=1, col=1)

            colors = ['#0ECB81' if v >= 0 else '#F6465D' for v in df_k['hist']]
@@ -289,43 +425,43 @@ if new_mode != st.session_state.mode: st.session_state.mode = new_mode; st.rerun
st.session_state.coin = t2.selectbox("交易币对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0, key="coin_select")
st.session_state.dur = t3.selectbox("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", key="dur_select")

ints = ["1m", "3m", "5m", "15m", "30m", "1h"]
cols = st.columns(len(ints))
for i, n in enumerate(ints):
    if cols[i].button(n, use_container_width=True, type="primary" if st.session_state.interval==n else "secondary"):
        st.session_state.interval = n; st.rerun()

chart_fragment()

st.markdown("<br>", unsafe_allow_html=True)
o1, o2 = st.columns(2)
def buy(dir):
    p = get_price(st.session_state.coin)
    if st.session_state.balance >= st.session_state.bet and p:
        st.session_state.balance -= st.session_state.bet
        st.session_state.orders.append({"资产": st.session_state.coin, "方向": dir, "开仓价": p, "金额": st.session_state.bet, "开仓时间": get_beijing_time(), "结算时间": get_beijing_time() + timedelta(minutes=st.session_state.dur), "状态": "待结算", "平仓价": None})
        save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

if o1.button("🟢 买涨 (UP)", use_container_width=True): buy("看涨")
if o2.button("🔴 买跌 (DOWN)", use_container_width=True): buy("看跌")

# 下单控制区：这里只显示你写的加减号
a1, a2, a3 = st.columns([1,2,1])
if a1.button("➖", use_container_width=True): ␍␊
    st.session_state.bet = max(10.0, st.session_state.bet - 10.0)
    st.rerun()␍␊
# 此框内的自带加减号已被 CSS 隐藏␍␊
st.session_state.bet = a2.number_input("AMT", value=st.session_state.bet, step=10.0, label_visibility="collapsed")
if a3.button("➕", use_container_width=True): ␍␊
    st.session_state.bet += 10.0
    st.rerun()␍␊
if a1.button("➖", use_container_width=True): ␊
    step_bet(-10.0)
    st.rerun()␊
# 此框内的自带加减号已被 CSS 隐藏␊
st.number_input("AMT", min_value=10.0, step=10.0, key="bet_input", on_change=sync_bet_from_input, label_visibility="collapsed")
if a3.button("➕", use_container_width=True): ␊
    step_bet(10.0)
    st.rerun()␊

order_flow_fragment()

with st.sidebar:
    st.markdown("<br>"*20, unsafe_allow_html=True)
    if st.checkbox("⚙️ 系统重置"):
        pwd = st.text_input("输入授权码", type="password")
        if pwd == "522087":
            if st.button("🔴 确认清空所有账户数据"):
                st.session_state.balance = 1000.0; st.session_state.orders = []; save_db(1000.0, []); st.rerun()
