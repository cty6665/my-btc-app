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

# 修正时差：获取北京时间
def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if isinstance(od.get(key), str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized_orders = []
    for od in orders:
        temp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if isinstance(temp.get(key), datetime):
                temp[key] = temp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized_orders}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

st.markdown("<style>.stApp{background:#FFF;}.stButton button{background:#FCD535!important;color:#000;font-weight:bold;height:55px;border-radius:10px;}</style>", unsafe_allow_html=True)
st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情获取 (绝对不改动)
# ==========================================
def get_price(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

# ==========================================
# 3. 界面与参数控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额 (U)", 10.0, 1000.0, 50.0)
    if st.button("🚨 清空记录并重置"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = get_beijing_time()

# 结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            p_close = get_price(od.get("资产", coin))
            if p_close:
                od["平仓价"] = p_close
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                      (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "W" if win else "L", "收益": (od["金额"] * 0.8) if win else -od["金额"]})
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 5. UI 布局
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "同步中")

# 图表
tv_html = f"""<div style="height:380px;"><script src="https://s3.tradingview.com/tv.js"></script>
<div id="tv-chart" style="height:380px;"></div>
<script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart","hide_side_toolbar":false,"allow_symbol_change":false,"studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
components.html(tv_html, height=380)

# 下单按钮 + 开仓动画 (st.status)
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在提交订单...", expanded=False) as status:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None,
                "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.5) # 动画停留
            status.update(label="✅ 开仓成功!", state="complete")
        st.toast(f"已下单: {coin} 看涨", icon="📈")
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在提交订单...", expanded=False) as status:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None,
                "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.5)
            status.update(label="✅ 开仓成功!", state="complete")
        st.toast(f"已下单: {coin} 看跌", icon="📉")
        st.rerun()

st.markdown("---")
# ==========================================
# 6. 历史记录 (增加：开仓时间、投入金额、平仓价格)
# ==========================================
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        
        # 处理显示逻辑
        p_close = od.get("平仓价")
        p_close_display = f"{p_close:,.2f}" if p_close else "运行中..."
        
        df_show.append({
            "开仓时间": od.get("开仓时间").strftime('%H:%M:%S') if od.get("开仓时间") else "-",
            "方向": "涨 ↗️" if od.get("方向") == "看涨" else "跌 ↘️",
            "金额": f"${od.get('金额')}",
            "入场价": f"{od.get('开仓价', 0):,.2f}",
            "平仓价": p_close_display,
            "盈亏": od.get("结果") if od.get("结果") else f"{int(max(0,rem))}s"
        })
    st.table(df_show)
