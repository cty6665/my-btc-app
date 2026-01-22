import streamlit as st
import pandas as pd
import requests
import time
import json
import os
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==========================================
# 1. 配置与数据持久化
# ==========================================
st.set_page_config(page_title="BTC移动版交易系统", layout="wide")
DB_FILE = "user_data.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                for od in data['orders']:
                    od['开仓时间'] = datetime.strptime(od['开仓时间'], '%Y-%m-%d %H:%M:%S')
                    od['结算时间'] = datetime.strptime(od['结算时间'], '%Y-%m-%d %H:%M:%S')
                return data['balance'], data['orders']
        except: return 1000.0, []
    return 1000.0, []

def save_data(balance, orders):
    serialized = []
    for od in orders:
        temp = od.copy()
        temp['开仓时间'] = od['开仓时间'].strftime('%Y-%m-%d %H:%M:%S')
        temp['结算时间'] = od['结算时间'].strftime('%Y-%m-%d %H:%M:%S')
        if "结算K线时间" in temp: del temp["结算K线时间"]
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

# 初始化
if 'balance' not in st.session_state:
    b, o = load_data()
    st.session_state.balance = b
    st.session_state.orders = o

# ==========================================
# 2. 样式优化 (适配手机屏幕)
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #0B0E11; color: #EAECEF; }
    .price-text { font-family: 'Consolas', monospace; font-size: 32px; font-weight: bold; color: #0ECB81; }
    .pos-card { border-left: 5px solid #FCD535; padding: 10px; background: #1E2329; margin-bottom: 5px; border-radius: 4px; font-size: 14px; }
    @media (max-width: 640px) { .price-text { font-size: 24px; } }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 核心功能
# ==========================================
def get_data(symbol, interval='1m'):
    base_url = "https://api.binance.com"
    try:
        res = requests.get(f"{base_url}/api/v3/klines?symbol={symbol}&interval={interval}&limit=80", timeout=3).json()
        df = pd.DataFrame(res, columns=['time','open','high','low','close','v','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
        # 计算指标
        df['MB'] = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        df['UP'], df['DN'] = df['MB'] + 2*std, df['MB'] - 2*std
        return df['close'].iloc[-1], df, "OK"
    except Exception as e: return 0.0, pd.DataFrame(), str(e)

# 侧边栏
with st.sidebar:
    st.title("📱 移动交易端")
    symbol = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"])
    st.metric("账户余额", f"${st.session_state.balance:,.2f}")
    
    # 统计信息
    if st.session_state.orders:
        wins = len([o for o in st.session_state.orders if o.get('结果') == 'W'])
        total = len([o for o in st.session_state.orders if o['状态'] == '已结算'])
        rate = (wins/total*100) if total > 0 else 0
        st.write(f"📊 胜率: {rate:.1f}% (胜{wins}/总{total})")

    duration_mins = st.select_slider("结算时长(分)", options=[1, 5, 10, 30, 60, 1440])
    if st.button("重置系统"):
        st.session_state.orders, st.session_state.balance = [], 1000.0
        save_data(1000.0, [])
        st.rerun()

# 主界面
chart_spot = st.empty()
st.write("---")
amt = st.number_input("投入金额", 1.0, 10000.0, 10.0)
c1, c2 = st.columns(2)
buy_btn = c1.button("🟢 看涨 (BULL)", use_container_width=True)
sell_btn = c2.button("🔴 看跌 (BEAR)", use_container_width=True)
pos_spot = st.empty()

# 循环更新
while True:
    price, df, status = get_data(symbol)
    if status == "OK":
        now = datetime.now()
        
        # 处理买入
        if buy_btn or sell_btn:
            direction = "上涨" if buy_btn else "下跌"
            if st.session_state.balance >= amt:
                st.session_state.balance -= amt
                st.session_state.orders.append({
                    "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                    "方向": direction, "行权价": price, "金额": amt, "状态": "待结算", "结果": None, "币种": symbol
                })
                save_data(st.session_state.balance, st.session_state.orders)
                st.rerun()

        # 检查结算
        for od in st.session_state.orders:
            if od["状态"] == "待结算" and now >= od["结算时间"]:
                win = (od["方向"] == "上涨" and price > od["行权价"]) or (od["方向"] == "下跌" and price < od["行权价"])
                if win:
                    st.session_state.balance += od["金额"] * 1.8
                    od["状态"], od["结果"], od["颜色"] = "已结算", "W", "#0ECB81"
                else:
                    od["状态"], od["结果"], od["颜色"] = "已结算", "L", "#F6465D"
                save_data(st.session_state.balance, st.session_state.orders)

        # 渲染图表
        with chart_spot.container():
            st.markdown(f"{symbol}: <span class='price-text'>${price:,.2f}</span>", unsafe_allow_html=True)
            fig = go.Figure(data=[go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name="K")])
            fig.add_trace(go.Scatter(x=df['time'], y=df['MB'], line=dict(color='#FF00FF', width=1), name="中轨"))
            fig.update_layout(height=350, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True, key=f"{time.time()}")

        # 仓位显示
        with pos_spot.container():
            for od in reversed(st.session_state.orders[-5:]): # 手机端只显示最近5条
                rem = (od["结算时间"] - now).total_seconds()
                timer = f" | {int(rem//60)}m{int(rem%60)}s" if rem > 0 else ""
                st.markdown(f"""<div class="pos-card">
                    {od['币种']} | {od['方向']}@{od['行权价']:.2f} | {od['状态']} {od['结果'] or ''} {timer}
                </div>""", unsafe_allow_html=True)
                
    time.sleep(2)
