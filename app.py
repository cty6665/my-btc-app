import streamlit as st
import pandas as pd
import requests
import time
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 核心持久化存储 (完全兼容模式)
# ==========================================
st.set_page_config(page_title="BTC Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "user_data.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                for od in orders:
                    # 强行转换时间，确保万无一失
                    if isinstance(od['开仓时间'], str):
                        od['开仓时间'] = datetime.strptime(od['开仓时间'], '%Y-%m-%d %H:%M:%S')
                    if isinstance(od['结算时间'], str):
                        od['结算时间'] = datetime.strptime(od['结算时间'], '%Y-%m-%d %H:%M:%S')
                return balance, orders
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
# 2. 价格获取 (完全复刻你 100 行代码的逻辑)
# ==========================================
def get_verified_price(symbol):
    # 这是你代码中最稳的 K 线接口路径
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, params=params, timeout=1.5)
        if res.status_code == 200:
            return float(res.json()[-1][4]) # 取最新 K 线收盘价
    except:
        pass
    # 备用路径
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1)
        return float(res.json()['price'])
    except:
        return None

# ==========================================
# 3. 页面布局
# ==========================================
with st.sidebar:
    st.title("⚙️ 终端控制")
    coin = st.selectbox("币种", ["BTCUSDT", "ETHUSDT"])
    duration = st.selectbox("周期(分)", [1, 5, 10, 30, 60], index=2)
    amt = st.number_input("金额", 1.0, 10000.0, 50.0)
    if st.button("🚨 重置系统"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_data(1000.0, [])
        st.rerun()

current_price = get_verified_price(coin)
now = datetime.now()

col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # TV 图表
    tv_html = f"""
        <div id="tv-chart" style="height:480px;"></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>
        new TradingView.widget({{"autosize": true, "symbol": "BINANCE:{coin}", "interval": "1", "theme": "light", "style": "1", "locale": "zh_CN", "container_id": "tv-chart"}});
        </script>
    """
    components.html(tv_html, height=500)

with col_trade:
    st.metric("可用余额", f"${st.session_state.balance:,.2f}")
    if current_price:
        st.success(f"实时执行价: {current_price:,.2f}")
    else:
        st.error("报价获取中...")

    # 下单逻辑
    if st.button("🟢 看涨", use_container_width=True) and current_price:
        if st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "方向": "涨", "开仓价": current_price, "平仓价": None,
                "金额": amt, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
                "状态": "等待中", "结果": None
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

    if st.button("🔴 看跌", use_container_width=True) and current_price:
        if st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "方向": "跌", "开仓价": current_price, "平仓价": None,
                "金额": amt, "开仓时间": now, "结算时间": now + timedelta(minutes=duration),
                "状态": "等待中", "结果": None
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

# ==========================================
# 4. 自动化结算
# ==========================================
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "等待中" and now >= od["结算时间"]:
            od["平仓价"] = current_price
            win = (od["方向"] == "涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "跌" and od["平仓价"] < od["开仓价"])
            st.session_state.balance += (od["金额"] * 1.8) if win else 0
            od["状态"], od["结果"] = "已结算", ("W" if win else "L")
            updated = True
    if updated: save_data(st.session_state.balance, st.session_state.orders)

# ==========================================
# 5. 交易记录 (修复 KeyError 关键区)
# ==========================================
st.divider()
st.subheader("📋 交易流水")

if st.session_state.orders:
    display_list = []
    for od in reversed(st.session_state.orders[-10:]):
        # 增加容错处理：检查键是否存在
        settle_time = od.get("结算时间", now)
        rem = (settle_time - now).total_seconds()
        
        display_list.append({
            "方向": od.get("方向"),
            "开仓价": od.get("开仓价"),
            "平仓价": od.get("平仓价") if od.get("平仓价") else "---",
            "金额": od.get("金额"),
            "结果": od.get("结果") if od.get("结果") else (f"{int(rem)}s" if rem > 0 else "计算中")
        })
    st.table(pd.DataFrame(display_list))

time.sleep(3)
st.rerun()
