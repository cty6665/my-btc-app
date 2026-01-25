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

# ==========================================
# 1. 视觉与动画复原
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db_v2.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    /* 强行固定下单按钮颜色 */
    div[data-testid="column"]:nth-of-type(1) button {
        background-color: #00B578 !important; color: white !important; height: 55px !important; font-weight: bold !important; font-size: 18px !important; border: none !important;
    }
    div[data-testid="column"]:nth-of-type(2) button {
        background-color: #FF3141 !important; color: white !important; height: 55px !important; font-weight: bold !important; font-size: 18px !important; border: none !important;
    }
    /* 动态对勾动画 */
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; stroke: #0ECB81; stroke-width: 2; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }
    @keyframes stroke { 100% { stroke-dashoffset: 0; } }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 数据获取 (多源容错)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_data(symbol, interval):
    # 优先币安
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df, df['close'].iloc[-1]
    except:
        return pd.DataFrame(), None

# --- 数据库加载 ---
if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 3. 核心 UI
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端设置")
    chart_mode = st.radio("图表源", ["原生 K 线", "TradingView"])
    coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=1)
    k_interval = st.pills("周期选择", ["1m", "5m", "15m", "1h", "1d"], default="1m")
    bet_amount = st.number_input("下单金额", 10.0, 5000.0, 100.0)

@st.fragment
def main_app():
    st_autorefresh(interval=3000, key="auto_refresh")
    now_time = get_beijing_time()
    
    # 顶栏
    st.markdown(f"### {coin} | 余额: ${st.session_state.balance:,.2f}")
    
    df, curr_p = get_data(coin, k_interval)

    # 图表区
    if chart_mode == "TradingView":
        tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:400px;"><div id="tv" style="height:400px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=400)
    else:
        if not df.empty:
            # 布林带计算
            df['ma'] = df['close'].rolling(20).mean()
            df['std'] = df['close'].rolling(20).std()
            df['up'] = df['ma'] + 2*df['std']
            df['dn'] = df['ma'] - 2*df['std']
            
            # 指标栏
            last = df.iloc[-1]
            st.markdown(f"<small style='color:#8E8E93;'>BOLL(20,2) UP:{last['up']:.2f} MB:{last['ma']:.2f} DN:{last['dn']:.2f}</small>", unsafe_allow_html=True)
            
            fig = go.Figure()
            # 完整布林带
            fig.add_trace(go.Scatter(x=df['time'], y=df['up'], line=dict(color='rgba(173,216,230,0.4)', width=1), hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=df['time'], y=df['dn'], line=dict(color='rgba(173,216,230,0.4)', width=1), fill='tonexty', fillcolor='rgba(173,216,230,0.05)', hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=df['time'], y=df['ma'], line=dict(color='#FFB11B', width=2), name='中轨(金)'))
            
            # 纯色 K 线
            fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], increasing_line_color='#00B578', decreasing_line_color='#FF3141'))
            
            # 实时虚线箭头
            for o in st.session_state.orders:
                if o.get('状态') == "待结算":
                    c = "#00B578" if o['方向'] == "上涨" else "#FF3141"
                    fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=c, annotation_text="▲" if o['方向']=="上涨" else "▼")

            fig.update_layout(height=380, margin=dict(t=5,b=5,l=0,r=0), xaxis_rangeslider_visible=False, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 下单区
    st.write("---")
    c1, c2 = st.columns(2)
    if c1.button(f"上涨 ▲", use_container_width=True):
        if st.session_state.balance >= bet_amount and curr_p:
            st.session_state.balance -= bet_amount
            st.session_state.orders.append({"资产":coin, "方向":"上涨", "开仓价":curr_p, "金额":bet_amount, "开仓时间":now_time, "结算时间":now_time+timedelta(minutes=5), "状态":"待结算"})
            st.session_state.show_success = True; st.rerun()

    if c2.button(f"下跌 ▼", use_container_width=True):
        if st.session_state.balance >= bet_amount and curr_p:
            st.session_state.balance -= bet_amount
            st.session_state.orders.append({"资产":coin, "方向":"下跌", "开仓价":curr_p, "金额":bet_amount, "开仓时间":now_time, "结算时间":now_time+timedelta(minutes=5), "状态":"待结算"})
            st.session_state.show_success = True; st.rerun()

    # 历史流水
    t1, t2 = st.tabs(["进行中", "已平仓"])
    with t1:
        active = [o for o in st.session_state.orders if o['状态'] == "待结算"]
        for o in reversed(active):
            cd = int((o['结算时间'] - now_time).total_seconds())
            st.info(f"【{o['方向']}】开仓:{o['开仓价']} | 倒计时:{max(0, cd)}s")
            if cd <= 0: # 简易结算逻辑
                o['状态'] = "已结算"; o['平仓价'] = curr_p; st.rerun()

    with t2:
        closed = [o for o in st.session_state.orders if o['状态'] == "已结算"]
        if closed:
            df_hist = pd.DataFrame(closed).tail(10)
            st.table(df_hist[['开仓时间','结算时间','开仓价','平仓价','方向','金额']])

# 成功动画
if st.session_state.get('show_success'):
    st.markdown('<div class="success-overlay"><div class="checkmark"></div><h2 style="color:#0ECB81;">开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

main_app()
