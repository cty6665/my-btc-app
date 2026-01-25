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

# ==========================================
# 1. UI 规格定义
# ==========================================
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db_pro.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    .nav-bar { position: fixed; top: 0; left: 0; width: 100%; height: 44px; background: #FFFFFF; border-bottom: 1px solid #E5E5EA; display: flex; align-items: center; justify-content: center; z-index: 1000; }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }
    /* 按钮样式重写，确保必现 */
    .stButton button { width: 100% !important; height: 50px !important; border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important; color: white !important; }
    div[data-testid="column"]:nth-of-type(1) button { background-color: #00B578 !important; }
    div[data-testid="column"]:nth-of-type(2) button { background-color: #FF3141 !important; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
<div style="height: 44px;"></div>
""", unsafe_allow_html=True)

# ==========================================
# 2. 数据与逻辑
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_market_data(symbol, interval='1m'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df, float(df['close'].iloc[-1])
    except: return pd.DataFrame(), None

# 数据库加载略（保持之前逻辑）
if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 3. 主界面布局
# ==========================================
@st.fragment
def main_app():
    st_autorefresh(interval=3000, key="refresh")
    now_time = get_beijing_time()
    
    # 顶部：交易对与模式切换
    col_t1, col_t2 = st.columns([2, 1])
    with col_t1: 
        st.markdown('<h1 style="margin:0;">ETHUSDT</h1>', unsafe_allow_html=True)
    with col_t2:
        chart_type = st.segmented_control("图表类型", ["原生", "TV"], default="原生", label_visibility="collapsed")
    
    # 周期选择（可按动）
    interval = st.pills("周期", ["1m", "5m", "15m", "1h", "4h", "1d"], default="1m", label_visibility="collapsed")

    df_k, curr_p = get_market_data("ETHUSDT", interval)

    if chart_type == "TV":
        tv_i = "1" if interval == "1m" else interval.replace("m", "")
        tv_html = f"""<div style="height:400px;"><div id="tv" style="height:400px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:ETHUSDT","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=400)
    else:
        if not df_k.empty:
            # 真实计算布林带
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2 * df_k['std']
            df_k['dn'] = df_k['ma'] - 2 * df_k['std']
            
            last = df_k.iloc[-1]
            st.markdown(f"""<div style="background:#F5F5F7; padding:5px 15px; font-size:12px; color:#8E8E93;">
                <b>指数价格:</b> {curr_p} | <b>BOLL(20,2)</b> UP:{last['up']:.2f} MB:{last['ma']:.2f} DN:{last['dn']:.2f}
            </div>""", unsafe_allow_html=True)

            fig = go.Figure()
            # 完整布林带：三根线
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(173,216,230,0.6)', width=1), name='上轨'))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(173,216,230,0.6)', width=1), name='下轨', fill='tonexty', fillcolor='rgba(173,216,230,0.05)'))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=2), name='中轨'))
            
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], 
                                         increasing_line_color='#00B578', decreasing_line_color='#FF3141'))
            
            # 开仓虚线
            for o in st.session_state.orders:
                if o.get('状态') == "待结算":
                    color = "#00B578" if o['方向'] == "上涨" else "#FF3141"
                    fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=color, annotation_text="▲" if o['方向']=="上涨" else "▼")

            fig.update_layout(height=400, margin=dict(t=0,b=0,l=0,r=0), xaxis_rangeslider_visible=False, paper_bgcolor='white', plot_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 下单区：保证必现
    st.markdown(f"<div style='text-align:right; padding:10px;'>可用余额: <b>{st.session_state.balance:.2f} USDT</b></div>", unsafe_allow_html=True)
    bet = st.number_input("下单金额", 10.0, 1000.0, 100.0, label_visibility="collapsed")
    
    col_btn1, col_btn2 = st.columns(2)
    if col_btn1.button("上涨 ▲"):
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"方向":"上涨", "开仓价":curr_p, "金额":bet, "结算时间": now_time+timedelta(minutes=5), "状态":"待结算", "开仓时间":now_time})
            st.rerun()
            
    if col_btn2.button("下跌 ▼"):
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"方向":"下跌", "开仓价":curr_p, "金额":bet, "结算时间": now_time+timedelta(minutes=5), "状态":"待结算", "开仓时间":now_time})
            st.rerun()

    # 订单列表
    st.divider()
    t1, t2 = st.tabs(["已开仓", "已平仓"])
    with t1:
        for o in [x for x in st.session_state.orders if x['状态']=="待结算"]:
            st.write(f"方向: {o['方向']} | 开仓: {o['开仓价']} | 倒计时: {int((o['结算时间']-now_time).total_seconds())}s")

main_app()
