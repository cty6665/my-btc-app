import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 环境检测 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 1. 整体参数 & UI 样式规范 (严格遵循描述)
# ==========================================
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown(f"""
<style>
    /* 全局重置 */
    .stApp {{ background-color: #FFFFFF; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    [data-testid="stHeader"] {{ display: none; }}
    
    /* 1. 导航栏 */
    .nav-bar {{
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 1000;
    }}
    .nav-title {{ font-size: 18px; font-weight: 700; color: #000000; }}

    /* 2. 交易对显示区 */
    .symbol-header {{
        margin-top: 44px; padding: 8px 16px; height: 60px;
        display: flex; justify-content: space-between; align-items: center;
    }}
    .symbol-name {{ font-size: 24px; font-weight: 700; color: #000000; }}
    .odds-group {{ display: flex; gap: 12px; }}
    .odds-up {{ font-size: 16px; font-weight: 600; color: #00B578; }}
    .odds-down {{ font-size: 16px; font-weight: 600; color: #FF3141; }}

    /* 3. 图表控制栏 */
    .chart-ctrl {{ background: #F5F5F7; height: 40px; display: flex; align-items: center; padding: 0 16px; gap: 12px; }}
    .index-label {{ font-size: 14px; color: #8E8E93; }}

    /* 4. 交易输入区 */
    .input-section {{ padding: 12px 16px; background: #FFFFFF; border-top: 1px solid #F5F5F7; }}
    .input-row {{ display: flex; justify-content: space-between; align-items: center; height: 50px; border-bottom: 1px solid #F5F5F7; }}
    .label-main {{ font-size: 16px; color: #000000; }}
    .sub-label {{ font-size: 12px; color: #8E8E93; text-align: right; }}
    
    /* 5. 核心操作按钮 */
    .btn-container {{ display: flex; gap: 12px; padding: 16px; background: #FFFFFF; }}
    .action-btn {{ 
        height: 44px; border-radius: 8px; font-size: 18px; font-weight: 700; 
        color: #FFFFFF; display: flex; align-items: center; justify-content: center; flex: 1;
        text-decoration: none; border: none; cursor: pointer;
    }}
    .btn-up {{ background: #00B578; }}
    .btn-down {{ background: #FF3141; }}

    /* 6. 订单列表区 */
    .order-tabs {{ display: flex; height: 40px; background: #F5F5F7; }}
    .tab-item {{ flex: 1; text-align: center; line-height: 40px; font-size: 16px; color: #8E8E93; }}
    .tab-active {{ background: #FFFFFF; color: #000000; border-bottom: 2px solid #00B578; }}
    
    .order-item {{ padding: 12px 16px; border-bottom: 1px solid #F5F5F7; }}
    .order-row-1 {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
    .order-symbol {{ font-size: 16px; font-weight: 600; color: #000000; }}
    .order-sub {{ font-size: 12px; color: #8E8E93; }}
    
    /* 强制手机端图表容器高度 */
    .js-plotly-plot {{ touch-action: none !important; }}
</style>

<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# ==========================================
# 2. 逻辑函数 (核心逻辑严格锁定，禁止变动)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return None

def get_klines(symbol, interval='1m'):
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
        with open(DB_FILE, "r") as f:
            d = json.load(f)
            orders = d.get('orders', [])
            for o in orders:
                for k in ['结算时间', '开仓时间']:
                    if o.get(k): o[k] = datetime.strptime(o[k], '%Y-%m-%d %H:%M:%S')
            return d.get('balance', 1000.0), orders
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for o in orders:
        tmp = o.copy()
        for k in ['结算时间', '开仓时间']:
            if isinstance(tmp.get(k), datetime): tmp[k] = tmp[k].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

# 初始化
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 3. UI 渲染区
# ==========================================
with st.sidebar:
    coin = st.selectbox("选择资产", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=1)
    k_interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=0)
    bet_amount = st.number_input("数量(USDT)", 10.0, 10000.0, 100.0)

@st.fragment
def main_ui():
    st_autorefresh(interval=3000, key="auto_upd")
    now_time = get_beijing_time()
    curr_p = get_price(coin)
    
    # 自动结算逻辑
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_p
                win = (od['方向']=="上涨" and od['平仓价']>od['开仓价']) or (od['方向']=="下跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'] = "已平仓"
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 2. 交易对显示区
    st.markdown(f"""
    <div class="symbol-header">
        <div class="symbol-name">{coin}</div>
        <div class="odds-group">
            <span class="odds-up">上涨：80%!</span>
            <span class="odds-down">下跌：80%!</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 3. 图表控制栏与图表
    st.markdown(f'<div class="chart-ctrl"><span class="index-label">指数价格</span></div>', unsafe_allow_html=True)
    
    df_k = get_klines(coin, k_interval)
    if not df_k.empty:
        # 指标计算
        df_k['ma'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'] = df_k['ma'] + 2*df_k['std']
        df_k['dn'] = df_k['ma'] - 2*df_k['std']
        
        # DIF/DEA/MACD (简易版)
        df_k['dif'] = df_k['close'].ewm(span=12).mean() - df_k['close'].ewm(span=26).mean()
        df_k['dea'] = df_k['dif'].ewm(span=9).mean()
        df_k['macd'] = (df_k['dif'] - df_k['dea']) * 2

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        # BOLL 线
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='#1f77b4', width=1.5), name='UP'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='#e377c2', width=1.5), name='DN'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1.5), name='MB'), row=1, col=1)
        # K线
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], 
                                     increasing_line_color='#00B578', decreasing_line_color='#FF3141'), row=1, col=1)
        # MACD
        fig.add_trace(go.Bar(x=df_k['time'], y=df_k['macd'], marker_color='#8E8E93'), row=2, col=1)

        fig.update_layout(height=350, margin=dict(t=5, b=5, l=0, r=0), xaxis_rangeslider_visible=False,
                          dragmode='pan', plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
        fig.update_xaxes(fixedrange=False)
        fig.update_yaxes(side="right", gridcolor="#E5E5EA", fixedrange=False)
        
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})

        # 3.3 指标文字
        last = df_k.iloc[-1]
        st.markdown(f"""
        <div class="chart-ctrl" style="height: auto; flex-direction: column; align-items: flex-start; padding: 4px 16px;">
            <div style="font-size: 10px; color: #8E8E93;">BOLL:(20,2) UP:{last['up']:.2f} MB:{last['ma']:.2f} DN:{last['dn']:.2f}</div>
            <div style="font-size: 10px; color: #8E8E93;">DIF:{last['dif']:.2f} DEA:{last['dea']:.2f} MACD:{last['macd']:.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    # 4. 交易输入区
    st.markdown(f"""
    <div class="input-section">
        <div class="input-row">
            <span class="label-main">数量(USDT)</span>
            <div>
                <div style="font-size: 16px; font-weight: 700;">{bet_amount}</div>
                <div class="sub-label">可用 {st.session_state.balance:.2f} USDT</div>
            </div>
        </div>
        <div class="input-row">
            <span class="label-main">支付率</span>
            <div>
                <span style="color: #00B578; font-weight: 600;">80%!</span>
                <div class="sub-label">0 USDT</div>
            </div>
        </div>
        <div class="input-row" style="border:none;">
            <span class="label-main">U本位合约</span>
            <span style="font-weight: 600;">{st.session_state.balance:.2f} USDT+</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5. 操作按钮
    c1, c2 = st.columns(2)
    if c1.button("上涨", use_container_width=True, type="primary"):
        if st.session_state.balance >= bet_amount:
            st.session_state.balance -= bet_amount
            st.session_state.orders.append({
                "资产": coin, "方向": "上涨", "金额": bet_amount, "开仓价": curr_p, 
                "开仓时间": now_time, "结算时间": now_time + timedelta(minutes=5), "状态": "待结算"
            })
            save_db(st.session_state.balance, st.session_state.orders); st.rerun()

    if c2.button("下跌", use_container_width=True):
        if st.session_state.balance >= bet_amount:
            st.session_state.balance -= bet_amount
            st.session_state.orders.append({
                "资产": coin, "方向": "下跌", "金额": bet_amount, "开仓价": curr_p, 
                "开仓时间": now_time, "结算时间": now_time + timedelta(minutes=5), "状态": "待结算"
            })
            save_db(st.session_state.balance, st.session_state.orders); st.rerun()

    # 6. 订单区
    active_count = len([o for o in st.session_state.orders if o['状态']=="待结算"])
    st.markdown(f"""
    <div class="order-tabs">
        <div class="tab-item tab-active">已开仓({active_count})</div>
        <div class="tab-item">已平仓(20+)</div>
    </div>
    """, unsafe_allow_html=True)

    for od in reversed(st.session_state.orders[-10:]):
        color = "#00B578" if od['方向']=="上涨" else "#FF3141"
        icon = "▲" if od['方向']=="上涨" else "▼"
        st.markdown(f"""
        <div class="order-item">
            <div class="order-row-1">
                <span class="order-symbol"><span style="color:{color}">{icon}</span> {od['资产']}</span>
                <span class="order-sub">数量(USDT) {od['金额']}</span>
            </div>
            <div class="order-sub">开仓价 {od['开仓价']} | 开仓时间 {od['开仓时间'].strftime('%m-%d %H:%M')}</div>
            <div class="order-sub" style="color:#00B578">开奖金支付率 80%! {"| 状态: " + od['状态']}</div>
        </div>
        """, unsafe_allow_html=True)

main_ui()
