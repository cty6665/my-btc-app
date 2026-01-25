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
# 1. 移动端基准布局 CSS
# ==========================================
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db_pro.json"

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; font-family: -apple-system, system-ui, sans-serif; }
    [data-testid="stHeader"] { display: none; }
    
    /* 导航栏 44px */
    .nav-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }

    /* 交易对区 60px */
    .pair-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 8px 16px; height: 60px; background: #FFFFFF; margin-top: 44px;
    }
    .pair-name { font-size: 24px; font-weight: 700; color: #000000; }
    .odds-group { display: flex; gap: 12px; }
    .odd-up { font-size: 16px; font-weight: 600; color: #00B578; }
    .odd-down { font-size: 16px; font-weight: 600; color: #FF3141; }

    /* 控制栏 40px */
    .info-bar { background: #F5F5F7; padding: 0 16px; height: 40px; display: flex; align-items: center; font-size: 14px; color: #8E8E93; }

    /* 技术指标 40px */
    .indicator-bar { background: #F5F5F7; padding: 4px 16px; font-size: 10px; color: #8E8E93; border-top: 1px solid #E5E5EA; }

    /* 下单行布局 */
    .trade-row { display: flex; justify-content: space-between; align-items: center; height: 50px; border-bottom: 1px solid #F5F5F7; padding: 0 16px; }
    .trade-label { font-size: 16px; color: #000000; }
    .trade-val-group { text-align: right; }

    /* 操作按钮 */
    .stButton button { width: 100% !important; height: 44px !important; border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important; color: #FFFFFF !important; border: none !important; }
    div[data-testid="column"]:nth-of-type(1) button { background-color: #00B578 !important; }
    div[data-testid="column"]:nth-of-type(2) button { background-color: #FF3141 !important; }

    /* 订单列表 */
    .order-item { padding: 12px 16px; border-bottom: 1px solid #F5F5F7; }
    .order-row-1 { display: flex; justify-content: space-between; align-items: center; }
    .coin-tag { display: flex; align-items: center; gap: 4px; font-size: 16px; font-weight: 600; }
    .order-info { font-size: 12px; color: #8E8E93; margin-top: 4px; }
    
    /* 成功动画 */
    .success-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.9); z-index: 9999; display: flex; flex-direction: column; align-items: center; justify-content: center; }
    .checkmark { width: 80px; height: 80px; border-radius: 50%; stroke-width: 2; stroke: #0ECB81; box-shadow: inset 0px 0px 0px #0ECB81; animation: fill .4s ease-in-out .4s forwards; }
    @keyframes fill { 100% { box-shadow: inset 0px 0px 0px 80px #0ECB81; } }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# ==========================================
# 2. 接口备份逻辑
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_market_data(symbol):
    urls = [
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=80",
        f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={symbol.replace('USDT','_USDT')}&interval=1m&limit=80"
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=1.5).json()
            if 'binance' in url:
                df = pd.DataFrame(res).iloc[:, :6]
                df.columns = ['time','open','high','low','close','vol']
                df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            else:
                df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
                df.columns = ['time','open','high','low','close','vol']
                df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, float(df['close'].iloc[-1])
        except: continue
    return pd.DataFrame(), None

# ==========================================
# 3. 数据库与结算
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE): return 1000.0, []
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f); orders = data.get('orders', [])
            for od in orders:
                for key in ['开仓时间', '结算时间']:
                    if od.get(key): od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
            return data.get('balance', 1000.0), orders
    except: return 1000.0, []

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
# 4. 主程序
# ==========================================
@st.fragment
def main_app():
    st_autorefresh(interval=2000, key="global_refresh")
    now_time = get_beijing_time()
    coin = "ETHUSDT"
    
    # 顶部赔率区
    st.markdown(f"""
    <div class="pair-header">
        <div class="pair-name">{coin}</div>
        <div class="odds-group">
            <span class="odd-up">上涨：80%!</span>
            <span class="odd-down">下跌：80%!</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 获取行情
    df_k, curr_p = get_market_data(coin)
    
    # 结算逻辑
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_p; od['状态'] = "已平仓"
                win = (od['方向']=="上涨" and od['平仓价']>od['开仓价']) or (od['方向']=="下跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 图表控制栏
    st.markdown(f'<div class="info-bar">指数价格 <span style="margin-left:8px; color:#000; font-weight:600;">{curr_p or "---"}</span></div>', unsafe_allow_html=True)

    # 原生 K 线图
    if not df_k.empty:
        df_k['ma'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_line_color='#00B578', decreasing_line_color='#FF3141', increasing_fillcolor='#00B578', decreasing_fillcolor='#FF3141'))
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=3), hoverinfo='skip'))
        
        # 实时虚线与箭头
        for od in st.session_state.orders:
            if od['状态'] == "待结算":
                c = "#00B578" if od['方向']=="上涨" else "#FF3141"
                fig.add_hline(y=od['开仓价'], line_dash="dash", line_color=c, line_width=2, annotation_text="▲" if od['方向']=="上涨" else "▼", annotation_position="right", annotation_font_color=c)

        fig.update_layout(height=266, margin=dict(t=0,b=0,l=0,r=0), xaxis_rangeslider_visible=False, plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
        fig.update_yaxes(side="right", gridcolor="#F5F5F7")
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        
        # 技术指标显示区
        st.markdown(f"""
        <div class="indicator-bar">
            BOLL:(20,2) UP:{df_k['up'].iloc[-1]:.2f} MB:{df_k['ma'].iloc[-1]:.2f} DN:{df_k['dn'].iloc[-1]:.2f}<br>
            周期：10分钟 | 30分钟 | 1小时 | 1天
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error("行情接口同步中...")

    # 交易输入与账户信息
    bet = st.number_input("数量(USDT)", 10.0, 5000.0, 100.0, key="bet_input")
    st.markdown(f"""
    <div class="trade-row"><span class="trade-label">支付率</span><div class="trade-val-group"><span style="color:#00B578; font-weight:600;">80%!</span><br><small style="color:#8E8E93;">{bet*0.8:.1f} USDT</small></div></div>
    <div class="trade-row"><span class="trade-label">可用余额</span><span style="font-weight:600;">{st.session_state.balance:,.2f} USDT</span></div>
    """, unsafe_allow_html=True)

    # 按钮区
    st.write("")
    b1, b2 = st.columns(2)
    if b1.button("上涨"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"方向": "上涨", "开仓价": curr_p, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算", "支付率": "80%!"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()
    if b2.button("下跌"):
        if st.session_state.balance >= bet and curr_p:
            st.session_state.balance -= bet
            st.session_state.orders.append({"方向": "下跌", "开仓价": curr_p, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=5), "状态": "待结算", "支付率": "80%!"})
            save_db(st.session_state.balance, st.session_state.orders); st.session_state.show_success = True; st.rerun()

    # 历史列表
    st.write("")
    t_open, t_closed = st.tabs([f"已开仓({len([o for o in st.session_state.orders if o['状态']=='待结算'])})", "已平仓(20+)"])
    
    with t_open:
        for o in reversed([o for o in st.session_state.orders if o['状态'] == "待结算"]):
            cd = int((o['结算时间'] - now_time).total_seconds())
            arrow = '<span style="color:#00B578;">▲</span>' if o['方向']=="上涨" else '<span style="color:#FF3141;">▼</span>'
            st.markdown(f"""
            <div class="order-item">
                <div class="order-row-1"><div class="coin-tag">{coin}{arrow}</div><span style="color:#8E8E93; font-size:14px;">数量 {o['金额']}</span></div>
                <div class="order-info">开仓价 {o['开仓价']:.2f} | 开仓时间 {o['开仓时间'].strftime('%H:%M:%S')}</div>
                <div class="order-info" style="color:#FFB11B;">倒计时: {max(0, cd)}s | 支付率 {o.get('支付率','80%!')}</div>
            </div>
            """, unsafe_allow_html=True)

    with t_closed:
        for o in reversed([o for o in st.session_state.orders if o['状态'] == "已平仓"]):
            arrow = '<span style="color:#00B578;">▲</span>' if o['方向']=="上涨" else '<span style="color:#FF3141;">▼</span>'
            st.markdown(f"""
            <div class="order-item">
                <div class="order-row-1"><div class="coin-tag">{coin}{arrow}</div><span style="color:#8E8E93;">已平仓</span></div>
                <div class="order-info">价格: {o['开仓价']:.2f} → {o['平仓价']:.2f}</div>
                <div class="order-info">时间: {o['开仓时间'].strftime('%H:%M:%S')} → {o['结算时间'].strftime('%H:%M:%S')}</div>
                <div class="order-info" style="color:#00B578;">支付率 {o.get('支付率','80%!')} | 收益已结算</div>
            </div>
            """, unsafe_allow_html=True)

# 成功动画
if st.session_state.get('show_success'):
    st.markdown('<div class="success-overlay"><div class="checkmark"></div><h2 style="color:#0ECB81; margin-top:20px;">开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2); st.session_state.show_success = False; st.rerun()

main_app()
