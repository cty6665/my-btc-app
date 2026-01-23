import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置 (使用你习惯的 user_data.json)
# ==========================================
st.set_page_config(page_title="BTC Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "user_data.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                # 转换时间格式
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
# 2. 核心：移植你验证过的“必通”报价逻辑
# ==========================================
def get_verified_price(symbol):
    try:
        # 使用你代码 验证过的 klines 接口
        base_url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(base_url, params=params, timeout=2)
        if res.status_code == 200:
            return float(res.json()[-1][4]) # 获取最新收盘价
        return None
    except:
        return None

# ==========================================
# 3. 页面布局
# ==========================================
# 侧边栏控制
with st.sidebar:
    st.title("⚙️ 终端控制")
    coin = st.selectbox("交易品种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    # 按照你的需求：增加 1小时 (60分) 选项
    duration_mins = st.select_slider("结算时长(分)", options=[1, 5, 10, 30, 60])
    amt = st.number_input("下单金额", 1.0, 10000.0, 50.0)
    
    if st.button("🚨 重置系统"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_data(1000.0, [])
        st.rerun()

# 获取当前下单价
price = get_verified_price(coin)
now = datetime.now()

# 主界面：左图右控
col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # 只保留这一个 TradingView 图表，彻底解决“两个图表”问题
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
    components.html(tv_html, height=550)

with col_trade:
    st.metric("可用余额", f"${st.session_state.balance:,.2f}")
    if price:
        st.success(f"实时执行价: ${price:,.2f}")
    else:
        st.error("报价重连中...")

    # 下单按钮加固
    if st.button("🟢 看涨 (BULL)", use_container_width=True):
        if price and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "上涨", "行权价": price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

    st.write("") 

    if st.button("🔴 看跌 (BEAR)", use_container_width=True):
        if price and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "下跌", "行权价": price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.rerun()

# ==========================================
# 4. 自动结算与刷新 (每2秒同步一次)
# ==========================================
# 检查到期订单
if price:
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "上涨" and price > od["行权价"]) or \
                  (od["方向"] == "下跌" and price < od["行权价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od["状态"], od["结果"] = "已结算", "W"
            else:
                od["状态"], od["结果"] = "已结算", "L"
            save_data(st.session_state.balance, st.session_state.orders)

# 显示最近记录
st.write("---")
for od in reversed(st.session_state.orders[-3:]):
    res_tag = f" | {od['结果']}" if od['结果'] else ""
    st.write(f"【{od['状态']}{res_tag}】{od['币种']} {od['方向']} @{od['行权价']}")

# 模拟你代码 的 2 秒刷新
time.sleep(2)
st.rerun()

