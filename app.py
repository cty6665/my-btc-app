import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 核心配置 ---
st.set_page_config(page_title="Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

try:
    import plotly.graph_objects as go
except:
    pass

# ==========================================
# 精准 CSS：优化按钮反馈与 K 线容器
# ==========================================
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
    
    /* 交易按钮 - 增加点击动效 */
    .stButton button { 
        background: #FCD535 !important; color: #000 !important; font-weight: bold !important; 
        height: 60px !important; border-radius: 12px !important; border: none !important;
        font-size: 1.1rem !important; transition: all 0.1s;
    }
    .stButton button:active { transform: scale(0.95); opacity: 0.8; }

    /* 成功动效 */
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.85); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 核心逻辑 (完全锁定，不作改动)
# ==========================================
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

# 数据库逻辑 (锁定)
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                d = json.load(f); ords = d.get('orders', [])
                for o in ords:
                    for k in ['结算时间', '开仓时间']:
                        if o.get(k): o[k] = datetime.strptime(o[k], '%Y-%m-%d %H:%M:%S')
                return d.get('balance', 1000.0), ords
        except: return 1000.0, []
    return 1000.0, []

def save_db(bal, ords):
    ser = []
    for o in ords:
        t = o.copy()
        for k in ['结算时间', '开仓时间']:
            if isinstance(t.get(k), datetime): t[k] = t[k].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(t)
    with open(DB_FILE, "w") as f: json.dump({"balance": bal, "orders": ser}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 侧边栏 (锁定)
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制中心")
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    k_interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=0)
    duration = st.radio("到期时间", [5, 10, 30], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)

# ==========================================
# 顶部数据卡片 & K线 (局部刷新)
# ==========================================
@st.fragment
def top_and_chart():
    st_autorefresh(interval=3000, key="auto_refresh")
    curr_p = get_price(coin)
    now_time = get_beijing_time()

    # 1. 数据面板
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{coin} 实时现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    # 2. 精美原生 K 线
    df = get_klines_smart_source(coin, k_interval)
    if not df.empty:
        df['ma'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'] = df['ma'] + 2*df['std']
        df['dn'] = df['ma'] - 2*df['std']
        
        fig = go.Figure()
        # 布林带填充
        fig.add_trace(go.Scatter(x=df['time'], y=df['up'], line=dict(color='rgba(41, 98, 255, 0.15)', width=0.5), showlegend=False))
        fig.add_trace(go.Scatter(x=df['time'], y=df['dn'], line=dict(color='rgba(41, 98, 255, 0.15)', width=0.5), fill='tonexty', fillcolor='rgba(41, 98, 255, 0.03)', showlegend=False))
        # 中轨
        fig.add_trace(go.Scatter(x=df['time'], y=df['ma'], line=dict(color='#FFD700', width=1.2), showlegend=False))
        # 蜡烛图 (视觉精修)
        fig.add_trace(go.Candlestick(
            x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            increasing_fillcolor='#02c076', increasing_line_color='#02c076',
            decreasing_fillcolor='#f84960', decreasing_line_color='#f84960',
            name="K线"
        ))
        
        fig.update_layout(
            height=380, margin=dict(t=10, b=10, l=0, r=0),
            xaxis_rangeslider_visible=False,
            # 开启自由滑动缩放
            dragmode='pan',
            hovermode='x unified',
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis=dict(showgrid=True, gridcolor='#f0f0f0', fixedrange=False),
            yaxis=dict(showgrid=True, gridcolor='#f0f0f0', side='right', fixedrange=False)
        )
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
    else:
        st.error("行情加载中...")

# 执行顶部区域渲染
top_and_chart()

# ==========================================
# 核心更改：下单按钮位置 (放在 K 线下方，流水上方)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
b1, b2 = st.columns(2)
curr_p_static = get_price(coin)
now_static = get_beijing_time()

if b1.button("🟢 买涨 (UP)", use_container_width=True):
    if st.session_state.balance >= bet and curr_p_static:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看涨", "开仓价": curr_p_static, "平仓价": None,
            "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration),
            "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.session_state.show_success = True
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True):
    if st.session_state.balance >= bet and curr_p_static:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看跌", "开仓价": curr_p_static, "平仓价": None,
            "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration),
            "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.session_state.show_success = True
        st.rerun()

# ==========================================
# 成功动画展示
# ==========================================
if st.session_state.get('show_success'):
    st.markdown('<div class="success-overlay"><h1 style="color: #0ECB81;">✔️ 开仓成功</h1></div>', unsafe_allow_html=True)
    time.sleep(1)
    st.session_state.show_success = False
    st.rerun()

# ==========================================
# 交易流水 (底部)
# ==========================================
st.divider()
st.subheader("📋 交易流水")

@st.fragment
def order_table():
    # 随行情刷新倒计时
    st_autorefresh(interval=3000, key="table_refresh")
    now = get_beijing_time()
    if not st.session_state.orders:
        st.info("暂无交易记录")
    else:
        data = []
        for o in reversed(st.session_state.orders[-8:]):
            rem = (o['结算时间'] - now).total_seconds()
            data.append({
                "币种": o['资产'].replace("USDT",""),
                "方向": "涨" if o['方向']=="看涨" else "跌",
                "金额": f"${o['金额']}",
                "开仓价": f"{o['开仓价']:,.2f}",
                "结算/倒计时": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
            })
        st.table(data)

order_table()
