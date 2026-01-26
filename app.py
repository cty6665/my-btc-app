import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 样式与配置 (保持原样)
# ==========================================
st.set_page_config(page_title="Binance Pro", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    [data-testid="stHorizontalBlock"] { align-items: center !important; }
    .data-card {
        background: #ffffff; padding: 12px; border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-top: 4px solid #FCD535;
        text-align: center; margin-bottom: 8px;
    }
    .balance-border { border-top: 4px solid #0ECB81; }
    .card-label { color: #848e9c; font-size: 0.8rem; }
    .card-value { color: #1e2329; font-size: 1.4rem; font-weight: 800; }
    .stats-container {
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
        background: #f8f9fa; padding: 15px; border-radius: 10px; margin-bottom: 15px;
    }
    .stat-item { text-align: center; border-right: 1px solid #eee; }
    .stat-item:last-child { border-right: none; }
    .stat-label { font-size: 0.75rem; color: #848e9c; }
    .stat-val { font-size: 1rem; font-weight: bold; margin-top: 4px; }
    .order-card-container {
        position: relative; background: white; border-radius: 10px;
        margin-bottom: 12px; border: 1px solid #eee; overflow: hidden;
    }
    .order-progress-bg { padding: 15px; width: 100%; height: 100%; position: relative; }
    .order-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; position: relative; z-index: 5; }
    .order-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; position: relative; z-index: 5; }
    .grid-label { color: #848e9c; font-size: 0.7rem; }
    .grid-val { color: #1e2329; font-size: 0.85rem; font-weight: 600; margin-top: 2px; }
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
# 2. 基础逻辑 (注入缓存优化防止卡顿)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

# 核心优化：增加 1 秒缓存，防止高频刷新撞墙
@st.cache_data(ttl=1)
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

# 核心优化：增加 2 秒缓存，防止 K 线图重绘过快导致的卡顿
@st.cache_data(ttl=2)
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

if 'balance' not in st.session_state: st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval = "1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5
if 'show_success' not in st.session_state: st.session_state.show_success = False

# ==========================================
# 3. 局部刷新组件 (逻辑保持原样)
# ==========================================
@st.fragment
def chart_fragment():
    st_autorefresh(interval=3000, key="chart_refresh")
    now = get_beijing_time()
    curr_p = get_price(st.session_state.coin)
    
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    if st.session_state.mode == "TradingView":
        tv_i = "1" if st.session_state.interval == "1m" else st.session_state.interval.replace("m", "")
        tv_html = f'<div style="height:450px;"><div id="tv" style="height:450px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>'
        components.html(tv_html, height=450)
    else:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        df_k = get_klines_smart_source(st.session_state.coin, st.session_state.interval)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean(); df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            ema12 = df_k['close'].ewm(span=12, adjust=False).mean(); ema26 = df_k['close'].ewm(span=26, adjust=False).mean()
            df_k['dif'] = ema12 - ema26; df_k['dea'] = df_k['dif'].ewm(span=9, adjust=False).mean(); df_k['hist'] = df_k['dif'] - df_k['dea']
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(41, 98, 255, 0.1)', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(41, 98, 255, 0.1)', width=1), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.03)') , row=1, col=1)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'), row=1, col=1)
            
            for o in st.session_state.orders:
                if o['状态'] == "待结算" and o['资产'] == st.session_state.coin:
                    color = "#0ECB81" if o['方向'] == "看涨" else "#F6465D"
                    rem_sec = int((o['结算时间'] - now).total_seconds())
                    if rem_sec > 0:
                        fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=color, line_width=1, row=1, col=1)
            fig.update_layout(height=450, margin=dict(t=10,b=10,l=0,r=0), xaxis_rangeslider_visible=False, plot_bgcolor='white', showlegend=False, uirevision=st.session_state.coin)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

@st.fragment
def order_flow_fragment():
    st_autorefresh(interval=1000, key="flow_refresh")
    now = get_beijing_time()
    
    # 自动结算逻辑 (保持不变)
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

    # 渲染界面
    for o in reversed(st.session_state.orders[-10:]):
        win = o.get('结果')=="W"; bg = f"background: {'rgba(14, 203, 129, 0.08)' if win else 'rgba(246, 70, 93, 0.08)'};"
        if o['状态'] == "待结算":
            bg = "background: white;"
            res_txt = "正在结算..."
            p_val = "0.00"
        else:
            res_txt = "已平仓"; p_val = f"{o['金额']*0.8 if win else -o['金额']:+.2f}"
            
        st.markdown(f"""<div class="order-card-container" style="{bg}"><div class="order-progress-bg"><div class="order-header">
        <div><span style="color:{'#0ecb81' if o['方向']=='看涨' else '#f6465d'}">{'涨' if o['方向']=='看涨' else '跌'} {o['资产']}</span></div>
        <div style="font-weight:800;">{p_val} USDT</div></div></div></div>""", unsafe_allow_html=True)

# ==========================================
# 4. 主程序运行
# ==========================================
if st.session_state.show_success:
    st.markdown('<div class="success-overlay"><div class="checkmark-circle"><div class="checkmark"></div></div><h2 style="color:#0ECB81; margin-top:20px;">下单成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

t1, t2, t3 = st.columns(3)
st.session_state.mode = t1.selectbox("图表源", ["原生 K 线", "TradingView"], index=0 if st.session_state.mode=="原生 K 线" else 1)
st.session_state.coin = t2.selectbox("交易币对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], key="coin_select")
st.session_state.dur = t3.selectbox("结算周期", [5, 10, 30], format_func=lambda x: f"{x} 分钟", key="dur_select")

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

a1, a2, a3 = st.columns([1,2,1])
if a1.button("➖", use_container_width=True): st.session_state.bet = max(10.0, st.session_state.bet - 10.0); st.rerun()
st.session_state.bet = a2.number_input("AMT", value=st.session_state.bet, step=10.0, label_visibility="collapsed")
if a3.button("➕", use_container_width=True): st.session_state.bet += 10.0; st.rerun()

order_flow_fragment()

with st.sidebar:
    st.markdown("<br>"*20, unsafe_allow_html=True)
    if st.checkbox("⚙️ 系统重置"):
        pwd = st.text_input("授权码", type="password")
        if pwd == "522087" and st.button("确认清空"):
            st.session_state.balance = 1000.0; st.session_state.orders = []; save_db(1000.0, []); st.rerun()
