import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 初始化与数据库
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance, orders = data.get('balance', 1000.0), data.get('orders', [])
                for od in orders:
                    for key in ['开仓时间', '结算时间', '平仓时间']:
                        if od.get(key) and isinstance(od[key], str) and od[key] != "-":
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        temp = od.copy()
        for key in ['开仓时间', '结算时间', '平仓时间']:
            if isinstance(temp.get(key), datetime):
                temp[key] = temp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f, indent=4)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情获取
# ==========================================
def get_price(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except: return None

# ==========================================
# 3. 界面逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制面板")
    coin = st.selectbox("交易资产", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("金额", 10.0, 5000.0, 100.0)
    if st.button("🚨 重置"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = datetime.now()

# 结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            p_close = get_price(od["资产"])
            if p_close:
                od["平仓价"], od["平仓时间"] = p_close, now
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                      (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "W" if win else "L", "收益": (od["金额"]*0.8 if win else -od["金额"])})
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 4. 【全网唯一】稳定渲染：TV + 价格参考线
# ==========================================
# 我们在这里只渲染一个组件，防止出现两个图
active_lines = [o['开仓价'] for o in st.session_state.orders if o['状态'] == '待结算' and o['资产'] == coin]

# 这种方式直接在侧边栏显示价格标记，因为 TV 内部 API 限制太多，
# 我们在图表上方用简单的 HTML 标记来显示你的“入场警戒位”
lines_html = "".join([f"<div style='color:#02C076; font-size:12px;'>➔ 已入场: {p}</div>" for p in active_lines])

tv_combined_html = f"""
<div style="position:relative; width:100%; height:450px; background:#fff;">
    <div id="tv_container" style="width:100%; height:100%;"></div>
    <div id="overlay" style="position:absolute; top:10px; right:10px; pointer-events:none; font-family:sans-serif;">
        {lines_html}
    </div>
</div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
    new TradingView.widget({{
        "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
        "theme": "light", "style": "1", "locale": "zh_CN", "container_id": "tv_container",
        "hide_side_toolbar": false, "allow_symbol_change": false, "timezone": "Asia/Shanghai"
    }});
</script>
"""

# ==========================================
# 5. UI 渲染
# ==========================================
c1, c2 = st.columns(2)
c1.metric("可用余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 现价", f"${current_price:,.2f}" if current_price else "Loading...")

# 只调用这一次 components.html，确保只有一个图
components.html(tv_combined_html, height=460)

col_up, col_down = st.columns(2)
btn_style = {"use_container_width": True}
if col_up.button("🟢 看涨 (UP)", **btn_style) and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)", **btn_style) and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# 交易流水
st.subheader("📋 执行流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        res = od.get("结果", "进行中")
        df_show.append({
            "资产": od['资产'], "方向": od['方向'], "开仓价": od['开仓价'],
            "开仓时间": od['开仓时间'].strftime('%H:%M:%S'), "状态": res
        })
    st.table(df_show)

