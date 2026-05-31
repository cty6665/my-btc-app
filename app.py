import streamlit as st
import pandas as pd
import requests
import json
import os
import time
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
# ==========================================
# 1. 核心配置与日志初始化
# ==========================================
st.set_page_config(page_title="Binance Pro", layout="wide",
initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"
AUTH_HASH = "8098c92cd86b247f6d2139049a4cd860953c8a91605e548dbbb09bdffca64d0e" #
SHA256 for 522087
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
STYLE_BLOCK = '''
<style> .stApp { background-color: #fcfcfc; }
[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHorizontalBlock"] { align-items: center
!important; }
button[data-testid="stNumberInputStepUp"],
button[data-testid="stNumberInputStepDown"] { display: none
!important; }
input[type=number]::-webkit-inner-spin-button,
input[type=number]::-webkit-outer-spin-button { -webkit-appearance:
none; margin: 0; }
input[type=number] { -moz-appearance: textfield; }
.data-card { background: #ffffff; padding: 12px; border-radius:
12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-top: 4px solid
#FCD535; text-align: center; margin-bottom: 8px; }
.balance-border { border-top: 4px solid #0ECB81; }
.card-label { color: #848e9c; font-size: 0.8rem; }
.card-value { color: #1e2329; font-size: 1.4rem; font-weight: 800;
}
.stats-container { display: grid; grid-template-columns: repeat(4,
1fr); gap: 10px; background: #f8f9fa; padding: 15px; border-radius:
10px; margin-bottom: 15px; }
.stat-item { text-align: center; border-right: 1px solid #eee; }
.stat-item:last-child { border-right: none; }
.stat-label { font-size: 0.75rem; color: #848e9c; }
.stat-val { font-size: 1rem; font-weight: bold; margin-top: 4px; }
.stPlotlyChart { min-height: 450px; }
.order-card-container { position: relative; background: white;
border-radius: 10px; margin-bottom: 12px; border: 1px solid #eee;
overflow: hidden; }
.order-progress-bg { padding: 15px; width: 100%; height: 100%;
position: relative; }
.order-header { display: flex; justify-content: space-between;
align-items: center; margin-bottom: 8px; position: relative; z-index:
5; }
.order-grid { display: grid; grid-template-columns: 1fr 1fr 1fr;
gap: 8px; position: relative; z-index: 5; }
.grid-label { color: #848e9c; font-size: 0.7rem; }
.grid-val { color: #1e2329; font-size: 0.85rem; font-weight: 600;
margin-top: 2px; }
.success-overlay { position: fixed; top: 0; left: 0; width: 100%;
height: 100%; background: rgba(255,255,255,0.9); z-index: 9999;
display: flex; flex-direction: column; align-items: center;
justify-content: center; }
.checkmark-circle { width: 100px; height: 100px; border-radius:
50%; border: 5px solid #0ECB81; position: relative; animation: scale
.3s ease-in-out; }
.checkmark { display: block; width: 50px; height: 25px;
border-bottom: 5px solid #0ECB81; border-left: 5px solid #0ECB81; transform: rotate(-45deg); position: absolute; top: 30px; left: 25px;
animation: checkmark-anim 0.4s ease-in-out; }
@keyframes checkmark-anim { 0% { width: 0; height: 0; } 100% {
width: 50px; height: 25px; } }
@keyframes scale { 0% { transform: scale(0); } 100% { transform:
scale(1); } }
.stButton button { border-radius: 12px !important; font-weight:
bold !important; height: 45px !important; }
div[data-testid="stNumberInput"] input { height: 45px !important;
text-align: center !important; font-weight: 700 !important; }
</style>
'''
st.markdown(STYLE_BLOCK, unsafe_allow_html=True)
# ==========================================
# 2. 资源复用与底层数据获取
# ==========================================
@st.cache_resource
def get_session():
session = requests.Session()
session.mount('https://',
requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10))
return session
@st.cache_resource
def get_executor():
return ThreadPoolExecutor(max_workers=5)
def get_beijing_time():
return datetime.utcnow() + timedelta(hours=8)
def fetch_json(url, timeout=1.5):
try:
res = get_session().get(url, timeout=timeout)
if res.status_code == 200:
return res.json()
logger.warning(f"HTTP {res.status_code} from {url}")
except Exception as e:
logger.debug(f"Fetch error {url}: {str(e)}")
return None
def fetch_price_binance(symbol):
data =
fetch_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbo
l}")
return (float(data['price']), "Binance") if data and
data.get('price') else None def fetch_price_gate(symbol):
data =
fetch_json(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={
symbol.replace('USDT', '_USDT')}")
return (float(data[0]['last']), "Gate") if data and
isinstance(data, list) and data[0].get('last') else None
           def fetch_price_okx(symbol):
data =
fetch_json(f"https://www.okx.com/api/v5/market/ticker?instId={symbol.r
eplace('USDT', '-USDT')}")
rows = (data or {}).get("data", [])
return (float(rows[0]['last']), "OKX") if rows and
rows[0].get('last') else None
def get_median_price(price_rows):
if not price_rows: return None
prices = sorted([r[0] for r in price_rows])
n = len(prices)
if n == 1: return prices[0]
return prices[n // 2] if n % 2 == 1 else (prices[n // 2 - 1] +
prices[n // 2]) / 2
def get_price(symbol):
providers = [fetch_price_binance, fetch_price_gate,
fetch_price_okx]
price_rows = []
futures = [get_executor().submit(fn, symbol) for fn in providers]
for future in as_completed(futures):
try:
row = future.result()
if row: price_rows.append(row)
except Exception as e:
logger.warning(f"Price fetch task failed: {str(e)}")
if price_rows:
median_price = get_median_price(price_rows)
src = min(price_rows, key=lambda x: abs(x[0] -
median_price))[1]
spread = ((max([p[0] for p in price_rows]) - min([p[0] for p
in price_rows])) / median_price * 100) if len(price_rows) > 1 else 0.0
st.session_state.last_price_meta = {"source": src, "nodes":
len(price_rows), "spread_pct": spread, "time":
get_beijing_time().strftime('%H:%M:%S')}
st.session_state.price_cache[symbol] = median_price
return median_price
return st.session_state.price_cache.get(symbol) def normalize_df(df):
if df.empty: return df
for c in ['open', 'high', 'low', 'close']: df[c] =
pd.to_numeric(df[c], errors='coerce')
return df.dropna(subset=['time', 'open', 'high', 'low',
'close']).sort_values('time').tail(100).reset_index(drop=True)
def fetch_klines_binance(symbol, interval='1m'):
data =
fetch_json(f"https://api.binance.com/api/v3/klines?symbol={symbol}&int
erval={interval}&limit=100", timeout=2.0)
if not data or not isinstance(data, list): return pd.DataFrame(),
None
df = pd.DataFrame(data).iloc[:, :6]
df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
df['time'] = pd.to_datetime(df['time'], unit='ms') +
timedelta(hours=8)
return normalize_df(df), "Binance"
def fetch_klines_gate(symbol, interval='1m'):
data =
fetch_json(f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_p
air={symbol.replace('USDT', '_USDT')}&interval={interval}&limit=100",
timeout=2.0)
if not data or not isinstance(data, list): return pd.DataFrame(),
None
df = pd.DataFrame(data).iloc[:, [0, 5, 3, 4, 2, 1]]
df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') +
timedelta(hours=8)
return normalize_df(df), "Gate"
def fetch_klines_okx(symbol, interval='1m'):
bar = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m":
"30m", "1h": "1H"}.get(interval, "1m")
data =
fetch_json(f"https://www.okx.com/api/v5/market/candles?instId={symbol.
replace('USDT', '-USDT')}&bar={bar}&limit=100", timeout=2.0)
rows = (data or {}).get("data", [])
if not rows: return pd.DataFrame(), None
df = pd.DataFrame(rows).iloc[:, :6]
df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
df['time'] = pd.to_datetime(df['time'].astype('int64'), unit='ms')
+ timedelta(hours=8)
return normalize_df(df), "OKX"
def get_klines_smart_source(symbol, interval='1m'): providers = [fetch_klines_binance, fetch_klines_gate,
fetch_klines_okx]
rows = []
futures = [get_executor().submit(fn, symbol, interval) for fn in
providers]
for future in as_completed(futures):
try:
df, source = future.result()
if not df.empty: rows.append((df, source))
except Exception as e:
logger.warning(f"Kline fetch failed: {str(e)}")
if rows:
best_df, best_source = max(rows, key=lambda x:
(x[0]['time'].iloc[-1], len(x[0])))
st.session_state.last_kline_meta = {"source": best_source,
"nodes": len(rows), "time": get_beijing_time().strftime('%H:%M:%S')}
return best_df
return pd.DataFrame()
# ==========================================
# 3. 原子化数据持久层
# ==========================================
def load_db():
if os.path.exists(DB_FILE):
try:
with open(DB_FILE, "r", encoding="utf-8") as f:
data = json.load(f)
orders = data.get('orders', [])
for od in orders:
for key in ['结算时间', '开仓时间']:
if od.get(key) and isinstance(od[key], str):
od[key] = datetime.strptime(od[key],
'%Y-%m-%d %H:%M:%S')
return data.get('balance', 1000.0), orders
except Exception as e:
logger.error(f"DB load error: {e}")
return 1000.0, []
return 1000.0, []
def save_db(balance, orders):
ser = []
for od in orders:
tmp = od.copy()
for key in ['结算时间', '开仓时间']:
if tmp.get(key) and isinstance(tmp[key], datetime):
tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
ser.append(tmp) tmp_file = f"{DB_FILE}.tmp"
try:
with open(tmp_file, "w", encoding="utf-8") as f:
json.dump({"balance": balance, "orders": ser}, f)
os.replace(tmp_file, DB_FILE)
except Exception as e:
logger.error(f"Atomic save failed: {e}")
# ==========================================
# 4. 指标与 K 线增量引擎
# ==========================================
def sync_bet_from_input():
st.session_state.bet = max(10.0,
float(st.session_state.bet_input))
def step_bet(delta):
base = float(st.session_state.get('bet_input',
st.session_state.bet))
nxt = max(10.0, base + delta)
st.session_state.bet_input = nxt
st.session_state.bet = nxt
def get_bucket_time(interval, now=None):
now = now or get_beijing_time()
step = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
"1h": 3600}.get(interval, 60)
return pd.to_datetime(int(now.timestamp() // step * step),
unit='s')
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
now_ts = time.time()
bucket_time = get_bucket_time(interval) runtime = st.session_state.kline_runtime.setdefault(cache_key, {
'last_sync_ts': 0.0, 'history_df': pd.DataFrame(),
'active_candle': None,
'active_bucket': None, 'indicator_df': pd.DataFrame(),
'indicator_sig': None,
})
# 低频校验远端数据
if (now_ts - runtime['last_sync_ts']) >= 10:
fresh_df = get_klines_smart_source(symbol, interval)
if not fresh_df.empty:
runtime['history_df'] = fresh_df[fresh_df['time'] <
bucket_time].copy().tail(119).reset_index(drop=True)
bucket_df = fresh_df[fresh_df['time'] == bucket_time]
if not bucket_df.empty:
row = bucket_df.iloc[-1]
runtime['active_candle'] = {'time': row['time'],
'open': float(row['open']), 'high': float(row['high']), 'low':
float(row['low']), 'close': float(row['close']), 'vol':
float(row.get('vol', 0) or 0)}
elif not runtime['history_df'].empty:
px = float(runtime['history_df']['close'].iloc[-1])
runtime['active_candle'] = {'time': bucket_time,
'open': px, 'high': px, 'low': px, 'close': px, 'vol': 0.0}
runtime['active_bucket'] = bucket_time
runtime['last_sync_ts'] = now_ts
active = runtime['active_candle']
if active is None:
hist = runtime['history_df']
if hist.empty: return pd.DataFrame(), pd.DataFrame(), None
px = float(hist['close'].iloc[-1])
active = {'time': bucket_time, 'open': px, 'high': px, 'low':
px, 'close': px, 'vol': 0.0}
runtime['active_candle'] = active
runtime['active_bucket'] = bucket_time
# 周期跨越推进
if runtime['active_bucket'] is not None and bucket_time >
runtime['active_bucket']:
old_row = pd.DataFrame([runtime['active_candle']])
runtime['history_df'] = pd.concat([runtime['history_df'],
old_row], ignore_index=True).tail(120).reset_index(drop=True)
new_open = float(runtime['active_candle']['close'])
seed = curr_p if curr_p is not None else new_open
runtime['active_candle'] = {'time': bucket_time, 'open':
new_open, 'high': max(new_open, float(seed)), 'low': min(new_open,
float(seed)), 'close': float(seed), 'vol': 0.0} runtime['active_bucket'] = bucket_time
# 实时闭包更新
if curr_p is not None:
runtime['active_candle']['close'] = float(curr_p)
runtime['active_candle']['high'] =
max(float(runtime['active_candle']['high']), float(curr_p))
runtime['active_candle']['low'] =
min(float(runtime['active_candle']['low']), float(curr_p))
history_df = runtime['history_df'].copy()
sig = (len(history_df), str(history_df['time'].iloc[-1]) if not
history_df.empty else '-')
if sig != runtime['indicator_sig']:
runtime['indicator_df'] =
build_incremental_indicators(history_df)
runtime['indicator_sig'] = sig
return pd.concat([history_df,
pd.DataFrame([runtime['active_candle']])], ignore_index=True),
runtime['indicator_df'].copy(), runtime['active_candle'].copy()
# ==========================================
# 5. 状态机与前端渲染
# ==========================================
if 'balance' not in st.session_state: st.session_state.balance,
st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'bet_input' not in st.session_state: st.session_state.bet_input =
st.session_state.bet
if 'price_cache' not in st.session_state: st.session_state.price_cache
= {}
if 'kline_runtime' not in st.session_state:
st.session_state.kline_runtime = {}
if 'last_price_meta' not in st.session_state:
st.session_state.last_price_meta = {"source": "-", "nodes": 0,
"spread_pct": 0.0, "time": "-"}
if 'last_kline_meta' not in st.session_state:
st.session_state.last_kline_meta = {"source": "-", "nodes": 0, "time":
"-"}
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval =
"1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5
if 'show_success' not in st.session_state:
st.session_state.show_success = False @st.fragment
def chart_fragment():
# 动态调配刷新率：短周期高频，长周期降载
refresh_ms = 1500 if st.session_state.interval in ["1m", "3m"]
else 3000
st_autorefresh(interval=refresh_ms, key="chart_refresh")
now = get_beijing_time()
curr_p = get_price(st.session_state.coin)
c1, c2 = st.columns(2)
c1.markdown(f'<div class="data-card balance-border"><div
class="card-label">可用余额</div><div
class="card-value">${st.session_state.balance:,.2f}</div></div>',
unsafe_allow_html=True)
c2.markdown(f'<div class="data-card"><div
class="card-label">{st.session_state.coin} 现价</div><div
class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>',
unsafe_allow_html=True)
st.caption(f"价格源: {st.session_state.last_price_meta['source']} |
节点: {st.session_state.last_price_meta['nodes']}/3 | 偏差:
{st.session_state.last_price_meta['spread_pct']:.4f}% | K线源:
{st.session_state.last_kline_meta['source']}({st.session_state.last_kl
ine_meta['nodes']}/3)")
if st.session_state.mode == "TradingView":
tv_i = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m":
"30", "1h": "60"}.get(st.session_state.interval, "1")
tv_html = f'<div style="height:450px;"><div id="tv"
style="height:450px;"></div><script
src="https://s3.tradingview.com/tv.js"></script><script>new
TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_sta
te.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh
_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basi
cstudies"]}});</script></div>'
components.html(tv_html, height=450)
else:
import plotly.graph_objects as go
from plotly.subplots import make_subplots
df_k, indicator_df, active_candle =
get_live_klines_incremental(st.session_state.coin,
st.session_state.interval, curr_p)
if not df_k.empty:
fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
vertical_spacing=0.03, row_heights=[0.7, 0.3])
if not indicator_df.empty:
fig.add_trace(go.Scatter(x=indicator_df['time'],
y=indicator_df['up'], line=dict(color='rgba(41, 98, 255, 0.2)',
width=1)), row=1, col=1) fig.add_trace(go.Scatter(x=indicator_df['time'],
y=indicator_df['dn'], line=dict(color='rgba(41, 98, 255, 0.2)',
width=1), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.03)'), row=1,
col=1)
fig.add_trace(go.Scatter(x=indicator_df['time'],
y=indicator_df['ma'], line=dict(color='#FFB11B', width=1)), row=1,
col=1)
colors = ['#0ECB81' if v >= 0 else '#F6465D' for v in
indicator_df['hist']]
fig.add_trace(go.Bar(x=indicator_df['time'],
y=indicator_df['hist'], marker_color=colors), row=2, col=1)
fig.add_trace(go.Scatter(x=indicator_df['time'],
y=indicator_df['dif'], line=dict(color='#2962FF', width=1)), row=2,
col=1)
fig.add_trace(go.Scatter(x=indicator_df['time'],
y=indicator_df['dea'], line=dict(color='#FF6D00', width=1)), row=2,
col=1)
fig.add_trace(go.Candlestick(x=df_k['time'],
open=df_k['open'], high=df_k['high'], low=df_k['low'],
close=df_k['close'], increasing_fillcolor='#0ECB81',
decreasing_fillcolor='#F6465D'), row=1, col=1)
if active_candle is not None:
fig.add_vline(x=active_candle['time'], line_width=1,
line_dash='dot', line_color='rgba(132,142,156,0.35)', row=1, col=1)
for o in st.session_state.orders:
if o['状态'] == "待结算" and o['资产'] ==
st.session_state.coin:
color = "#0ECB81" if o['方向'] == "看涨" else
"#F6465D"
rem_sec = int((o['结算时间'] - now).total_seconds())
if rem_sec > 0:
fig.add_hline(y=o['开仓价'], line_dash="dash",
line_color=color, line_width=1, row=1, col=1)
fig.add_annotation(x=df_k['time'].iloc[-1],
y=o['开仓价'], text=f"{'↑' if o['方向']=='看涨' else '↓'} {rem_sec}s",
showarrow=False, font=dict(size=9, color=color), bgcolor="white",
opacity=0.8, row=1, col=1)
fig.update_layout(height=450, margin=dict(t=10, b=10, l=0,
r=0), xaxis_rangeslider_visible=False, plot_bgcolor='white',
showlegend=False,
uirevision=f"{st.session_state.coin}_{st.session_state.interval}",
transition=dict(duration=0))
st.plotly_chart(fig, use_container_width=True,
config={'displayModeBar': False}, key="native_kline_chart") @st.fragment
def order_flow_fragment():
st_autorefresh(interval=1500, key="flow_refresh")
now = get_beijing_time()
upd = False
for od in st.session_state.orders:
if od['状态'] == "待结算" and now >= od['结算时间']:
p_final = get_price(od['资产'])
if p_final:
od['平仓价'] = p_final
win = (
    (od['方向']=="看涨" and od['平仓价'] > od['开仓价'])
    or
    (od['方向']=="看跌" and od['平仓价'] < od['开仓价'])
)
st.session_state.balance += (od['金额'] * 1.8) if win
else 0
od['状态'] = "已结算"
od['结果'] = "W" if win else "L"
upd = True
if upd:
save_db(st.session_state.balance, st.session_state.orders)
all_s = [o for o in st.session_state.orders if o['状态']=="已结算"]
today_s = [o for o in all_s if o['结算时间'].date() == now.date()]
total_p = sum([(o['金额']*0.8 if o['结果']=="W" else -o['金额']) for
o in all_s])
total_wr = (len([o for o in all_s if o['结果']=="W"]) / len(all_s)
* 100) if all_s else 0
today_p = sum([(o['金额']*0.8 if o['结果']=="W" else -o['金额']) for
o in today_s])
today_wr = (len([o for o in today_s if o['结果']=="W"]) /
len(today_s) * 100) if today_s else 0
st.markdown("---")
st.markdown(f'<div class="stats-container"><div
class="stat-item"><div class="stat-label">今日盈亏</div><div
class="stat-val" style="color:{"#0ecb81" if today_p>=0 else
"#f6465d"}">{today_p:+.2f}</div></div><div class="stat-item"><div
class="stat-label">今日胜率</div><div
class="stat-val">{today_wr:.1f}%</div></div><div
class="stat-item"><div class="stat-label">总计盈亏</div><div
class="stat-val" style="color:{"#0ecb81" if total_p>=0 else
"#f6465d"}">{total_p:+.2f}</div></div><div class="stat-item"><div
class="stat-label">总计胜率</div><div
class="stat-val">{total_wr:.1f}%</div></div></div>',
unsafe_allow_html=True)
for o in reversed(st.session_state.orders[-10:]): if o['状态'] == "待结算":
ts = (o['结算时间'] - o['开仓时间']).total_seconds()
ps = (now - o['开仓时间']).total_seconds()
pct = min(100, max(0, int((ps/ts)*100))) if ts > 0 else
100
bg = f"background: linear-gradient(90deg, rgba(252, 213,
53, 0.12) {pct}%, white {pct}%);"
res_txt, p_color, p_val, close_d = f"正在结算 {100-pct}%",
"#222", "0.00", "---"
else:
win = o.get('结果') == "W"
bg = f"background: {'rgba(14, 203, 129, 0.08)' if win else
'rgba(246, 70, 93, 0.08)'};"
res_txt = "已平仓"
p_val = f"{o['金额']*0.8 if win else -o['金额']:+.2f}"
p_color, close_d = ("#0ecb81" if win else "#f6465d"),
(f"{o['平仓价']:,.2f}" if o.get('平仓价') else "---")
st.markdown(f'<div class="order-card-container"
style="{bg}"><div class="order-progress-bg"><div
class="order-header"><div class="symbol-info"><span
style="color:{"#0ecb81" if o["方向"]=="看涨" else "#f6465d"}">{"↗" if
o["方向"]=="看涨" else "↘"} {o["资产"]}</span><span
style="font-size:0.7rem; color:#848e9c;
margin-left:10px;">{res_txt}</span></div><div style="font-weight:800;
color:{p_color}">{p_val} USDT</div></div><div class="order-grid"><div
class="grid-item"><span class="grid-label">金额</span><span
class="grid-val">${o["金额"]}</span></div><div class="grid-item"><span
class="grid-label">开仓价</span><span class="grid-val">{o["开仓价
"]:,.2f}</span></div><div class="grid-item"><span class="grid-label">平
仓价</span><span
class="grid-val">{close_d}</span></div></div></div></div>',
unsafe_allow_html=True)
# ==========================================
# 6. 交互响应区
# ==========================================
if st.session_state.show_success:
st.markdown('<div class="success-overlay"><div
class="checkmark-circle"><div class="checkmark"></div></div><h2
style="color:#0ECB81; margin-top:20px;">下单成功</h2></div>',
unsafe_allow_html=True)
time.sleep(1.0)
st.session_state.show_success = False
st.rerun()
t1, t2, t3 = st.columns(3)
new_mode = t1.selectbox("图表源", ["原生 K 线", "TradingView"], index=0 if st.session_state.mode=="原生 K 线" else 1)
if new_mode != st.session_state.mode:
st.session_state.mode = new_mode
st.rerun()
st.session_state.coin = t2.selectbox("交易币对", ["BTCUSDT", "ETHUSDT",
"SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0, key="coin_select")
st.session_state.dur = t3.selectbox("结算周期", [5, 10, 30, 60],
format_func=lambda x: f"{x} 分钟", key="dur_select")
ints = ["1m", "3m", "5m", "15m", "30m", "1h"]
cols = st.columns(len(ints))
for i, n in enumerate(ints):
if cols[i].button(n, use_container_width=True, type="primary" if
st.session_state.interval==n else "secondary"):
st.session_state.interval = n
st.rerun()
chart_fragment()
st.markdown("<br>", unsafe_allow_html=True)
o1, o2 = st.columns(2)
def buy(dir):
p = get_price(st.session_state.coin)
if st.session_state.balance >= st.session_state.bet and p:
st.session_state.balance -= st.session_state.bet
st.session_state.orders.append({"资产": st.session_state.coin,
"方向": dir, "开仓价": p, "金额": st.session_state.bet, "开仓时间":
get_beijing_time(), "结算时间": get_beijing_time() +
timedelta(minutes=st.session_state.dur), "状态": "待结算", "平仓价":
None})
save_db(st.session_state.balance, st.session_state.orders)
st.session_state.show_success = True
st.rerun()
if o1.button("🟢 买涨 (UP)", use_container_width=True): buy("看涨")
if o2.button("🔴 买跌 (DOWN)", use_container_width=True): buy("看跌")
a1, a2, a3 = st.columns([1,2,1])
a1.button("➖", use_container_width=True, key="bet_minus_btn",
on_click=step_bet, args=(-10.0,))
amt_val = a2.number_input("AMT", min_value=10.0, step=10.0,
key="bet_input", on_change=sync_bet_from_input,
label_visibility="collapsed")
st.session_state.bet = max(10.0, float(amt_val))
a3.button("➕", use_container_width=True, key="bet_plus_btn",
on_click=step_bet, args=(10.0,)) order_flow_fragment()
with st.sidebar:
st.markdown("<br>"*20, unsafe_allow_html=True)
if st.checkbox("⚙️ 系统重置"
pwd = st.text_input("授权码", type="password")
if pwd:
pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
if pwd_hash == AUTH_HASH and st.button("🔴 确认清空"):
st.session_state.balance = 1000.0
st.session_state.orders = []
save_db(1000.0, [])
st.rerun()
elif pwd_hash != AUTH_HASH:
st.error("授权码错误")
