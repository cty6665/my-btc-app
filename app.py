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
st.set_page_config(page_title="BTC Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "user_data.json"

# 数据加载函数保持不变...
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
# 2. 价格获取逻辑 (加固版)
# ==========================================
def get_verified_price(symbol):
    try:
        # 尝试你验证过的 klines 接口
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 1}
        res = requests.get(url, params=params, timeout=1.2)
        if res.status_code == 200:
            return float(res.json()[-1][4])
        return None
    except:
        return None

# ==========================================
# 3. 页面布局
# ==========================================
with st.sidebar:
    st.title("⚙️ 终端控制")
    coin = st.selectbox("交易品种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    
    # 核心：手动价格补丁 (如果右侧显示“重连中”，请在这里填入你看到的图表价格)
    st.markdown("---")
    manual_p = st.number_input("🛠️ 手动同步价(API不通时填此)", value=0.0, format="%.2f", help="若实时执行价获取不到，请参考图表填入此项")
    
    duration_mins = st.selectbox("结算时长", [1, 5, 10, 30, 60, 240], index=2)
    amt = st.number_input("下单金额", 1.0, 10000.0, 50.0)
    
    if st.button("🚨 重置系统"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_data(1000.0, [])
        st.rerun()

# 获取价格：优先 API，失败则用手动输入的价格
price = get_verified_price(coin)
if not price and manual_p > 0:
    price = manual_p

now = datetime.now()

# 主界面
col_chart, col_trade = st.columns([3, 1])

with col_chart:
    # 唯一的 TV 图表
    tv_html = f"""
        <div id="tv-chart" style="height:550px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
          "theme": "light", "style": "1", "locale": "zh_CN",
          "container_id": "tv-chart", "hide_side_toolbar": false,
          "allow_symbol_change": true, "details": true,
          "studies": ["MAExp@tv-basicstudies", "BollingerBandsUpper@tv-basicstudies"]
        }});
        </script>
    """
    components.html(tv_html, height=560)

with col_trade:
    st.metric("可用余额", f"${st.session_state.balance:,.2f}")
    
    if price:
        # 这里变绿了说明下单功能已激活
        st.success(f"实时执行价: ${price:,.2f}")
    else:
        st.error("⚠️ 接口阻塞：请在侧边栏手动输入价格")

    # 下单按钮
    if st.button("🟢 看涨 (UP)", use_container_width=True):
        if price and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "上涨", "行权价": price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.toast("下单成功！")
            st.rerun()
        elif not price:
            st.warning("无价格无法交易")

    st.write("") 

    if st.button("🔴 看跌 (DOWN)", use_container_width=True):
        if price and st.session_state.balance >= amt:
            st.session_state.balance -= amt
            st.session_state.orders.append({
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
                "方向": "下跌", "行权价": price, "金额": amt, "状态": "待结算", "结果": None, "币种": coin
            })
            save_data(st.session_state.balance, st.session_state.orders)
            st.toast("下单成功！")
            st.rerun()
        elif not price:
            st.warning("无价格无法交易")

# ==========================================
# 4. 自动结算
# ==========================================
if price:
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            # 使用结算时的价格对比
            win = (od["方向"] == "上涨" and price > od["行权价"]) or \
                  (od["方向"] == "下跌" and price < od["行权价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od["状态"], od["结果"] = "已结算", "W"
            else:
                od["状态"], od["结果"] = "已结算", "L"
            save_data(st.session_state.balance, st.session_state.orders)

st.write("---")
st.subheader("📜 交易历史")
for od in reversed(st.session_state.orders[-3:]):
    res_info = f" | {od['结果']}" if od['结果'] else ""
    st.info(f"{od['方向']} @{od['行权价']} | 状态: {od['状态']}{res_info}")

# 2秒刷新
time.sleep(2)
st.rerun()

