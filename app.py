import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境检测 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置 (红线：数据库、CSS、双源价格)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

# --- 手机端适配 CSS ---
st.markdown("""
<style>
    .stApp { background-color: #ffffff; }
    .stButton button { background: #FCD535 !important; color: #000 !important; font-weight: bold !important; height: 55px !important; border-radius: 8px !important; border: none !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; font-family: monospace; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } }
    .stTable { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=3000, key="global_refresh")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if isinstance(od.get(key), str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if isinstance(tmp.get(key), datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(tmp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

def get_price(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", headers=headers, timeout=2).json()
            return float(res[0]['last'])
        except: return None

def get_klines_direct(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=3).json()
        df = pd.DataFrame(res, columns=['time','open','high','low','close','vol','x','x','x','x','x','x'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        df['ma'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'], df['dn'] = df['ma'] + 2*df['std'], df['ma'] - 2*df['std']
        exp12, exp26 = df['close'].ewm(span=12).mean(), df['close'].ewm(span=26).mean()
        df['dif'] = exp12 - exp26
        df['dea'] = df['dif'].ewm(span=9).mean()
        df['hist'] = (df['dif'] - df['dea']) * 2
        return df
    except: return pd.DataFrame()

# ==========================================
# 控制区
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制台")
    chart_mode = st.radio("图表模式", ["TradingView", "原生 K 线"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    # 周期还原：5, 10, 30, 60
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额", 10.0, 5000.0, 50.0)
    if st.button("🚨 重置系统"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = get_beijing_time()

# 结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            close_p = get_price(od['资产'])
            if close_p:
                od['平仓价'] = close_p
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                if win: 
                    st.session_state.balance += od['金额'] * 1.8
                    od['收益'] = od['金额'] * 0.8
                else: od['收益'] = -od['金额']
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 显示区
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 现价", f"${current_price:,.2f}" if current_price else "同步中...")

if chart_mode == "TradingView":
    tv_script = f"""
    <div style="height:500px; width:100%;">
      <div id="tradingview_chart" style="height:500px; width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1", "timezone": "Asia/Shanghai",
        "theme": "light", "style": "1", "locale": "zh_CN", "toolbar_bg": "#f1f3f6",
        "container_id": "tradingview_chart", "studies": ["BB@tv-basicstudies", "MACD@tv-basicstudies"] 
      }});
      </script>
    </div>
    """
    components.html(tv_script, height=500)
else:
    if HAS_PLOTLY:
        df_k = get_klines_direct(coin)
        if not df_k.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.02)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K'), row=1, col=1)
            fig.update_layout(height=500, margin=dict(t=10,b=10,l=10,r=10), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# 交易操作 (仪式感动画)
b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交订单中...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交订单中...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

# ==========================================
# 统计与流水 (找回你的“仪式感”细节)
# ==========================================
st.markdown("---")
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
t_pnl = sum(o['收益'] for o in settled if o['开仓时间'].date() == now.date())
m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")
m3.metric("总盈亏", f"${sum(o['收益'] for o in settled):.1f}")
m4.metric("总胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")

st.subheader("📋 交易流水")

# --- 还原你最喜欢的细节 ---
if not st.session_state.orders:
    st.info("💡 请开启你的第一笔交易，开始盈利之旅！")
else:
    data = []
    for o in reversed(st.session_state.orders[-10:]):
        rem = (o['结算时间'] - now).total_seconds()
        data.append({
            "时间": o['开仓时间'].strftime('%H:%M:%S'),
            "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
            "金额": f"${o['金额']}",
            "入场": f"{o['开仓价']:,.2f}",
            "平仓": f"{o['平仓价']:,.2f}" if o['平仓价'] else "运行中",
            "结果": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
        })
    st.table(data)
