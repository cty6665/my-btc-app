import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 核心配置 ---
st.set_page_config(page_title="事件合约", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

# --- 2. 深度视觉定制 (缝合 375px 移动端风格) ---
st.markdown("""
<style>
    /* 全局背景与导航栏 */
    .stApp { background-color: #FFFFFF; }
    [data-testid="stHeader"] { display: none; }
    
    .nav-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 44px;
        background: #FFFFFF; border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center; z-index: 999;
    }
    .nav-title { font-size: 18px; font-weight: 700; color: #000000; }

    /* 交易对与赔率区 */
    .symbol-container { margin-top: 50px; padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; }
    .symbol-name { font-size: 24px; font-weight: 700; color: #000000; }
    .odds-green { color: #00B578; font-size: 16px; font-weight: 600; }
    .odds-red { color: #FF3141; font-size: 16px; font-weight: 600; }

    /* 图表控制栏 */
    .chart-ctrl-bar { background: #F5F5F7; padding: 4px 16px; display: flex; justify-content: space-between; align-items: center; }
    .index-label { font-size: 12px; color: #8E8E93; }

    /* 模拟输入框样式美化原生组件 */
    div[data-testid="stNumberInput"] label { font-size: 16px !important; color: #000000 !important; font-weight: 400 !important; }
    div[data-testid="stNumberInput"] input { border: none !important; text-align: right !important; font-weight: 700 !important; font-size: 16px !important; }
    
    /* 核心大按钮 */
    .stButton button { 
        height: 50px !important; border-radius: 8px !important; font-size: 18px !important; font-weight: 700 !important; border: none !important;
    }
    div[data-testid="column"]:nth-of-type(1) .stButton button { background-color: #00B578 !important; color: white !important; }
    div[data-testid="column"]:nth-of-type(2) .stButton button { background-color: #FF3141 !important; color: white !important; }

    /* 成功动画 */
    @keyframes scaleIn { 0% { transform: scale(0); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 10000;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        animation: scaleIn 0.3s ease-out;
    }
</style>
<div class="nav-bar"><span class="nav-title">事件合约</span></div>
""", unsafe_allow_html=True)

# --- 3. 完整逻辑函数 (从你提供的代码中提取) ---
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
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df, "Binance"
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=100"
            res = requests.get(url, timeout=3).json()
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
            df.columns = ['time','open','high','low','close','vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Gate.io"
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

# 初始化状态
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# --- 4. 主界面逻辑 ---
@st.fragment
def main_app():
    st_autorefresh(interval=3000, key="global_refresh")
    now_time = get_beijing_time()
    
    # --- 顶栏配置区 ---
    c1, c2 = st.columns([2, 1])
    with c1: coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], label_visibility="collapsed")
    with c2: k_interval = st.selectbox("周期", ["1m", "5m", "15m", "1h"], label_visibility="collapsed")
    
    curr_p = get_price(coin)
    
    # 自动结算逻辑
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                od['平仓价'] = curr_p
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['收益'] = (od['金额'] * 0.8) if win else -od['金额']
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 1. 交易对赔率区
    st.markdown(f"""
    <div class="symbol-container">
        <div class="symbol-name">{coin}</div>
        <div style="text-align: right;">
            <div class="odds-green">上涨：80%!</div>
            <div class="odds-red">下跌：80%!</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. K 线图表区
    st.markdown('<div class="chart-ctrl-bar"><span class="index-label">指数价格</span></div>', unsafe_allow_html=True)
    
    df_k, src = get_klines_smart_source(coin, k_interval)
    if not df_k.empty:
        # 技术指标计算
        df_k['ma'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
        ema12 = df_k['close'].ewm(span=12).mean(); ema26 = df_k['close'].ewm(span=26).mean()
        df_k['macd'] = ema12 - ema26; df_k['sig'] = df_k['macd'].ewm(span=9).mean(); df_k['hist'] = df_k['macd'] - df_k['sig']

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        # 主图: 蜡烛 + BOLL
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_line_color='#00B578', decreasing_line_color='#FF3141', name="K线"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1.5), name='MB'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='#1f77b4', width=1, dash='dot'), name='UP'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='#e377c2', width=1, dash='dot'), name='DN'), row=1, col=1)
        # 副图: MACD
        fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], marker_color='gray', name='Hist'), row=2, col=1)
        
        fig.update_layout(height=350, margin=dict(t=5,b=5,l=0,r=0), xaxis_rangeslider_visible=False, dragmode='pan', plot_bgcolor='white', paper_bgcolor='white', showlegend=False)
        fig.update_yaxes(side="right", gridcolor="#F5F5F7")
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
        
        # 指标参数文本
        last = df_k.iloc[-1]
        st.markdown(f"""
        <div style="padding: 0 16px; font-size: 10px; color: #8E8E93; background: #F5F5F7;">
            BOLL(20,2) UP:{last['up']:.2f} MB:{last['ma']:.2f} DN:{last['dn']:.2f}<br>
            DIF:{last['macd']:.2f} DEA:{last['sig']:.2f} MACD:{last['hist']:.2f}
        </div>
        """, unsafe_allow_html=True)

    # 3. 交易输入区 (原生组件美化，确保可点)
    st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
    bet = st.number_input("数量(USDT)", 10.0, 5000.0, 100.0, step=10.0)
    st.markdown(f'<div style="text-align: right; padding: 0 16px; font-size: 12px; color: #8E8E93; margin-top: -15px;">可用 {st.session_state.balance:,.2f} USDT</div>', unsafe_allow_html=True)
    
    st.markdown(f"""
    <div style="padding: 12px 16px; border-top: 1px solid #F5F5F7;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <span style="font-size: 16px;">支付率</span>
            <span style="color: #00B578; font-weight: 600;">80%!</span>
        </div>
        <div style="display: flex; justify-content: space-between;">
            <span style="font-size: 16px;">U本位合约</span>
            <span style="font-weight: 600;">{st.session_state.balance:,.2f} USDT+</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. 操作按钮
    st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
    btn_col1, btn_col2 = st.columns(2)
    duration = 5 # 默认 5 分钟结算
    
    if btn_col1.button("上涨", use_container_width=True) and curr_p:
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            st.session_state.show_success = True; st.rerun()

    if btn_col2.button("下跌", use_container_width=True) and curr_p:
        if st.session_state.balance >= bet:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": curr_p, "平仓价": None, "金额": bet, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            st.session_state.show_success = True; st.rerun()

    # 5. 订单列表 (缝合你的流水逻辑)
    st.markdown('<div style="height: 20px; background: #F5F5F7; margin: 15px -1rem 0 -1rem;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="padding: 10px 16px; font-weight: 700; border-bottom: 2px solid #00B578; width: fit-content;">已开仓/流水</div>', unsafe_allow_html=True)
    
    if not st.session_state.orders:
        st.info("暂无交易记录")
    else:
        for o in reversed(st.session_state.orders[-15:]):
            color = "#00B578" if o['方向'] == "看涨" else "#FF3141"
            icon = "▲" if o['方向'] == "看涨" else "▼"
            status_txt = o['结果'] if o['结果'] else "进行中..."
            st.markdown(f"""
            <div style="padding: 12px 16px; border-bottom: 1px solid #F5F5F7;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="font-weight: 600;"><span style="color:{color}">{icon}</span> {o['资产']}</span>
                    <span style="color: #8E8E93; font-size: 14px;">数量 {o['金额']}</span>
                </div>
                <div style="font-size: 12px; color: #8E8E93; margin-top: 4px;">
                    开仓价 {o['开仓价']:,.2f} | {o['开仓时间'].strftime('%H:%M:%S')}
                </div>
                <div style="font-size: 12px; color: {color}; margin-top: 2px;">
                    支付率 80%! | 结果: {status_txt}
                </div>
            </div>
            """, unsafe_allow_html=True)

# 成功动画
if 'show_success' not in st.session_state: st.session_state.show_success = False
if st.session_state.show_success:
    st.markdown('<div class="success-overlay"><h1 style="color: #00B578;">✓</h1><h2 style="color: #00B578;">下单成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1); st.session_state.show_success = False; st.rerun()

# 启动
main_app()
