import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 基础配置
# ==========================================
st.set_page_config(page_title="Trade Pro", layout="wide", initial_sidebar_state="collapsed")

# 强制白色背景样式
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #EEE; }
    .price-text { font-family: 'Consolas', monospace; font-size: 32px; font-weight: bold; color: #02C076; }
    .pos-card { border-left: 5px solid #FCD535; padding: 10px; background: #F8F9FA; margin-bottom: 8px; border-radius: 8px; border: 1px solid #EEE; color: #000; }
    div[data-testid="stMetricValue"] { color: #000000 !important; font-size: 18px !important; }
    p, span, label { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

# 每 5 秒自动刷新一次页面
st_autorefresh(interval=5000, key="datarefresh")

# ==========================================
# 2. 初始化状态
# ==========================================
if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 3. 侧边栏配置
# ==========================================
with st.sidebar:
    st.header("⚙️ 设置")
    target_coin = st.selectbox("交易品种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    interval_choice = st.selectbox("K线周期", ['1m', '5m', '15m', '1h'], index=0)
    unit_map = {"5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60, "1天": 1440}
    selected_duration = st.radio("结算时长", list(unit_map.keys()), index=1)
    duration_mins = unit_map[selected_duration]
    if st.button("重置账户"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        st.rerun()

# ==========================================
# 4. 数据获取与结算逻辑
# ==========================================
def get_crypto_data(symbol, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=60"
    try:
        res = requests.get(url, timeout=3).json()
        df = pd.DataFrame(res, columns=['time','open','high','low','close','v','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
        return df['close'].iloc[-1], df
    except:
        return 0.0, pd.DataFrame()

price, df = get_crypto_data(target_coin, interval_choice)
now = datetime.now()

# 自动结算
for od in st.session_state.orders:
    if od["状态"] == "待结算" and now >= od["结算时间"]:
        win = (od["方向"] == "上涨" and price > od["开仓价"]) or (od["方向"] == "下跌" and price < od["开仓价"])
        if win:
            st.session_state.balance += od["金额"] * 1.8
            od.update({"状态": "已结算", "结果": "WIN", "颜色": "#02C076"})
        else:
            od.update({"状态": "已结算", "结果": "LOSS", "颜色": "#CF304A"})

# 统计看板数据
orders = st.session_state.orders
finished_orders = [od for od in orders if od['状态']=='已结算']
total_profit = sum([(od['金额']*0.8 if od['结果']=='WIN' else -od['金额']) for od in finished_orders])
win_rate = (len([od for od in finished_orders if od['结果']=='WIN']) / len(finished_orders) * 100) if finished_orders else 0.0

# ==========================================
# 5. 主界面渲染
# ==========================================
# 顶部统计
c1, c2, c3 = st.columns(3)
c1.metric("当日盈亏", f"${total_profit:.2f}")
c2.metric("总盈亏", f"${total_profit:.2f}")
c3.metric("胜率", f"{win_rate:.1f}%")

st.divider()

# 价格显示
st.markdown(f"**{target_coin}** <span class='price-text'>${price:,.2f}</span> (余额: ${st.session_state.balance:.2f})", unsafe_allow_html=True)

# K线图表
if not df.empty:
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#02C076', decreasing_line_color='#CF304A'
    )])
    fig.update_layout(
        height=400, template="plotly_white", margin=dict(l=0,r=0,t=0,b=0),
        xaxis_rangeslider_visible=False
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.warning("正在加载K线数据...")

# 下单操作
st.subheader("⚡ 快速下单")
order_amt = st.number_input("下单金额 (U)", 10.0, 5000.0, 50.0)
col_buy, col_sell = st.columns(2)

if col_buy.button("🟢 看涨 (BULL)", use_container_width=True, type="primary"):
    if st.session_state.balance >= order_amt:
        st.session_state.balance -= order_amt
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "上涨", "开仓价": price, "金额": order_amt, "状态": "待结算", "结果": None
        })
        st.rerun()

if col_sell.button("🔴 看跌 (BEAR)", use_container_width=True):
    if st.session_state.balance >= order_amt:
        st.session_state.balance -= order_amt
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "下跌", "开仓价": price, "金额": order_amt, "状态": "待结算", "结果": None
        })
        st.rerun()

# 订单列表
st.divider()
st.write("📋 最近记录")
for od in reversed(st.session_state.orders[-5:]):
    res_color = od.get("颜色", "#FCD535")
    st.markdown(f"""
    <div class="pos-card">
        <b>{od['方向']}</b> | 开仓: ${od['开仓价']:.2f} | {od['金额']}U | 
        <span style="color:{res_color}">{od['状态']} {od['结果'] if od['结果'] else ''}</span>
    </div>
    """, unsafe_allow_html=True)
