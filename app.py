import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import time

# ==========================================
# 1. 数据库持久化
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间', '平仓时间']:
                        if isinstance(od.get(key), str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized_orders = []
    for od in orders:
        temp = od.copy()
        for key in ['结算时间', '开仓时间', '平仓时间']:
            if isinstance(temp.get(key), datetime):
                temp[key] = temp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized_orders}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# --- 【UI & 手机美化注入】 ---
st.markdown("""
<style>
    .stApp { background:#FFF; }
    /* 按钮美化 */
    .stButton button { 
        background:#FCD535 !important; 
        color:#000 !important; 
        font-weight:bold !important;
        height: 60px !important;
        font-size: 18px !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* 表格紧凑化美化 */
    .stTable td, .stTable th {
        padding: 4px 8px !important;
        font-size: 13px !important;
    }
    @media (max-width: 640px) {
        .block-container { padding: 0.5rem !important; }
        .stMetric { margin-bottom: 0px !important; }
    }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情获取
# ==========================================
def get_price(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        return None

# ==========================================
# 3. 界面控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("周期", [5, 10, 30, 60], format_func=lambda x: f"{x}分", index=0)
    bet = st.number_input("下单金额 (U)", 10.0, 1000.0, 50.0)
    if st.button("🚨 清空重置"):
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
            p_close = get_price(od.get("资产", coin))
            if p_close:
                od["平仓价"] = p_close
                od["平仓时间"] = now
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                      (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                profit_loss = (od["金额"] * 0.8) if win else -od["金额"]
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "W" if win else "L", "收益": profit_loss})
                updated = True
                st.toast(f"{'💰 盈利' if win else '📉 亏损'} ${abs(profit_loss):.2f}", icon="📢")
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 4. 数据统计
# ==========================================
settled_orders = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
total_pnl = sum([o.get("收益", 0) for o in settled_orders])
total_win_rate = (len([o for o in settled_orders if o.get("结果") == "W"]) / len(settled_orders) * 100) if settled_orders else 0

# ==========================================
# 5. UI 布局
# ==========================================
c1, c2 = st.columns(2)
c1.metric("可用余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 现价", f"${current_price:,.2f}" if current_price else "📡")

# 图表
tv_html = f"""<div style="height:380px;"><script src="https://s3.tradingview.com/tv.js"></script>
<div id="tv-chart" style="height:380px;"></div>
<script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart","hide_side_toolbar":false,"allow_symbol_change":false,"studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
components.html(tv_html, height=380)

# 下单区
col_up, col_down = st.columns(2)
if col_up.button("🟢 BUY / 看涨") and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交中...", expanded=False):
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "平仓时间": None, "状态": "待结算", "结果": None, "收益": 0})
            save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

if col_down.button("🔴 SELL / 看跌") and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交中...", expanded=False):
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "平仓时间": None, "状态": "待结算", "结果": None, "收益": 0})
            save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# 紧凑流水表
st.markdown("---")
st.subheader("📋 交易流水")
if st.session_state.orders:
    history = []
    for od in reversed(st.session_state.orders[-12:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        history.append({
            "方向": "上涨 ↗️" if od["方向"] == "看涨" else "下跌 ↘️",
            "数额": f"${od['金额']}",
            "入场价": f"{od['开仓价']:,.2f}",
            "开仓时间": od['开仓时间'].strftime('%H:%M:%S'),
            "状态/离场": od['平仓时间'].strftime('%H:%M:%S') if od.get('平仓时间') else f"{int(max(0,rem))}s",
            "盈亏": f"${od['收益']:+.2f}" if od['状态'] == "已结算" else "⏳"
        })
    st.table(history)
