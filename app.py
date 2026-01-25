import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境检测 & Plotly 配置 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置 & 深度视觉定制 (含全背景进度条样式)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    [data-testid="collapsedControl"] { display: none; }
    
    .data-card {
        background: #ffffff; padding: 12px; border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-top: 4px solid #FCD535;
        text-align: center; margin-bottom: 8px;
    }
    .balance-border { border-top: 4px solid #0ECB81; }
    .card-label { color: #848e9c; font-size: 0.8rem; }
    .card-value { color: #1e2329; font-size: 1.4rem; font-weight: 800; }

    /* 核心：订单卡片进度背景 */
    .order-card-container {
        position: relative;
        background: white;
        border-radius: 10px;
        margin-bottom: 12px;
        border: 1px solid #eee;
        overflow: hidden; /* 确保进度背景不溢出 */
        transition: all 0.3s;
    }
    
    /* 进度层：利用 linear-gradient 实现 */
    .order-progress-bg {
        padding: 15px;
        width: 100%;
        height: 100%;
    }

    .order-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; position: relative; z-index: 2; }
    .symbol-info { font-weight: 800; font-size: 1.1rem; display: flex; align-items: center; }
    .order-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; position: relative; z-index: 2; }
    .grid-item { display: flex; flex-direction: column; }
    .grid-label { color: #848e9c; font-size: 0.7rem; }
    .grid-val { color: #1e2329; font-size: 0.85rem; font-weight: 600; margin-top: 2px; }

    /* 下单按钮 */
    .stButton button { border-radius: 12px !important; font-weight: bold !important; height: 50px !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 强化版多接口 K 线函数 (原样保留多接口逻辑)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

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

def get_klines_smart_source(symbol, interval='1m'):
    """保留 Gate.io 和 Binance 双重接口，确保图表显示"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    # 尝试接口 1: Gate.io
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100"
        res = requests.get(url, timeout=3, headers=headers).json()
        df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df, "Gate.io"
    except:
        # 尝试接口 2: Binance
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
            res = requests.get(url, timeout=2).json()
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Binance"
        except: return pd.DataFrame(), None

# --- 数据库读写 ---
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

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval = "1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5

# ==========================================
# 页面 UI 逻辑
# ==========================================
@st.fragment
def live_ui():
    st_autorefresh(interval=3000, key="main_loop")
    now_time = get_beijing_time()
    curr_p = get_price(st.session_state.coin)

    # --- 1. 顶部控制栏 ---
    t1, t2, t3 = st.columns(3)
    st.session_state.mode = t1.selectbox("图表源", ["原生 K 线", "TradingView"], index=0 if st.session_state.mode=="原生 K 线" else 1)
    st.session_state.coin = t2.selectbox("交易币对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], index=0)
    st.session_state.dur = t3.selectbox("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")

    # --- 2. 状态卡片 ---
    h1, h2 = st.columns(2)
    h1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    h2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    # --- 3. 周期切换条 ---
    ints = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
    btn_cols = st.columns(len(ints))
    for idx, name in enumerate(ints):
        if btn_cols[idx].button(name, use_container_width=True, type="primary" if st.session_state.interval == name else "secondary"):
            st.session_state.interval = name
            st.rerun()

    # --- 4. 核心图表区 ---
    if st.session_state.mode == "TradingView":
        tv_i = "1" if st.session_state.interval == "1m" else st.session_state.interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df_k, src = get_klines_smart_source(st.session_state.coin, st.session_state.interval)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            ema12 = df_k['close'].ewm(span=12).mean(); ema26 = df_k['close'].ewm(span=26).mean()
            df_k['macd'] = ema12 - ema26; df_k['sig'] = df_k['macd'].ewm(span=9).mean(); df_k['hist'] = df_k['macd'] - df_k['sig']

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
            # 主图 (中轨金色)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1.5), name='MID'), row=1, col=1)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'), row=1, col=1)
            
            # 副图 MACD (染色逻辑：水上绿，水下红)
            bar_colors = ['#0ECB81' if val >= 0 else '#F6465D' for val in df_k['hist']]
            fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], marker_color=bar_colors), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['macd'], line=dict(color='#2962FF', width=1)), row=2, col=1)

            fig.update_layout(height=400, margin=dict(t=5,b=5,l=0,r=0), xaxis_rangeslider_visible=False, plot_bgcolor='white', showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
        else:
            st.warning(f"⚠️ {st.session_state.coin} K线数据同步中，请稍后...")

    # --- 5. 操作区 ---
    st.markdown("<br>", unsafe_allow_html=True)
    o1, o2 = st.columns(2)
    if o1.button("🟢 买涨 (UP)", use_container_width=True):
        if st.session_state.balance >= st.session_state.bet and curr_p:
            st.session_state.balance -= st.session_state.bet
            st.session_state.orders.append({"资产": st.session_state.coin, "方向": "看涨", "开仓价": curr_p, "平仓价": None, "金额": st.session_state.bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=st.session_state.dur), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.rerun()

    if o2.button("🔴 买跌 (DOWN)", use_container_width=True):
        if st.session_state.balance >= st.session_state.bet and curr_p:
            st.session_state.balance -= st.session_state.bet
            st.session_state.orders.append({"资产": st.session_state.coin, "方向": "看跌", "开仓价": curr_p, "平仓价": None, "金额": st.session_state.bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=st.session_state.dur), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.rerun()

    # 下单金额控制器
    st.markdown("<div style='text-align:center; color:#848e9c; font-size:0.8rem;'>下单金额控制</div>", unsafe_allow_html=True)
    a1, a2, a3 = st.columns([1,2,1])
    if a1.button("➖", use_container_width=True): st.session_state.bet = max(10.0, st.session_state.bet - 10.0); st.rerun()
    st.session_state.bet = a2.number_input("AMT", value=st.session_state.bet, step=10.0, label_visibility="collapsed")
    if a3.button("➕", use_container_width=True): st.session_state.bet += 10.0; st.rerun()

    # --- 6. 自动化结算逻辑 (不可手动平仓) ---
    upd = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now_time >= od['结算时间']:
            p_final = get_price(od['资产'])
            if p_final:
                od['平仓价'] = p_final
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'] = "已结算"; od['结果'] = "W" if win else "L"
                upd = True
    if upd: save_db(st.session_state.balance, st.session_state.orders)

    # --- 7. 动态进度条流水卡片 ---
    st.markdown("---")
    st.subheader("📋 实时流水")
    for o in reversed(st.session_state.orders[-15:]):
        # 计算进度
        if o['状态'] == "待结算":
            total_sec = (o['结算时间'] - o['开仓时间']).total_seconds()
            past_sec = (now_time - o['开仓时间']).total_seconds()
            progress = min(100, max(0, int((past_sec / total_sec) * 100)))
            # 待结算背景：浅蓝色进度
            bg_style = f"background: linear-gradient(90deg, rgba(252, 213, 53, 0.15) {progress}%, white {progress}%);"
            res_val = f"结算中 {100-progress}%"
        else:
            # 已结算背景：根据输赢变色
            color = "rgba(14, 203, 129, 0.1)" if o.get('结果')=="W" else "rgba(246, 70, 93, 0.1)"
            bg_style = f"background: {color};"
            res_val = "已平仓"

        dir_color = "#0ecb81" if o['方向']=="看涨" else "#f6465d"
        dir_icon = "↗" if o['方向']=="看涨" else "↘"

        card_html = f"""
        <div class="order-card-container" style="{bg_style}">
            <div class="order-progress-bg">
                <div class="order-header">
                    <div class="symbol-info">
                        <span style="color:{dir_color}; margin-right:8px;">{dir_icon} {o['资产']}</span>
                        <span style="font-size:0.8rem; color:#848e9c;">{res_val}</span>
                    </div>
                    <div style="font-weight:800; color:{dir_color if o.get('结果')=='W' else '#222'}">
                        { '0.00 USDT' if o['状态']=='待结算' else (f"+{o['金额']*0.8:.2f}" if o['结果']=='W' else f"-{o['金额']:.2f}") }
                    </div>
                </div>
                <div class="order-grid">
                    <div class="grid-item"><span class="grid-label">数量(USDT)</span><span class="grid-val">{o['金额']}</span></div>
                    <div class="grid-item"><span class="grid-label">开仓价</span><span class="grid-val">{o['开仓价']:,.4f}</span></div>
                    <div class="grid-item"><span class="grid-label">开仓时间</span><span class="grid-val">{o['开仓时间'].strftime('%m-%d %H:%M:%S')}</span></div>
                    <div class="grid-item"><span class="grid-label">奖金支付率</span><span class="grid-val" style="color:#0ecb81">80%</span></div>
                    <div class="grid-item"><span class="grid-label">平仓价</span><span class="grid-val">{o['平仓价'] if o['平仓价'] else '---'}</span></div>
                    <div class="grid-item"><span class="grid-label">平仓时间</span><span class="grid-val">{o['结算时间'].strftime('%m-%d %H:%M:%S')}</span></div>
                </div>
            </div>
        </div>
        """
        st.markdown(card_html, unsafe_allow_html=True)

live_ui()
