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
# 视觉样式：彩色边框、手机滚动、压感按钮
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
    
    .stButton button { 
        background: #FCD535 !important; color: #000 !important; font-weight: bold !important; 
        height: 60px !important; border-radius: 12px !important; border: none !important;
        font-size: 1.1rem !important; transition: all 0.1s;
    }
    .stButton button:active { transform: scale(0.95); opacity: 0.8; }

    @media (max-width: 640px) {
        .stTable { display: block !important; overflow-x: auto !important; white-space: nowrap !important; }
    }
    
    .success-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.85); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 核心获取行情逻辑 (全修复)
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        # 备用方案：Binance + Gate
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

def get_klines_data(symbol, interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

# 数据库 (锁定)
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                d = json.load(f); ords = d.get('orders', [])
                for o in ords:
                    for k in ['结算时间', '开仓时间']:
                        if o.get(k) and isinstance(o[k], str): 
                            o[k] = datetime.strptime(o[k], '%Y-%m-%d %H:%M:%S')
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
# 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制中心")
    chart_mode = st.radio("切换K线视图", ["原生 K 线", "TradingView"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    k_interval = st.selectbox("K线周期", ["1m", "5m", "15m", "1h"], index=0)
    duration = st.radio("到期时间", [5, 10, 30], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)

# ==========================================
# 顶部数据 & K线渲染 (局部刷新)
# ==========================================
@st.fragment
def main_display():
    st_autorefresh(interval=3000, key="auto_refresh")
    curr_p = get_price(coin)
    now_time = get_beijing_time()

    # 1. 顶部面板
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    # 2. K线视图切换
    if chart_mode == "TradingView":
        tv_i = "1" if k_interval == "1m" else k_interval.replace("m", "")
        tv_html = f"""<div style="height:380px;"><div id="tv" style="height:380px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>"""
        components.html(tv_html, height=380)
    else:
        df = get_klines_data(coin, k_interval)
        if not df.empty:
            df['ma'] = df['close'].rolling(20).mean()
            df['std'] = df['close'].rolling(20).std()
            df['up'] = df['ma'] + 2*df['std']; df['dn'] = df['ma'] - 2*df['std']
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['time'], y=df['up'], line=dict(color='rgba(41,98,255,0.2)', width=0.8), showlegend=False))
            fig.add_trace(go.Scatter(x=df['time'], y=df['dn'], line=dict(color='rgba(41,98,255,0.2)', width=0.8), fill='tonexty', fillcolor='rgba(41,98,255,0.05)', showlegend=False))
            fig.add_trace(go.Scatter(x=df['time'], y=df['ma'], line=dict(color='#FFB11B', width=1.5), showlegend=False))
            fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], increasing_fillcolor='#02c076', increasing_line_color='#02c076', decreasing_fillcolor='#f84960', decreasing_line_color='#f84960'))
            
            fig.update_layout(
                height=380, margin=dict(t=10, b=10, l=0, r=0),
                xaxis_rangeslider_visible=False,
                dragmode='pan', # 默认手势为滑动
                plot_bgcolor='white', paper_bgcolor='white',
                xaxis=dict(showgrid=True, gridcolor='#f2f2f2', fixedrange=False),
                yaxis=dict(showgrid=True, gridcolor='#f2f2f2', side='right', fixedrange=False)
            )
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
        else:
            st.warning("正在同步 API 数据...")

main_display()

# ==========================================
# 中间位置：下单按钮
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
b1, b2 = st.columns(2)
curr_p_act = get_price(coin)
now_act = get_beijing_time()

if b1.button("🟢 买涨 (UP)", use_container_width=True):
    if st.session_state.balance >= bet and curr_p_act:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": curr_p_act, "平仓价": None, "金额": bet, "开仓时间": now_act, "结算时间": now_act+timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.session_state.show_success = True
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True):
    if st.session_state.balance >= bet and curr_p_act:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": curr_p_act, "平仓价": None, "金额": bet, "开仓时间": now_act, "结算时间": now_act+timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.session_state.show_success = True
        st.rerun()

# 成功动效
if st.session_state.get('show_success'):
    st.markdown('<div class="success-overlay"><h2 style="color: #0ECB81;">✔️ 开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1)
    st.session_state.show_success = False
    st.rerun()

# ==========================================
# 底部：交易流水
# ==========================================
st.divider()
st.subheader("📋 交易流水")

@st.fragment
def table_area():
    st_autorefresh(interval=3000, key="table_auto")
    now = get_beijing_time()
    if not st.session_state.orders:
        st.info("暂无记录")
    else:
        display_list = []
        for o in reversed(st.session_state.orders[-10:]):
            rem = (o['结算时间'] - now).total_seconds()
            display_list.append({
                "资产": o['资产'].replace("USDT",""),
                "方向": "涨" if o['方向']=="看涨" else "跌",
                "开仓": f"{o['开仓价']:,.2f}",
                "现价/平仓": f"{get_price(o['资产']):,.2f}" if not o['平仓价'] else f"{o['平仓价']:,.2f}",
                "结果/倒计时": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
            })
        st.table(display_list)

table_area()
