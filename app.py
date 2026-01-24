import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

# ==========================================
# 1. 基础配置与时差处理
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Hybrid Terminal", layout="wide", initial_sidebar_state="collapsed")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# 核心：计算技术指标 (用于原生绘图)
def add_indicators(df):
    # 布林带计算
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['std'] = df['close'].rolling(window=20).std()
    df['upper'] = df['ma20'] + (df['std'] * 2)
    df['lower'] = df['ma20'] - (df['std'] * 2)
    # MACD计算
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    return df

# ==========================================
# 2. 数据库与行情获取
# ==========================================
def get_price_and_klines(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        # 1. 获取当前价
        p_res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=3).json()
        current_p = float(p_res['price'])
        # 2. 获取K线 (原生绘图需要)
        k_res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60", headers=headers, timeout=3).json()
        df = pd.DataFrame(k_res, columns=['time','open','high','low','close','vol','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
        return current_p, df, "OK"
    except Exception as e:
        return None, None, str(e)

# 数据库加载/保存 (保持原有逻辑)
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance, orders = data.get('balance', 1000.0), data.get('orders', [])
                for od in orders:
                    for k in ['结算时间', '开仓时间']:
                        if isinstance(od.get(k), str): od[k] = datetime.strptime(od[k], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        temp = od.copy()
        for k in ['结算时间', '开仓时间']:
            if isinstance(temp.get(k), datetime): temp[k] = temp[k].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(temp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 3. 侧边栏与模式切换
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    # --- 核心切换开关 ---
    chart_mode = st.radio("图表引擎模式", ["TradingView (需要VPN)", "原生Plotly (无需VPN)"], index=0)
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30], index=0)
    bet = st.number_input("下单金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置系统"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price, df_klines, status = get_price_and_klines(coin)
now = get_beijing_time()

# 结算逻辑 (原封不动)
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            od["平仓价"] = current_price
            win = (od["方向"] == "看涨" and current_price > od["开仓价"]) or (od["方向"] == "看跌" and current_price < od["开仓价"])
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

# --- 图表逻辑分发 ---
if chart_mode == "TradingView (需要VPN)":
    tv_html = f"""<div style="height:400px;"><script src="https://s3.tradingview.com/tv.js"></script>
    <div id="tv-chart" style="height:400px;"></div>
    <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart","hide_side_toolbar":false,"allow_symbol_change":false,"studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
    components.html(tv_html, height=400)
else:
    # 自研 Plotly 绘图逻辑 (含布林带与MACD)
    if status == "OK":
        df = add_indicators(df_klines)
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        # K线与布林带
        fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='K线'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['time'], y=df['upper'], line=dict(color='rgba(173,216,230,0.5)'), name='布林上轨'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['time'], y=df['lower'], line=dict(color='rgba(173,216,230,0.5)'), fill='tonexty', name='布林下轨'), row=1, col=1)
        # MACD
        colors = ['red' if val < 0 else 'green' for val in df['hist']]
        fig.add_trace(go.Bar(x=df['time'], y=df['hist'], marker_color=colors, name='MACD柱'), row=2, col=1)
        fig.update_layout(height=450, margin=dict(l=0,r=0,t=0,b=0), template="plotly_white", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

# 下单按钮
col_up, col_down = st.columns(2)
btn_css = "<style>.stButton button{background:#FCD535!important;color:#000;font-weight:bold;height:55px;border-radius:10px;}</style>"
st.markdown(btn_css, unsafe_allow_html=True)

if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.toast("✅ 已开仓看涨")
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
        save_db(st.session_state.balance, st.session_state.orders)
        st.toast("✅ 已开仓看跌")
        st.rerun()

# 统计行
st.markdown("---")
# 计算逻辑... (省略同前)
m1, m2, m3, m4 = st.columns(4)
m1.metric("今日盈亏", "$0.0") # 示意
m2.metric("今日胜率", "0%")
m3.metric("总盈亏", "$0.0")
m4.metric("总胜率", "0%")
st.markdown("---")

# 流水表
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        df_show.append({
            "时间": od.get("开仓时间").strftime('%H:%M:%S'),
            "方向": "涨 ↗️" if od.get("方向") == "看涨" else "跌 ↘️",
            "金额": f"${od.get('金额')}",
            "入场价": f"{od.get('开仓价', 0):,.2f}",
            "结果": od.get("结果") if od.get("结果") else f"{int(max(0,rem))}s"
        })
    st.table(df_show)
