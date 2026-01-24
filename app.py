import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import time

# 尝试导入绘图库，如果环境没有则提示安装
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 1. 数据库与基础设置
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Pro Hybrid", layout="wide", initial_sidebar_state="collapsed")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                return data.get('balance', 1000.0), data.get('orders', [])
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    # 转换时间对象为字符串以便保存
    s_orders = []
    for o in orders:
        temp = o.copy()
        for k in ['结算时间', '开仓时间']:
            if isinstance(temp.get(k), datetime):
                temp[k] = temp[k].strftime('%Y-%m-%d %H:%M:%S')
        s_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": s_orders}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
    # 转换回 datetime 对象
    for od in st.session_state.orders:
        for k in ['结算时间', '开仓时间']:
            if isinstance(od.get(k), str):
                od[k] = datetime.strptime(od[k], '%Y-%m-%d %H:%M:%S')

# 样式美化（包含你要求的手机端适配）
st.markdown("""
<style>
    .stApp { background:#FFF; }
    .stButton button { background:#FCD535 !important; color:#000 !important; font-weight:bold !important; height: 55px !important; border-radius: 10px !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; } }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情引擎 (严格参考你提供的获取逻辑)
# ==========================================
def get_price_data(symbol):
    # 你的核心获取逻辑：币安优先，Gate.io 备用
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    price = None
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        price = float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            price = float(res[0]['last'])
        except: price = None
    
    # 获取K线用于原生绘图 (1分钟线)
    df = pd.DataFrame()
    try:
        k_res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=50", timeout=2).json()
        df = pd.DataFrame(k_res, columns=['time','open','high','low','close','vol','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
    except: pass
    
    return price, df

# ==========================================
# 3. 控制面板与逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    chart_engine = st.radio("图表引擎", ["TradingView", "原生K线 (直连)"], index=0)
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额 (U)", 10.0, 1000.0, 50.0)
    if st.button("🚨 清空记录"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price, df_k = get_price_data(coin)
now = get_beijing_time()

# 结算逻辑 (原版不动)
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            p_close, _ = get_price_data(od.get("资产", coin))
            if p_close:
                od["平仓价"] = p_close
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "W" if win else "L", "收益": (od["金额"] * 0.8) if win else -od["金额"]})
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 4. UI 布局
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "同步中")

# 图表逻辑
if chart_engine == "TradingView":
    tv_html = f"""<div style="height:380px;"><script src="https://s3.tradingview.com/tv.js"></script>
    <div id="tv-chart" style="height:380px;"></div>
    <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart"}});</script></div>"""
    components.html(tv_html, height=380)
else:
    if not df_k.empty and HAS_PLOTLY:
        # 计算布林带和 MACD 指标
        df_k['ma20'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'], df_k['dn'] = df_k['ma20'] + 2*df_k['std'], df_k['ma20'] - 2*df_k['std']
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K线'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(0,0,255,0.1)'), name='布林上轨'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(0,0,255,0.1)'), fill='tonexty', name='布林下轨'), row=1, col=1)
        fig.update_layout(height=380, margin=dict(l=0,r=0,t=0,b=0), template="plotly_white", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("原生绘图数据同步中...请确保已安装 plotly 库")

# 下单区域
cu, cd = st.columns(2)
if cu.button("🟢 看涨 (UP)", key="up") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.toast(f"看涨成功！"); st.rerun()

if cd.button("🔴 看跌 (DOWN)", key="down") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.toast(f"看跌成功！"); st.rerun()

# --- 统计显示 ---
st.markdown("---")
settled = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
today_str = now.strftime('%Y-%m-%d')
today_o = [o for o in settled if o.get("开仓时间") and o.get("开仓时间").strftime('%Y-%m-%d') == today_str]
t_pnl = sum([o.get("收益", 0) for o in today_o])
t_wr = (len([o for o in today_o if o.get("结果") == "W"]) / len(today_o) * 100) if today_o else 0
all_pnl = sum([o.get("收益", 0) for o in settled])
all_wr = (len([o for o in settled if o.get("结果") == "W"]) / len(settled) * 100) if settled else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(t_wr)}%")
m3.metric("总盈亏", f"${all_pnl:.1f}")
m4.metric("总胜率", f"{int(all_wr)}%")
st.markdown("---")

# 流水
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        p_c = od.get("平仓价")
        df_show.append({
            "时间": od.get("开仓时间").strftime('%H:%M:%S') if od.get("开仓时间") else "-",
            "方向": "涨 ↗️" if od.get("方向") == "看涨" else "跌 ↘️",
            "金额": f"${od.get('金额')}",
            "结果": od.get("结果") if od.get("结果") else f"{int(max(0,rem))}s"
        })
    st.table(df_show)
