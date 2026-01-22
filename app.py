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

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    [data-testid="stSidebar"] { background-color: #F8F9FA; border-right: 1px solid #EEE; }
    .price-text { font-family: 'Consolas', monospace; font-size: 32px; font-weight: bold; color: #02C076; }
    .pos-card { border-left: 5px solid #FCD535; padding: 10px; background: #F8F9FA; margin-bottom: 8px; border-radius: 8px; border: 1px solid #EEE; color: #000; }
    div[data-testid="stMetricValue"] { color: #000000 !important; }
    p, span, label { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

# 自动刷新 (5秒)
st_autorefresh(interval=5000, key="datarefresh")

if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 2. 增强型数据获取函数
# ==========================================
def get_crypto_data(symbol, interval):
    # 尝试使用不同的币安 API 节点以增加稳定性
    endpoints = [
        f"https://api.binance.com/api/v3/klines",
        f"https://api1.binance.com/api/v3/klines",
        f"https://api2.binance.com/api/v3/klines"
    ]
    params = {"symbol": symbol, "interval": interval, "limit": 60}
    for url in endpoints:
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                df = pd.DataFrame(data, columns=['time','open','high','low','close','v','ct','qa','tr','tb','tq','ig'])
                df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
                for col in ['open','high','low','close']: df[col] = df[col].astype(float)
                return df['close'].iloc[-1], df
        except:
            continue
    return None, None

# ==========================================
# 3. 侧边栏
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

# 获取数据
price, df = get_crypto_data(target_coin, interval_choice)
now = datetime.now()

# 自动结算逻辑
if price:
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "上涨" and price > od["开仓价"]) or (od["方向"] == "下跌" and price < od["开仓价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "WIN", "颜色": "#02C076"})
            else:
                od.update({"状态": "已结算", "结果": "LOSS", "颜色": "#CF304A"})

# 统计
finished = [od for od in st.session_state.orders if od['状态']=='已结算']
profit = sum([(od['金额']*0.8 if od['结果']=='WIN' else -od['金额']) for od in finished])
win_rate = (len([od for od in finished if od['结果']=='WIN']) / len(finished) * 100) if finished else 0.0

# ==========================================
# 4. 主界面渲染
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("总盈亏", f"${profit:.2f}")
c2.metric("胜率", f"{win_rate:.1f}%")
c3.metric("余额", f"${st.session_state.balance:.1f}")

st.divider()

if price is not None and not df.empty:
    st.markdown(f"**{target_coin}** <span class='price-text'>${price:,.2f}</span>", unsafe_allow_html=True)
    
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#02C076', decreasing_line_color='#CF304A'
    )])
    fig.update_layout(height=400, template="plotly_white", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.error("⚠️ 无法连接行情接口，请稍后刷新页面或检查网络。")

# 下单区
st.subheader("⚡ 快速下单")
order_amt = st.number_input("金额 (U)", 10.0, 5000.0, 50.0)
col_buy, col_sell = st.columns(2)

if col_buy.button("🟢 看涨", use_container_width=True, type="primary"):
    if st.session_state.balance >= order_amt:
        st.session_state.balance -= order_amt
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "上涨", "开仓价": price, "金额": order_amt, "状态": "待结算", "结果": None
        })
        st.rerun()

if col_sell.button("🔴 看跌", use_container_width=True):
    if st.session_state.balance >= order_amt:
        st.session_state.balance -= order_amt
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "下跌", "开仓价": price, "金额": order_amt, "状态": "待结算", "结果": None
        })
        st.rerun()

# 记录列表
st.write("📋 最近记录")
for od in reversed(st.session_state.orders[-5:]):
    res_color = od.get("颜色", "#FCD535")
    st.markdown(f"""
    <div class="pos-card">
        <b>{od['方向']}</b> ${od['开仓价']:.2f} | {od['金额']}U | 
        <span style="color:{res_color}">{od['状态']} {od['结果'] if od['结果'] else ''}</span>
    </div>
    """, unsafe_allow_html=True)
