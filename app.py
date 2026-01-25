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
# 基础配置 & 深度视觉定制 (原样保留)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    .data-card {
        background: #ffffff; padding: 15px; border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-top: 4px solid #FCD535;
        text-align: center; margin-bottom: 8px;
    }
    .balance-border { border-top: 4px solid #0ECB81; }
    .card-label { color: #848e9c; font-size: 0.8rem; }
    .card-value { color: #1e2329; font-size: 1.5rem; font-weight: 800; }
    .stButton button { 
        background: #FCD535 !important; color: #000 !important; font-weight: bold !important; 
        height: 55px !important; border-radius: 12px !important; border: none !important; 
    }
    @media (max-width: 640px) {
        .stTable { display: block !important; overflow-x: auto !important; white-space: nowrap !important; }
        .card-value { font-size: 1.3rem !important; }
    }
    @keyframes scaleIn { 0% { transform: scale(0); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.8); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        animation: scaleIn 0.3s ease-out;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; display: block; stroke-width: 2; stroke: #0ECB81; stroke-miterlimit: 10; box-shadow: inset 0px 0px 0px #0ECB81; animation: fill .4s ease-in-out .4s forwards, scale .3s ease-in-out .9s both; }
    .checkmark__circle { stroke-dasharray: 166; stroke-dashoffset: 166; stroke-width: 2; stroke-miterlimit: 10; stroke: #0ECB81; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }
    .checkmark__check { transform-origin: 50% 50%; stroke-dasharray: 48; stroke-dashoffset: 48; animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.8s forwards; }
    @keyframes stroke { 100% { stroke-dashoffset: 0; } }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 工具函数 (原样保留)
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
    headers = {'User-Agent': 'Mozilla/5.0'}
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
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
            res = requests.get(url, timeout=2).json()
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Binance"
        except: return pd.DataFrame(), None

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

# ==========================================
# 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制中心")
    chart_mode = st.radio("数据源", ["原生 K 线", "TradingView"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    k_interval = st.selectbox("K线周期", ["1m", "3m", "5m", "15m", "30m", "1h"], index=0)
    duration = st.radio("期权结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)
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

    # 1. 自动结算 (原逻辑)
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                cp_f = get_price(od['资产'])
                if cp_f:
                    od['平仓价'] = cp_f
                    win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                    st.session_state.balance += (od['金额'] * 1.8) if win else 0
                    od['收益'] = (od['金额'] * 0.8) if win else -od['金额']
                    od['状态'], od['结果'] = "已结算", "W" if win else "L"
                    upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 2. 顶栏卡片
    h1, h2 = st.columns(2)
    h1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    d_p = curr_p if curr_p else 0.0
    h2.markdown(f'<div class="data-card"><div class="card-label">{coin} 实时现价</div><div class="card-value">${d_p:,.2f}</div></div>', unsafe_allow_html=True)

    # 3. K 线 (双指缩放/中轨金色/MACD)
    if chart_mode == "TradingView":
        tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df_k, src = get_klines_smart_source(coin, k_interval)
        if not df_k.empty:
            # 计算 BOLL
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            # 计算 MACD
            ema12 = df_k['close'].ewm(span=12, adjust=False).mean()
            ema26 = df_k['close'].ewm(span=26, adjust=False).mean()
            df_k['macd'] = ema12 - ema26
            df_k['sig'] = df_k['macd'].ewm(span=9, adjust=False).mean()
            df_k['hist'] = df_k['macd'] - df_k['sig']

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            
            # 主图
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='#1f77b4', width=2), name='上轨(蓝)'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='#e377c2', width=2), name='下轨(粉)'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=2), name='中轨(金)'), row=1, col=1) # 中轨金色
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', increasing_line_color='#0ECB81', decreasing_fillcolor='#F6465D', decreasing_line_color='#F6465D'), row=1, col=1)
            
            # 副图 MACD
            fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], marker_color='gray'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['macd'], line=dict(color='#2962FF', width=1)), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['sig'], line=dict(color='#FF6D00', width=1)), row=2, col=1)

            fig.update_layout(
                height=420, margin=dict(t=5,b=5,l=0,r=0), 
                xaxis_rangeslider_visible=False, 
                dragmode='pan', 
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(fixedrange=False), yaxis=dict(fixedrange=False),
                showlegend=False
            )
            # 关键：注入 scrollZoom 和移动端支持
            st.plotly_chart(fig, use_container_width=True, config={
                'scrollZoom': True, 
                'displayModeBar': False,
                'doubleClick': 'reset',
                'showAxisDragHandles': True
            })
        else: st.error("K 线同步中...")

    # --- 下单区 (原样保留) ---
    st.markdown("<br>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    now_s = get_beijing_time()
    if b1.button("🟢 买涨 (UP)", use_container_width=True) and curr_p:
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_s, "结算时间": now_s+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            st.session_state.show_success = True; st.rerun()

    if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and curr_p:
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_s, "结算时间": now_s+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            st.session_state.show_success = True; st.rerun()

    # 流水
    st.markdown("---")
    st.subheader("📋 实时流水")
    if not st.session_state.orders:
        st.info("💡 请开启你的第一笔交易，开启盈利之旅！")
    else:
        t_d = []
        for o in reversed(st.session_state.orders[-10:]):
            rem = (o['结算时间'] - now_time).total_seconds()
            t_d.append({
                "币种": o['资产'].replace("USDT",""), "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
                "金额": f"${o['金额']}", "开仓价": f"{o['开仓价']:,.2f}", "平仓价": f"{o['平仓价']:,.2f}" if o['平仓价'] else "---",
                "结果/倒计时": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
            })
        st.table(t_d)

# 成功动画 (原样保留)
if 'show_success' not in st.session_state: st.session_state.show_success = False
if st.session_state.show_success:
    st.markdown('<div class="success-overlay"><svg class="checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52"><circle class="checkmark__circle" cx="26" cy="26" r="25" fill="none"/><path class="checkmark__check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8"/></svg><h2 style="color: #0ECB81; margin-top: 20px;">开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

live_ui()
