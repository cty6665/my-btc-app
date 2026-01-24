import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境检测 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置 & 深度定制 CSS (适配手机与现代 UI)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    /* 基础背景 */
    .stApp { background-color: #fcfcfc; }
    
    /* 现代感卡片样式 */
    .data-card {
        background: #ffffff;
        padding: 18px;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        border-top: 4px solid #FCD535;
        margin-bottom: 10px;
        text-align: center;
    }
    .card-label { color: #848e9c; font-size: 0.85rem; margin-bottom: 5px; font-weight: 500; }
    .card-value { color: #1e2329; font-size: 1.8rem; font-weight: 800; font-family: 'Roboto', sans-serif; }
    
    /* 余额卡片特定颜色 */
    .balance-border { border-top: 4px solid #0ECB81; }
    
    /* 手机端表格横向滚动适配 (解决拥挤) */
    @media (max-width: 640px) {
        .stTable {
            display: block !important;
            overflow-x: auto !important;
            white-space: nowrap !important;
        }
        .card-value { font-size: 1.4rem !important; } /* 手机端数字稍微收敛 */
    }

    /* 按钮样式锁定 */
    .stButton button { 
        background: #FCD535 !important; 
        color: #000 !important; 
        font-weight: bold !important; 
        height: 55px !important; 
        border-radius: 12px !important; 
        border: none !important; 
        transition: transform 0.1s;
    }
    .stButton button:active { transform: scale(0.98); }
</style>
""", unsafe_allow_html=True)

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# ==========================================
# 核心逻辑 (多源 API & 周期切换 - 保持不变)
# ==========================================
def get_klines_smart_source(symbol, interval='1m'):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=80"
        res = requests.get(url, timeout=3, headers=headers).json()
        if isinstance(res, list) and len(res) > 0:
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Gate.io"
    except: pass
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=80"
        res = requests.get(url, timeout=2).json()
        if isinstance(res, list):
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Binance"
    except: pass
    return pd.DataFrame(), None

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

# --- 数据库管理 ---
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
    serialized = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 侧边栏 (锁定功能)
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    chart_mode = st.radio("数据源", ["原生 K 线", "TradingView"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    k_interval = st.selectbox("K线周期", ["1m", "3m", "5m", "15m", "30m", "1h"], index=0)
    duration = st.radio("期权周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("金额", 10.0, 5000.0, 100.0)
    if st.button("🚨 重置"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

# ==========================================
# 局部刷新区 (Fragment)
# ==========================================
@st.fragment
def live_ui():
    st_autorefresh(interval=3000, key="live_refresh")
    curr_p = get_price(coin)
    now_time = get_beijing_time()

    # 1. 自动结算
    if curr_p:
        updated = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                cp_final = get_price(od['资产'])
                if cp_final:
                    od['平仓价'] = cp_final
                    win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                    st.session_state.balance += (od['金额'] * 1.8) if win else 0
                    od['收益'] = (od['金额'] * 0.8) if win else -od['金额']
                    od['状态'], od['结果'] = "已结算", "W" if win else "L"
                    updated = True
        if updated: save_db(st.session_state.balance, st.session_state.orders)

    # 2. 【重点优化】顶栏彩色卡片数据展示
    h1, h2 = st.columns(2)
    h1.markdown(f"""
        <div class="data-card balance-border">
            <div class="card-label">账户可用余额 (USDT)</div>
            <div class="card-value">${st.session_state.balance:,.2f}</div>
        </div>
    """, unsafe_allow_html=True)
    
    h2.markdown(f"""
        <div class="data-card">
            <div class="card-label">{coin} 实时现价</div>
            <div class="card-value">${curr_p:,.2f if curr_p else 0}</div>
        </div>
    """, unsafe_allow_html=True)

    # 3. K 线展示 (保留金中轨视觉)
    if chart_mode == "TradingView":
        tv_interval = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:500px;"><div id="tv" style="height:500px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_interval}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=500)
    else:
        df_k, src = get_klines_smart_source(coin, k_interval)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(41, 98, 255, 0.3)', width=0.8), showlegend=False))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(41, 98, 255, 0.3)', width=0.8), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.08)', showlegend=False))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1.5), showlegend=False))
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', increasing_line_color='#0ECB81', decreasing_fillcolor='#F6465D', decreasing_line_color='#F6465D'))
            fig.update_layout(height=500, margin=dict(t=10,b=10,l=0,r=0), xaxis_rangeslider_visible=False, dragmode='pan', plot_bgcolor='white', paper_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
        else: st.error("K 线同步中...")

live_ui()

# ==========================================
# 交易操作 & 流水 (表格适配)
# ==========================================
now_static = get_beijing_time()
curr_p_static = get_price(coin)

b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and curr_p_static:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": curr_p_static, "平仓价": None, "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders); st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and curr_p_static:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": curr_p_static, "平仓价": None, "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders); st.rerun()

st.markdown("---")
# 统计板块
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
t_pnl = sum(o['收益'] for o in settled if o['开仓时间'].date() == now_static.date())
m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")
m3.metric("总盈亏", f"${sum(o['收益'] for o in settled):.1f}")
m4.metric("总胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")

st.subheader("📋 交易流水")
if not st.session_state.orders:
    st.info("💡 请开启你的第一笔交易，开启盈利之旅！")
else:
    table_data = []
    for o in reversed(st.session_state.orders[-15:]):
        rem = (o['结算时间'] - now_static).total_seconds()
        table_data.append({
            "币种": o['资产'].replace("USDT", ""),
            "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
            "金额": f"${o['金额']}",
            "开仓价": f"{o['开仓价']:,.2f}",
            "平仓价": f"{o['平仓价']:,.2f}" if o['平仓价'] else "---",
            "开仓": o['开仓时间'].strftime('%H:%M:%S'),
            "结算": o['结算时间'].strftime('%H:%M:%S'),
            "结果": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
        })
    # 这里的 st.table 已经通过 CSS 注入了横向滚动逻辑
    st.table(table_data)
