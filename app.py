import streamlit as st
import pandas as pd
import requests
import time
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 核心持久化存储
# ==========================================
st.set_page_config(page_title="BTC Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
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
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    b, o = load_data()
    st.session_state.balance, st.session_state.orders = b, o

# ==========================================
# 2. 必通报价逻辑
# ==========================================
def get_verified_price(symbol):
    urls = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
        f"https://api3.binance.com/api/v3/ticker/price?symbol={symbol}"
    ]
    for url in urls:
        try:
            res = requests.get(url, timeout=1.2)
            if res.status_code == 200:
                return float(res.json()['price'])
        except: continue
    return None

# ==========================================
# 3. 页面布局
# ==========================================
coin = st.sidebar.selectbox("选择币种", ["BTCUSDT", "ETHUSDT"], index=0)
duration = st.sidebar.selectbox("结算周期(分钟)", [1, 5, 10, 30, 60], index=2) # 默认10分钟
amt = st.sidebar.number_input("下单金额", 1.0, 10000.0, 50.0)

current_price = get_verified_price(coin)
now = datetime.now()

col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # TradingView 插件（不闪烁）
    tv_html = f"""
        <div id="tv-chart" style="height:500px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget({{"autosize": true, "symbol": "BINANCE:{coin}", "interval": "1", "theme": "light", "style": "1", "locale": "zh_CN", "container_id": "tv-chart"}});
        </script>
    """
    components.html(tv_html, height=520)

with col_trade:
    st.metric("可用余额", f"${st.session_state.balance:,.2f}")
    if current_price:
        st.success(f"实时价格: {current_price:,.2f}")
    else:
        st.error("报价获取中...")

    if st.button("🟢 看涨 (UP)", use_container_width=True) and current_price:
        if st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "币种": coin, "方向": "涨", "开仓价": current_price, "平仓价": None,
                "金额": amt, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
                "状态": "等待中", "结果": None
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

    if st.button("🔴 看跌 (DOWN)", use_container_width=True) and current_price:
        if st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "币种": coin, "方向": "跌", "开仓价": current_price, "平仓价": None,
                "金额": amt, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
                "状态": "等待中", "结果": None
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

# ==========================================
# 4. 自动结算逻辑（核心修改点）
# ==========================================
if current_price:
    updated = False
    for od in st.session_state.orders:
        # 只要当前时间 > 订单结算时间，且订单还是等待状态
        if od["状态"] == "等待中" and now >= od["结算时间"]:
            od["平仓价"] = current_price # 记录结算瞬间的价格
            win = (od["方向"] == "涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "跌" and od["平仓价"] < od["开仓价"])
            
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od["状态"], od["结果"] = "已完成", "W"
            else:
                od["状态"], od["结果"] = "已完成", "L"
            updated = True
    if updated:
        save_data(st.session_state.balance, st.session_state.orders)

# ==========================================
# 5. 详细交易历史（显示开仓+平仓价）
# ==========================================
st.divider()
st.subheader("📋 交易流水 (含开平仓对比)")

if not st.session_state.orders:
    st.info("暂无交易记录")
else:
    # 转换为表格显示，更清晰
    history = []
    for od in reversed(st.session_state.orders[-10:]):
        # 计算剩余秒数
        remaining = (od["结算时间"] - now).total_seconds()
        countdown = f"{int(remaining)}s" if remaining > 0 else "已结算"
        
        history.append({
            "方向": od["方向"],
            "金额": od["金额"],
            "开仓价": od["开仓价"],
            "平仓价": od["平仓价"] if od["平仓价"] else "待定",
            "状态": od["状态"],
            "结果": od["结果"] if od["结果"] else countdown
        })
    st.table(history)

# 3秒强制刷新
time.sleep(3)
st.rerun()

