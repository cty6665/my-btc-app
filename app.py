import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置
# ==========================================
st.set_page_config(page_title="BTC Pro", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "user_data.json"

# 数据加载与保存 (保持你的逻辑)
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
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    b, o = load_data()
    st.session_state.balance, st.session_state.orders = b, o

# 初始化一个全局缓存，防止价格显示“闪烁”
if 'last_valid_price' not in st.session_state:
    st.session_state.last_valid_price = 0.0

# ==========================================
# 2. 必通价格获取逻辑
# ==========================================
def get_verified_price(symbol):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, params=params, timeout=1.5)
        if res.status_code == 200:
            price = float(res.json()[-1][4])
            st.session_state.last_valid_price = price # 存入缓存
            return price
    except:
        return None
    return None

# ==========================================
# 3. 页面布局
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    coin = st.selectbox("品种", ["BTCUSDT", "ETHUSDT"], index=0)
    # 周期加入 60 分钟 (1小时)
    duration_mins = st.selectbox("周期(分钟)", [1, 5, 10, 30, 60], index=2)
    amt = st.number_input("金额", 1.0, 10000.0, 50.0)
    
    if st.button("🚨 重置"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_data(1000.0, [])
        st.rerun()

# 尝试获取最新价
current_price = get_verified_price(coin)
# 如果这次没抓到，就用缓存的价格来维持显示和下单
display_price = current_price if current_price else st.session_state.last_valid_price

col_left, col_right = st.columns([3, 1])

with col_left:
    # 纯净 TradingView 图表
    tv_html = f"""
        <div id="tv-chart" style="height:500px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
          "theme": "light", "style": "1", "locale": "zh_CN",
          "container_id": "tv-chart", "hide_side_toolbar": false,
          "allow_symbol_change": true, "details": true,
          "studies": ["MAExp@tv-basicstudies"]
        }});
        </script>
    """
    components.html(tv_html, height=520)

with col_right:
    st.write("💰 余额")
    st.subheader(f"${st.session_state.balance:,.2f}")
    
    st.write("📈 实时执行价")
    if display_price > 0:
        # 使用更醒目的方式显示价格
        st.markdown(f"<h1 style='color:#02C076; font-family:monospace;'>{display_price:,.2f}</h1>", unsafe_allow_html=True)
    else:
        st.warning("正在连接行情...")

    # 下单按钮
    if st.button("🟢 看涨", use_container_width=True):
        if display_price > 0 and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": datetime.now(), "结算时间": datetime.now() + timedelta(minutes=duration_mins),
                "方向": "上涨", "行权价": display_price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

    st.write("") 

    if st.button("🔴 看跌", use_container_width=True):
        if display_price > 0 and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": datetime.now(), "结算时间": datetime.now() + timedelta(minutes=duration_mins),
                "方向": "下跌", "行权价": display_price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

# ==========================================
# 4. 自动结算
# ==========================================
now = datetime.now()
# 只要后台抓到了有效价格（current_price），不论前台是否延迟，自动结算
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "上涨" and current_price > od["行权价"]) or \
                  (od["方向"] == "下跌" and current_price < od["行权价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od["状态"], od["结果"] = "已结算", "W"
            else:
                od["状态"], od["结果"] = "已结算", "L"
            updated = True
    if updated:
        save_data(st.session_state.balance, st.session_state.orders)

# 历史记录
st.write("---")
for od in reversed(st.session_state.orders[-3:]):
    res = f" | {od['结果']}" if od['结果'] else ""
    st.info(f"{od['方向']} @{od['行权价']} | {od['状态']}{res}")

# 2秒强制刷新
time.sleep(2)
st.rerun()

