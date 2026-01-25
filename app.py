import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 基础配置与样式 (极致精简) ---
st.set_page_config(page_title="事件合约终端", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    .nav-bar { position: fixed; top: 0; left: 0; width: 100%; height: 44px; background: #FFFFFF; border-bottom: 1px solid #E5E5EA; display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }
    div[data-testid="column"]:nth-of-type(1) button { background-color: #00B578 !important; color: white !important; height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important; }
    div[data-testid="column"]:nth-of-type(2) button { background-color: #FF3141 !important; color: white !important; height: 60px !important; font-size: 22px !important; font-weight: 900 !important; width: 100%; border: none !important; }
    .order-card { padding: 12px; border-bottom: 1px solid #F5F5F7; background: #FFF; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
<div style="height: 50px;"></div>
""", unsafe_allow_html=True)

# --- 2. 稳健数据接口 ---
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return None

def get_klines_all_sources(symbol, interval='1m'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=80"
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

# --- 3. UI 核心渲染 (带防崩保护) ---
@st.fragment
def main_app():
    try:
        st_autorefresh(interval=2000, key="global_refresh")
        now_time = get_beijing_time()

        # 1. 顶部控制器
        chart_mode = st.radio("模式", ["原生 K 线", "TradingView"], horizontal=True, label_visibility="collapsed")
        c1, c2 = st.columns([2, 1])
        with c1: coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0, label_visibility="collapsed")
        with c2: k_interval = st.selectbox("周期", ["1m", "5m", "15m", "1h"], index=0, label_visibility="collapsed")
        
        curr_p = get_price(coin)

        # 2. 自动结算
        if curr_p:
            upd = False
            for od in st.session_state.orders:
                if od['状态'] == "待结算" and now_time >= od['结算时间']:
                    od['平仓价'] = curr_p
                    win = (od['方向']=="上涨" and od['平仓价']>od['开仓价']) or (od['方向']=="下跌" and od['平仓价']<od['开仓价'])
                    st.session_state.balance += (od['金额'] * 1.8) if win else 0
                    od['状态'] = "已结算"
                    upd = True
            if upd: save_db(st.session_state.balance, st.session_state.orders)

        # 3. 图表渲染逻辑 (双重隔离)
        if chart_mode == "TradingView":
            tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
            tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
            components.html(tv_html, height=380)
        else:
            df_k = get_klines_all_sources(coin, k_interval)
            if not df_k.empty:
                df_k['ma'] = df_k['close'].rolling(20).mean()
                df_k['std'] = df_k['close'].rolling(20).std()
                df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
                fig = make_subplots(rows=1, cols=1)
                fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#00B578', increasing_line_color='#00B578', decreasing_fillcolor='#FF3141', decreasing_line_color='#FF3141'))
                fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3))) # 金色中轨加粗
                
                # 画实时虚线
                for od in st.session_state.orders:
                    if od['状态'] == "待结算" and od['资产'] == coin:
                        l_color = "#00B578" if od['方向']=="上涨" else "#FF3141"
                        fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=l_color, line_width=2, annotation_text=f"{od['方向']} {'▲' if od['方向']=='上涨' else '▼'}", annotation_position="right")

                fig.update_layout(height=400, margin=dict(t=10,b=10,l=0,r=0), xaxis_rangeslider_visible=False, paper_bgcolor='white', plot_bgcolor='white', showlegend=False)
                fig.update_yaxes(side="right", gridcolor="#F5F5F7")
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            else:
                st.info("📊 正在同步原生 K 线数据...")

        # 4. 下单区 (原生按钮，确保可点)
        st.markdown(f'<div style="text-align:right; font-size:14px; color:#8E8E93; margin-bottom:5px;">可用: <b>{st.session_state.balance:,.2f}</b> USDT</div>', unsafe_allow_html=True)
        bet = st.number_input("下单数量", 10.0, 5000.0, 100.0, label_visibility="collapsed")
        b1, b2 = st.columns(2)
        if b1.button("上涨 ▲"):
            if st.session_state.balance >= bet and curr_p:
                st.session_state.balance -= bet
                st.session_state.orders.append({"资产": coin, "方向": "上涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
                save_db(st.session_state.balance, st.session_state.orders); st.rerun()

        if b2.button("下跌 ▼"):
            if st.session_state.balance >= bet and curr_p:
                st.session_state.balance -= bet
                st.session_state.orders.append({"资产": coin, "方向": "下跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算"})
                save_db(st.session_state.balance, st.session_state.orders); st.rerun()

        # 5. 流水区 (带实时秒数倒计时)
        st.markdown('<div style="margin-top:20px; font-weight:700; border-bottom:2px solid #00B578; width:fit-content; padding-bottom:5px;">交易明细流水</div>', unsafe_allow_html=True)
        for o in reversed(st.session_state.orders[-10:]):
            color = "#00B578" if o['方向'] == "上涨" else "#FF3141"
            countdown = ""
            if o['状态'] == "待结算":
                diff = (o['结算时间'] - now_time).total_seconds()
                countdown = f'<span style="color:#FFB11B; font-weight:700;">结算中 {int(max(0, diff))}s</span>'
            else:
                countdown = '<span style="color:#8E8E93;">已结算</span>'

            st.markdown(f"""
            <div class="order-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-weight:700; color:{color}; font-size:16px;">{o['方向']} {o['资产']}</span>
                    {countdown}
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; font-size: 11px; color:#8E8E93; margin-top:6px;">
                    <div>开仓价: <b style="color:#000">{o['开仓价']:,.2f}</b></div>
                    <div>平仓价: <b style="color:#000">{o['平仓价'] or '---'}</b></div>
                    <div>开仓: {o['开仓时间'].strftime('%H:%M:%S')}</div>
                    <div>结算: {o['结算时间'].strftime('%H:%M:%S')}</div>
                    <div>数量: <b style="color:#000">${o['金额']}</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"⚠️ 系统组件加载中... (或刷新重试)")

# 启动
main_app()
