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
# 1. 基础配置与数据库 (保持原逻辑)
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Hybrid Terminal", layout="wide", initial_sidebar_state="collapsed")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                for od in orders:
                    for k in ['结算时间', '开仓时间']:
                        if isinstance(od.get(k), str):
                            od[k] = datetime.strptime(od[k], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        temp = od.copy()
        for k in ['结算时间', '开仓时间']:
            if isinstance(temp.get(k), datetime):
                temp[k] = temp[k].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

# CSS 修复：强制手机端不显示省略号，并美化按钮
st.markdown("""
<style>
    .stApp { background:#FFF; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    .stButton button { background:#FCD535!important; color:#000!important; font-weight:bold!important; height:55px!important; border-radius:10px!important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; } }
</style>
""", unsafe_allow_html=True)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情获取引擎 (双模核心)
# ==========================================
def get_market_data(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        # 获取当前价
        p_res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=3).json()
        current_p = float(p_res['price'])
        # 获取K线 (用于原生绘图)
        k_res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=50", headers=headers, timeout=3).json()
        df = pd.DataFrame(k_res, columns=['time','open','high','low','close','vol','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
        
        # 计算指标 (BB & MACD)
        df['ma20'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['upper'], df['lower'] = df['ma20'] + 2*df['std'], df['ma20'] - 2*df['std']
        exp1, exp2 = df['close'].ewm(span=12).mean(), df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['sig'] = df['macd'].ewm(span=9).mean()
        df['hist'] = df['macd'] - df['sig']
        
        return current_p, df, "OK"
    except Exception as e:
        return None, None, str(e)

# ==========================================
# 3. 逻辑处理
# ==========================================
with st.sidebar:
    st.header("⚙️ 设置")
    chart_mode = st.radio("K线引擎", ["TradingView (VPN)", "原生绘制 (直连)"])
    coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("周期", [5, 10, 30, 60], format_func=lambda x:f"{x}min")
    bet = st.number_input("金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置记录"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price, df_k, status = get_market_data(coin)
now = get_beijing_time()

# 结算逻辑
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
# 4. UI 展现
# ==========================================
c1, c2 = st.columns(2)
c1.metric("余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin}", f"${current_price:,.2f}" if current_price else "连接中")

# 图表切换
if chart_mode == "TradingView (VPN)":
    tv_html = f"""<div style="height:380px;"><script src="https://s3.tradingview.com/tv.js"></script><div id="tv-chart" style="height:380px;"></div>
    <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
    components.html(tv_html, height=380)
else:
    if status == "OK":
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['upper'], line=dict(color='rgba(0,0,255,0.2)'), name='BB上'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['lower'], line=dict(color='rgba(0,0,255,0.2)'), fill='tonexty', name='BB下'), row=1, col=1)
        fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], name='MACD'), row=2, col=1)
        fig.update_layout(height=380, margin=dict(l=10,r=10,t=10,b=10), template="plotly_white", xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# 下单
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在开仓...") as s:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产":coin,"方向":"看涨","开仓价":current_price,"平仓价":None,"金额":bet,"开仓时间":now,"结算时间":now+timedelta(minutes=duration),"状态":"待结算","结果":None})
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.3)
            s.update(label="✅ 开仓成功", state="complete")
        st.toast("下单成功: 看涨", icon="📈"); st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在开仓...") as s:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产":coin,"方向":"看跌","开仓价":current_price,"平仓价":None,"金额":bet,"开仓时间":now,"结算时间":now+timedelta(minutes=duration),"状态":"待结算","结果":None})
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.3)
            s.update(label="✅ 开仓成功", state="complete")
        st.toast("下单成功: 看跌", icon="📉"); st.rerun()

# --- 统计行 (彻底解决省略号) ---
st.markdown("---")
settled = [o for o in st.session_state.orders if o.get("状态")=="已结算"]
t_str = now.strftime('%Y-%m-%d')
today_o = [o for o in settled if o.get("开仓时间") and o.get("开仓时间").strftime('%Y-%m-%d') == t_str]
t_pnl = sum([o.get("收益",0) for o in today_o])
t_wr = (len([o for o in today_o if o.get("结果")=="W"])/len(today_o)*100) if today_o else 0
all_pnl = sum([o.get("收益",0) for o in settled])
all_wr = (len([o for o in settled if o.get("结果")=="W"])/len(settled)*100) if settled else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("今日", f"${t_pnl:.1f}")
m2.metric("今胜", f"{int(t_wr)}%")
m3.metric("总盈", f"${all_pnl:.1f}")
m4.metric("总胜", f"{int(all_wr)}%")
st.markdown("---")

# 流水
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        pc = od.get("平仓价")
        df_show.append({
            "时间": od.get("开仓时间").strftime('%H:%M:%S'),
            "方向": "涨 ↗️" if od.get("方向")=="看涨" else "跌 ↘️",
            "金额": f"${od.get('金额')}",
            "入场": f"{od.get('开仓价',0):,.2f}",
            "平仓": f"{pc:,.2f}" if pc else "运行中",
            "结果": od.get("结果") if od.get("结果") else f"{int(max(0,rem))}s"
        })
    st.table(df_show)
