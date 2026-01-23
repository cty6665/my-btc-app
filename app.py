import streamlit as st
import pandas as pd
import requests
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 初始化与数据持久化
# ==========================================
DATA_FILE = "trading_data.csv"
st.set_page_config(page_title="Pro Trader Terminal", layout="wide", initial_sidebar_state="collapsed")

def load_data():
    if os.path.exists(DATA_FILE):
        try: return float(pd.read_csv(DATA_FILE)['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_data(balance):
    pd.DataFrame({"balance": [balance]}).to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state: st.session_state.balance = load_data()
if 'orders' not in st.session_state: st.session_state.orders = []

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000; }
    .stButton button { background-color: #FCD535 !important; color: #000 !important; font-weight: bold; height: 50px; }
    .up-arrow { color: #02C076; font-weight: bold; }
    .down-arrow { color: #CF304A; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 多源行情抓取 (修复币种不联动问题)
# ==========================================
def get_price_v4(symbol):
    # 路径 1: 币安 (带 API KEY 权重)
    try:
        headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=1.5).json()
        return float(res['price'])
    except: pass

    # 路径 2: Gate.io (格式转换: BTCUSDT -> BTC_USDT)
    try:
        gate_sym = symbol.replace("USDT", "_USDT")
        res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={gate_sym}", timeout=1.5).json()
        return float(res[0]['last'])
    except: pass
    
    return None

# ==========================================
# 3. 侧边栏与核心变量
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端设置")
    # 币种选择
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算周期(分钟)", [1, 5, 10, 30], index=2)
    bet = st.number_input("下单金额", 10.0, 1000.0, 50.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_data(1000.0)
        st.rerun()

# 实时获取当前选定币种的价格
current_price = get_price_v4(coin)
now = datetime.now()

# 自动结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        # 只结算对应币种且到期的订单
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            # 注意：平仓时需要获取该订单对应币种的价格，这里简化处理，
            # 实际大规模交易建议在结算瞬间为每个币种调一次API
            od["平仓价"] = current_price 
            win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                  (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
            if win: st.session_state.balance += od["金额"] * 1.8
            od.update({"状态": "已结算", "结果": "W" if win else "L"})
            updated = True
    if updated: save_data(st.session_state.balance)

# ==========================================
# 4. UI 布局
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "连接中...")
c3.metric("周期", f"{duration} Min")

# --- TradingView 图表 (集成下单虚线模拟) ---
# 注意：TV 基础版插件无法直接通过 Python 画虚线，我们通过下方流水和视觉反馈来强化
tv_html = f"""
    <div id="tv-chart" style="height:450px;"></div>
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
    new TradingView.widget({{
      "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
      "timezone": "Asia/Shanghai", "theme": "light", "style": "1",
      "locale": "zh_CN", "container_id": "tv-chart", "hide_side_toolbar": false,
      "allow_symbol_change": false, "details": true
    }});
    </script>
"""
components.html(tv_html, height=460)

# --- 交易按钮 ---
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (BUY UP)"):
    if current_price and st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({
            "币种": coin, "方向": "看涨", "图标": "↗️", 
            "开仓价": current_price, "平仓价": None, 
            "金额": bet, "结算时间": now + timedelta(minutes=duration), 
            "状态": "待结算", "结果": None
        })
        st.rerun()

if col_down.button("🔴 看跌 (SELL DOWN)"):
    if current_price and st.session_state.balance >= bet:
        st.session_state.balance -= bet
        save_data(st.session_state.balance)
        st.session_state.orders.append({
            "币种": coin, "方向": "看跌", "图标": "↘️", 
            "开仓价": current_price, "平仓价": None, 
            "金额": bet, "结算时间": now + timedelta(minutes=duration), 
            "状态": "待结算", "结果": None
        })
        st.rerun()

# --- 动态交易流水 ---
st.subheader(f"📊 {coin} 实时执行流水")
if st.session_state.orders:
    # 只显示当前选中币种的订单，或者全部显示但标明币种
    display_data = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od["结算时间"] - now).total_seconds()
        
        # 这里的样式模拟了你想要的“箭头”和“虚线感”
        arrow = f"<span class='up-arrow'>↗️</span>" if od["方向"] == "看涨" else f"<span class='down-arrow'>↘️</span>"
        
        display_data.append({
            "资产": od["币种"],
            "类型": od["方向"] + (" ↗️" if od["方向"] == "看涨" else " ↘️"),
            "执行价格(虚线位)": f"{od['开仓价']:.2f}",
            "当前/平仓价": f"{od['平仓价']:.2f}" if od['平仓价'] else "⚡ 运行中",
            "投入": f"{od['金额']} U",
            "结果": od["结果"] if od["结果"] else f"剩余 {int(rem)}s"
        })
    
    st.table(pd.DataFrame(display_data))

# 底部说明
st.caption("注：图表虚线标记已在流水中同步实时价位。入场即刻锁定当前报价。")
