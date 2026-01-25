import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境检测与 Plotly 导入 ---
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==========================================
# 基础配置 & 深度视觉定制
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    /* 下单按钮美化：上涨绿，下跌红 */
    div[data-testid="column"]:nth-of-type(1) button {
        background: #0ECB81 !important; color: white !important; font-weight: bold !important; 
        height: 60px !important; border-radius: 12px !important; border: none !important; font-size: 20px !important;
    }
    div[data-testid="column"]:nth-of-type(2) button {
        background: #F6465D !important; color: white !important; font-weight: bold !important; 
        height: 60px !important; border-radius: 12px !important; border: none !important; font-size: 20px !important;
    }
    
    /* 动态对勾动画 CSS */
    @keyframes scaleIn { 0% { transform: scale(0); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        animation: scaleIn 0.3s ease-out;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; display: block; stroke-width: 2; stroke: #0ECB81; stroke-miterlimit: 10; box-shadow: inset 0px 0px 0px #0ECB81; animation: fill .4s ease-in-out .4s forwards, scale .3s ease-in-out .9s both; }
    .checkmark__circle { stroke-dasharray: 166; stroke-dashoffset: 166; stroke-width: 2; stroke-miterlimit: 10; stroke: #0ECB81; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }
    .checkmark__check { transform-origin: 50% 50%; stroke-dasharray: 48; stroke-dashoffset: 48; animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.8s forwards; }
    @keyframes stroke { 100% { stroke-dashoffset: 0; } }
    @keyframes fill { 100% { box-shadow: inset 0px 0px 0px 80px #0ECB81; } }
</style>
""", unsafe_allow_html=True)

# --- 工具函数 ---
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except: return None

def get_klines_smart_source(symbol, interval='1m'):
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

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 侧边栏控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制中心")
    chart_mode = st.radio("数据源", ["原生 K 线", "TradingView"], index=0)
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    k_interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=0)
    duration = st.radio("期权结算周期", [5, 10, 30], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)

# ==========================================
# 局部刷新主界面
# ==========================================
@st.fragment
def live_ui():
    st_autorefresh(interval=3000, key="live_refresh")
    curr_p = get_price(coin)
    now_time = get_beijing_time()

    # 1. 自动结算
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_p
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'] = "已结算"
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    st.subheader(f"💰 可用余额: ${st.session_state.balance:,.2f} | {coin} 现价: {curr_p or '---'}")

    # 2. 图表显示
    if chart_mode == "TradingView":
        tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df_k = get_klines_smart_source(coin, k_interval)
        if not df_k.empty:
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']
            df_k['dn'] = df_k['ma'] - 2*df_k['std']

            fig = make_subplots(rows=1, cols=1)
            # 纯色 K 线
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', increasing_line_color='#0ECB81', decreasing_fillcolor='#F6465D', decreasing_line_color='#F6465D'))
            # 布林带加粗
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(31,119,180,0.3)', width=2)))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(227,119,194,0.3)', width=2)))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3))) # 中轨金色加粗

            # 3. 实时开仓虚线 (加上箭头)
            for od in st.session_state.orders:
                if od['状态'] == "待结算" and od['资产'] == coin:
                    l_color = "#0ECB81" if od['方向']=="看涨" else "#F6465D"
                    arrow = "▲" if od['方向']=="看涨" else "▼"
                    fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=l_color, line_width=2, 
                                  annotation_text=f"{od['方向']} {arrow}", annotation_position="right", annotation_font_color=l_color)

            fig.update_layout(height=400, margin=dict(t=5,b=5,l=0,r=0), xaxis_rangeslider_visible=False, plot_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 4. 下单按钮
    b1, b2 = st.columns(2)
    if b1.button("买涨 (UP)", use_container_width=True):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=duration), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    if b2.button("买跌 (DOWN)", use_container_width=True):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=duration), "状态": "待结算"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    # 5. 实时流水
    st.markdown("### 📋 交易流水")
    if st.session_state.orders:
        t_d = []
        for o in reversed(st.session_state.orders[-10:]):
            rem = (o['结算时间'] - now_time).total_seconds()
            t_d.append({
                "开仓时间": o['开仓时间'].strftime('%H:%M:%S'),
                "结算时间": o['结算时间'].strftime('%H:%M:%S'),
                "方向": "上涨 ↗️" if o['方向']=="看涨" else "下跌 ↘️",
                "开仓价": f"{o['开仓价']:,.2f}",
                "平仓价": f"{o['平仓价']:,.2f}" if o['平仓价'] else "---",
                "金额": f"${o['金额']}",
                "状态/倒计时": f"{int(max(0,rem))}s" if o['状态']=="待结算" else "已结算"
            })
        st.table(t_d)

# 动态对勾动画
if st.session_state.get('show_success'):
    st.markdown('<div class="success-overlay"><svg class="checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52"><circle class="checkmark__circle" cx="26" cy="26" r="25" fill="none"/><path class="checkmark__check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8"/></svg><h2 style="color: #0ECB81; margin-top: 20px;">开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

live_ui()
