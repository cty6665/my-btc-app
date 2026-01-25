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
# 1. 屏幕基准样式与 CSS 深度定制
# ==========================================
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db_pro.json"

st.markdown("""
<style>
    /* 全局背景与字体 */
    .stApp { background-color: #FFFFFF; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    [data-testid="stHeader"] { display: none; }
    
    /* 1. 导航栏 */
    .nav-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }

    /* 2. 交易对赔率区 */
    .pair-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 8px 16px; height: 60px; background: #FFFFFF; margin-top: 44px;
    }
    .pair-name { font-size: 24px; font-weight: 700; color: #000000; }
    .odds-group { display: flex; gap: 12px; }
    .odd-up { font-size: 16px; font-weight: 600; color: #00B578; }
    .odd-down { font-size: 16px; font-weight: 600; color: #FF3141; }

    /* 3. 控制栏与指标 */
    .info-bar { background: #F5F5F7; padding: 4px 16px; font-size: 10px; color: #8E8E93; line-height: 1.4; }

    /* 4. 按钮定制 */
    div[data-testid="stHorizontalBlock"] > div:nth-child(1) button {
        background-color: #00B578 !important; color: #FFFFFF !important; height: 44px !important;
        border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important; border: none !important;
    }
    div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
        background-color: #FF3141 !important; color: #FFFFFF !important; height: 44px !important;
        border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important; border: none !important;
    }

    /* 5. 订单列表项 */
    .order-item { padding: 12px 16px; border-bottom: 1px solid #F5F5F7; background: #FFFFFF; }
    .order-row-1 { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
    .order-coin { font-size: 16px; font-weight: 600; color: #000000; display: flex; align-items: center; gap: 4px; }
    .order-meta { font-size: 12px; color: #8E8E93; margin-top: 2px; }

    /* 6. 成功动画 */
    @keyframes fill { 100% { box-shadow: inset 0px 0px 0px 80px #0ECB81; } }
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; display: block; stroke-width: 2; stroke: #0ECB81; animation: fill .4s ease-in-out .4s forwards; }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# ==========================================
# 2. 强力多接口 K 线获取逻辑
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_market_data(symbol, interval='1m'):
    # 接口 A: Binance
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=1.5).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df, float(df['close'].iloc[-1])
    except:
        # 接口 B: Gate.io 备份
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100"
            res = requests.get(url, timeout=1.5).json()
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, float(df['close'].iloc[-1])
        except:
            return pd.DataFrame(), None

# ==========================================
# 3. 数据库逻辑
# ==========================================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f); orders = data.get('orders', [])
                for od in orders:
                    for key in ['开仓时间', '结算时间']:
                        if od.get(key): od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['开仓时间', '结算时间']:
            if isinstance(tmp.get(key), datetime): tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 4. 主 UI 渲染 (Fragment 局部刷新)
# ==========================================
@st.fragment
def main_app():
    st_autorefresh(interval=2000, key="refresh")
    now_time = get_beijing_time()
    
    # --- 2. 交易对与赔率区 ---
    st.markdown(f"""
    <div class="pair-header">
        <div class="pair-name">ETHUSDT</div>
        <div class="odds-group">
            <span class="odd-up">上涨：80%!</span>
            <span class="odd-down">下跌：80%!</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- 3. 获取数据 & 结算逻辑 ---
    df_k, curr_price = get_market_data("ETHUSDT")
    
    if curr_price:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_price
                win = (od['方向']=="上涨" and od['平仓价']>od['开仓价']) or (od['方向']=="下跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'] = "已平仓"
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # --- 4. 原生 K 线渲染 ---
    if not df_k.empty:
        # 技术指标计算
        df_k['ma'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'] = df_k['ma'] + 2*df_k['std']
        df_k['dn'] = df_k['ma'] - 2*df_k['std']
        
        # 指标文本栏
        last = df_k.iloc[-1]
        st.markdown(f"""
        <div class="info-bar">
            BOLL:(20,2) UP:{last['up']:.2f} MB:{last['ma']:.2f} DN:{last['dn']:.2f}<br>
            指数价格: {curr_price:.2f}
        </div>
        """, unsafe_allow_html=True)

        fig = go.Figure()
        # 蜡烛图
        fig.add_trace(go.Candlestick(
            x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
            increasing_line_color='#00B578', decreasing_line_color='#FF3141',
            increasing_fillcolor='#00B578', decreasing_fillcolor='#FF3141'
        ))
        # 布林带中轨加粗金色
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3), hoverinfo='skip'))
        
        # 实时订单虚线功能
        for od in st.session_state.orders:
            if od['状态'] == "待结算":
                color = "#00B578" if od['方向']=="上涨" else "#FF3141"
                icon = "▲" if od['方向']=="上涨" else "▼"
                fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=color, line_width=2,
                              annotation_text=f"{od['方向']} {icon}", annotation_position="right", annotation_font_color=color)

        fig.update_layout(height=300, margin=dict(t=0,b=0,l=0,r=0), xaxis_rangeslider_visible=False, 
                          plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
        fig.update_yaxes(side="right", gridcolor="#E5E5EA")
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    else:
        st.error("原生K线数据获取中，请检查网络接口...")

    # --- 5. 交易输入区 ---
    st.markdown('<div style="padding: 12px 16px; border-bottom: 1px solid #F5F5F7;">', unsafe_allow_html=True)
    c_in1, c_in2 = st.columns([1, 1])
    with c_in1: st.write("**数量(USDT)**")
    with c_in2: bet = st.number_input("bet", 10.0, 5000.0, 100.0, label_visibility="collapsed")
    st.markdown(f'<div style="text-align:right; font-size:12px; color:#8E8E93; margin-top:-10px;">可用 {st.session_state.balance:,.2f} USDT</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # --- 6. 核心操作按钮 ---
    st.markdown('<div style="padding: 12px 16px;">', unsafe_allow_html=True)
    b_col1, b_col2 = st.columns(2)
    if b_col1.button("上涨"):
        if st.session_state.balance >= bet and curr_price:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": "ETHUSDT", "方向": "上涨", "开仓价": curr_price, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算", "支付率": "80%!"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    if b_col2.button("下跌"):
        if st.session_state.balance >= bet and curr_price:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": "ETHUSDT", "方向": "下跌", "开仓价": curr_price, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算", "支付率": "80%!"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # --- 7. 历史订单列表 ---
    tab1, tab2 = st.tabs(["已开仓", "已平仓(20+)"])
    
    with tab1:
        active_orders = [o for o in st.session_state.orders if o['状态'] == "待结算"]
        for o in reversed(active_orders):
            cd = int((o['结算时间'] - now_time).total_seconds())
            st.markdown(f"""
            <div class="order-item">
                <div class="order-row-1">
                    <span class="order-coin">ETHUSDT <small style="color:{'#00B578' if o['方向']=='上涨' else '#FF3141'}">{'▲' if o['方向']=='上涨' else '▼'}</small></span>
                    <span style="font-size:14px; color:#8E8E93;">数量(USDT) {o['金额']}</span>
                </div>
                <div class="order-meta">开仓价 {o['开仓价']:.2f} | 开仓时间 {o['开仓时间'].strftime('%H:%M:%S')}</div>
                <div class="order-meta" style="color:#00B578;">结算倒计时: {max(0, cd)}s | 支付率 {o['支付率']}</div>
            </div>
            """, unsafe_allow_html=True)

    with tab2:
        closed_orders = [o for o in st.session_state.orders if o['状态'] == "已平仓"]
        for o in reversed(closed_orders[-20:]):
            st.markdown(f"""
            <div class="order-item">
                <div class="order-row-1">
                    <span class="order-coin">ETHUSDT</span>
                    <span style="font-size:14px; color:#8E8E93;">已平仓</span>
                </div>
                <div class="order-meta">开仓: {o['开仓价']:.2f} -> 平仓: {o['平仓价']:.2f}</div>
                <div class="order-meta">时间: {o['开仓时间'].strftime('%m-%d %H:%M')} 至 {o['结算时间'].strftime('%H:%M')}</div>
                <div class="order-meta" style="color:#00B578;">收益已结算 | 支付率 {o['支付率']}</div>
            </div>
            """, unsafe_allow_html=True)

# --- 成功动画逻辑 ---
if st.session_state.get('show_success'):
    st.markdown("""
        <div class="success-overlay">
            <div class="checkmark"></div>
            <h2 style="color: #0ECB81; margin-top: 20px;">开仓成功</h2>
        </div>
    """, unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

main_app()
