import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 强化数据库逻辑 (记录与余额同步保存)
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Pro Hybrid", layout="wide", initial_sidebar_state="collapsed")

def load_db():
    """从JSON加载所有数据，确保重启不丢失记录"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            # 时间格式转换回对象
            for od in data.get('orders', []):
                od['结算时间'] = datetime.strptime(od['结算时间'], '%Y-%m-%d %H:%M:%S')
            return data.get('balance', 1000.0), data.get('orders', [])
    return 1000.0, []

def save_db(balance, orders):
    """保存余额和所有订单到JSON"""
    serialized_orders = []
    for od in orders:
        temp = od.copy()
        if isinstance(temp['结算时间'], datetime):
            temp['结算时间'] = temp['结算时间'].strftime('%Y-%m-%d %H:%M:%S')
        serialized_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized_orders}, f)

# 初始化：从文件读取，不再只靠内存
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# 样式
st.markdown("<style>.stApp{background:#FFF;}.stButton button{background:#FCD535!important;color:#000;font-weight:bold;}</style>", unsafe_allow_html=True)
st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 增强型行情获取 (支持指定币种)
# ==========================================
def get_price(symbol):
    """支持传入特定symbol，解决以太变比特的问题"""
    try:
        # 路径 A: 币安 API Key 通行证
        headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        try:
            # 路径 B: Gate.io 备用
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

# ==========================================
# 3. 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("周期(分)", [1, 5, 10], index=0)
    bet = st.number_input("下单金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 清空所有记录并充值"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = datetime.now()

# ==========================================
# 4. 结算逻辑 (修复结算错位核心Bug)
# ==========================================
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            # 💡 核心修复：根据订单里存的币种(od['资产'])去取价，而不是用当前选中的coin
            p_close = get_price(od["资产"]) 
            if p_close:
                od["平仓价"] = p_close
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                      (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "W" if win else "L"})
                updated = True
    if updated: 
        save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 5. UI 与 下单
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "连接中")

# TV 图表
tv_html = f"""<div style="height:400px;"><script src="https://s3.tradingview.com/tv.js"></script>
<script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart"}});</script>
<div id="tv-chart" style="height:400px;"></div></div>"""
components.html(tv_html, height=400)

col_up, col_down = st.columns(2)
# 下单：同时更新内存和硬盘
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders) # 立即保存
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders) # 立即保存
        st.rerun()

# 历史记录展示
st.subheader("📋 历史记录 (永久保存)")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od["结算时间"] - now).total_seconds()
        df_show.append({
            "资产": od["资产"],
            "方向": "上涨 ↗️" if od["方向"] == "看涨" else "下跌 ↘️",
            "开仓基准": f"{od['开仓价']:.2f}",
            "平仓价格": f"{od['平仓价']:.2f}" if od['平仓价'] else "运行中",
            "盈亏": od["结果"] if od["结果"] else f"{int(rem)}s"
        })
    st.table(df_show)
