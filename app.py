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
# 基础配置 & 增强版视觉定制
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    /* 隐藏侧边栏按钮 */
    [data-testid="collapsedControl"] { display: none; }
    
    /* 数据卡片 */
    .data-card {
        background: #ffffff; padding: 12px; border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-top: 3px solid #FCD535;
        text-align: center; margin-bottom: 10px;
    }
    .balance-border { border-top: 3px solid #0ECB81; }
    .card-label { color: #848e9c; font-size: 0.75rem; margin-bottom: 2px; }
    .card-value { color: #1e2329; font-size: 1.2rem; font-weight: 700; }
    
    /* 历史订单卡片 (对标图片) */
    .order-card {
        background: white; border-radius: 8px; padding: 15px; 
        margin-bottom: 10px; border-bottom: 1px solid #eee;
    }
    .order-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .symbol-box { display: flex; align-items: center; font-weight: bold; font-size: 1.1rem; }
    .direction-up { color: #0ecb81; margin-right: 5px; }
    .direction-down { color: #f6465d; margin-right: 5px; }
    .profit-text { font-weight: 800; font-size: 1.1rem; }
    
    .order-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
    .grid-item { display: flex; flex-direction: column; }
    .grid-label { color: #909090; font-size: 0.7rem; }
    .grid-val { color: #222; font-size: 0.85rem; margin-top: 2px; }
    
    /* 下单按钮 */
    .stButton button { border-radius: 8px !important; font-weight: bold !important; }
    .up-btn button { background-color: #0ecb81 !important; color: white !important; border: none !important; height: 50px !important; }
    .down-btn button { background-color: #f6465d !important; color: white !important; border: none !important; height: 50px !important; }
    
    /* K线周期按钮组 */
    .stSelectbox label { display: none; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 工具函数
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
if 'bet_amt' not in st.session_state: st.session_state.bet_amt = 100.0
if 'curr_coin' not in st.session_state: st.session_state.curr_coin = "BTCUSDT"
if 'curr_interval' not in st.session_state: st.session_state.curr_interval = "1m"
if 'curr_duration' not in st.session_state: st.session_state.curr_duration = 5
if 'chart_src' not in st.session_state: st.session_state.chart_src = "原生 K 线"

# ==========================================
# 核心 UI 逻辑
# ==========================================
@st.fragment
def live_ui():
    st_autorefresh(interval=3000, key="terminal_refresh")
    now_time = get_beijing_time()
    
    # 1. 顶部控制栏 (取代侧边栏)
    c1, c2, c3 = st.columns(3)
    with c1: 
        st.session_state.chart_src = st.selectbox("数据源", ["原生 K 线", "TradingView"], index=0 if st.session_state.chart_src=="原生 K 线" else 1)
    with c2:
        st.session_state.curr_coin = st.selectbox("交易币对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"])
    with c3:
        st.session_state.curr_duration = st.selectbox("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} min")

    # 2. 价格卡片
    curr_p = get_price(st.session_state.curr_coin)
    h1, h2 = st.columns(2)
    h1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额 (USDT)</div><div class="card-value">{st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    d_p = curr_p if curr_p else 0.0
    h2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.curr_coin} 实时现价</div><div class="card-value">{d_p:,.2f}</div></div>', unsafe_allow_html=True)

    # 3. K线周期快捷选择 (横向按钮组)
    st.markdown("---")
    intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
    cols_int = st.columns(len(intervals))
    for i, inter in enumerate(intervals):
        if cols_int[i].button(inter, use_container_width=True, type="secondary" if st.session_state.curr_interval != inter else "primary"):
            st.session_state.curr_interval = inter
            st.rerun()

    # 4. 自动结算逻辑
    if curr_p:
        upd = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                cp_f = get_price(od['资产'])
                if cp_f:
                    od['平仓价'] = cp_f
                    win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                    st.session_state.balance += (od['金额'] * 1.8) if win else 0
                    od['收益'] = (od['金额'] * 0.8) if win else -od['金额']
                    od['状态'], od['结果'] = "已结算", "W" if win else "L"
                    upd = True
        if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 5. K 线图表区
    if st.session_state.chart_src == "TradingView":
        tv_i = "1" if st.session_state.curr_interval == "1m" else st.session_state.curr_interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.curr_coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df_k = get_klines_smart_source(st.session_state.curr_coin, st.session_state.curr_interval)
        if not df_k.empty:
            # 指标计算
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']; df_k['dn'] = df_k['ma'] - 2*df_k['std']
            ema12 = df_k['close'].ewm(span=12).mean(); ema26 = df_k['close'].ewm(span=26).mean()
            df_k['macd'] = ema12 - ema26; df_k['sig'] = df_k['macd'].ewm(span=9).mean(); df_k['hist'] = df_k['macd'] - df_k['sig']

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            # 主图
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(173,216,230,0.4)'), name='BOLL'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='#FFB11B', width=1.5), name='MID'), row=1, col=1)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'), row=1, col=1)
            
            # 副图 MACD (红绿柱)
            colors = ['#0ECB81' if x >= 0 else '#F6465D' for x in df_k['hist']]
            fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], marker_color=colors, name='Hist'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['macd'], line=dict(color='#2962FF', width=1)), row=2, col=1)
            
            fig.update_layout(height=400, margin=dict(t=0,b=0,l=0,r=0), xaxis_rangeslider_visible=False, showlegend=False, plot_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # 6. 下单操作区
    st.markdown("<br>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🟢 买涨 (UP)", use_container_width=True, key="up_btn"):
            if st.session_state.balance >= st.session_state.bet_amt and curr_p:
                st.session_state.balance -= st.session_state.bet_amt
                st.session_state.orders.append({"资产": st.session_state.curr_coin, "方向": "看涨", "开仓价": curr_p, "平仓价": None, "金额": st.session_state.bet_amt, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=st.session_state.curr_duration), "状态": "待结算", "结果": None, "收益": 0})
                save_db(st.session_state.balance, st.session_state.orders)
                st.rerun()
    with b2:
        if st.button("🔴 买跌 (DOWN)", use_container_width=True, key="down_btn"):
            if st.session_state.balance >= st.session_state.bet_amt and curr_p:
                st.session_state.balance -= st.session_state.bet_amt
                st.session_state.orders.append({"资产": st.session_state.curr_coin, "方向": "看跌", "开仓价": curr_p, "平仓价": None, "金额": st.session_state.bet_amt, "开仓时间": now_time, "结算时间": now_time+timedelta(minutes=st.session_state.curr_duration), "状态": "待结算", "结果": None, "收益": 0})
                save_db(st.session_state.balance, st.session_state.orders)
                st.rerun()

    # 7. 下单金额步进器
    st.write("---")
    amt_c1, amt_c2, amt_c3 = st.columns([1, 2, 1])
    if amt_c1.button("➖", use_container_width=True): 
        st.session_state.bet_amt = max(10.0, st.session_state.bet_amt - 50.0)
        st.rerun()
    st.session_state.bet_amt = amt_c2.number_input("下单金额", value=st.session_state.bet_amt, step=10.0, label_visibility="collapsed")
    if amt_c3.button("➕", use_container_width=True): 
        st.session_state.bet_amt += 50.0
        st.rerun()

    # 8. 实时流水 (卡片化 - 对标图片)
    st.subheader("📋 历史成交")
    if not st.session_state.orders:
        st.info("暂无交易记录")
    else:
        for o in reversed(st.session_state.orders[-15:]):
            dir_class = "direction-up" if o['方向'] == "看涨" else "direction-down"
            dir_icon = "↗" if o['方向'] == "看涨" else "↘"
            profit_color = "#0ecb81" if o['收益'] > 0 else ("#f6465d" if o['收益'] < 0 else "#222")
            p_val = f"+{o['收益']:.2f}" if o['收益'] > 0 else f"{o['收益']:.2f}"
            
            card_html = f"""
            <div class="order-card">
                <div class="order-header">
                    <div class="symbol-box">
                        <span class="{dir_class}">{dir_icon}</span> {o['资产']}
                    </div>
                    <div class="profit-text" style="color: {profit_color}">{p_val} USDT</div>
                </div>
                <div class="order-grid">
                    <div class="grid-item">
                        <span class="grid-label">数量(USDT)</span>
                        <span class="grid-val">{o['金额']}</span>
                    </div>
                    <div class="grid-item">
                        <span class="grid-label">开仓价</span>
                        <span class="grid-val">{o['开仓价']:,.4f}</span>
                    </div>
                    <div class="grid-item">
                        <span class="grid-label">开仓时间</span>
                        <span class="grid-val">{o['开仓时间'].strftime('%m-%d %H:%M:%S')}</span>
                    </div>
                    <div class="grid-item">
                        <span class="grid-label">奖金支付率</span>
                        <span class="grid-val" style="color:#0ecb81">80%</span>
                    </div>
                    <div class="grid-item">
                        <span class="grid-label">平仓价</span>
                        <span class="grid-val">{o['平仓价'] if o['平仓价'] else '---':,.4f}</span>
                    </div>
                    <div class="grid-item">
                        <span class="grid-label">平仓时间</span>
                        <span class="grid-val">{o['结算时间'].strftime('%m-%d %H:%M:%S')}</span>
                    </div>
                </div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)

# 启动 UI
live_ui()
