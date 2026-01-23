import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

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
                    if isinstance(od.get('结算时间'), str):
                        od['结算时间'] = datetime.strptime(od['结算时间'], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized_orders = []
    for od in orders:
        temp = od.copy()
        if isinstance(temp.get('结算时间'), datetime):
            temp['结算时间'] = temp['结算时间'].strftime('%Y-%m-%d %H:%M:%S')
        serialized_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized_orders}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# --- 【手机优化点 1】增强型 CSS 注入 ---
st.markdown("""
<style>
    .stApp { background:#FFF; }
    /* 下单按钮在手机上变得更大、更好按 */
    .stButton button { 
        background:#FCD535 !important; 
        color:#000 !important; 
        font-weight:bold !important;
        height: 60px !important; /* 增加高度 */
        font-size: 18px !important; /* 字体加大 */
        border-radius: 10px !important;
    }
    /* 针对手机窄屏减少容器边距 */
    @media (max-width: 640px) {
        .block-container { padding: 1rem 0.5rem !important; }
        .stMetric { margin-bottom: 0.5rem !important; }
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
now = datetime.now()

# 结算逻辑 (保持原样)
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
# 4. 数据统计计算
# ==========================================
settled_orders = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
today_str = now.strftime('%Y-%m-%d')
today_orders = [o for o in settled_orders if o.get("结算时间").strftime('%Y-%m-%d') == today_str]
today_pnl = sum([o.get("收益", 0) for o in today_orders])
today_win_rate = (len([o for o in today_orders if o.get("结果") == "W"]) / len(today_orders) * 100) if today_orders else 0
total_pnl = sum([o.get("收益", 0) for o in settled_orders])
total_win_rate = (len([o for o in settled_orders if o.get("结果") == "W"]) / len(settled_orders) * 100) if settled_orders else 0

# ==========================================
# 5. UI 布局 (自适应优化)
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "同步中")

# --- 【手机优化点 2】指标预装版图表 ---
tv_html = f"""
<div style="height:400px;">
    <script src="https://s3.tradingview.com/tv.js"></script>
    <div id="tv-chart" style="height:400px;"></div>
    <script>
    new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{coin}",
        "interval": "1",
        "theme": "light",
        "style": "1",
        "locale": "zh_CN",
        "container_id": "tv-chart",
        "hide_side_toolbar": false,
        "allow_symbol_change": false,
        "timezone": "Asia/Shanghai",
        "hide_volume": false,
        "studies": [
            "BB@tv-basicstudies",      // 布林带
            "MACD@tv-basicstudies"     // MACD
        ]
    }});
    </script>
</div>
"""
components.html(tv_html, height=400)

# 下单按钮 (并排显示)
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None,
            "金额": bet, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# 战报展示
st.markdown(f"""
---
### 📈 实时战报
| 统计维度 | 今日盈亏 | 今日胜率 | 总盈亏 | 总胜率 |
| :--- | :--- | :--- | :--- | :--- |
| **数值** | <span style='color:{"green" if today_pnl >= 0 else "red"}'>${today_pnl:.2f}</span> | {today_win_rate:.1f}% | <span style='color:{"green" if total_pnl >= 0 else "red"}'>${total_pnl:.2f}</span> | {total_win_rate:.1f}% |
""", unsafe_allow_html=True)

# 历史记录
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        df_show.append({
            "资产": od.get("资产", "未知"),
            "方向": "上涨 ↗️" if od.get("方向") == "看涨" else "下跌 ↘️",
            "开仓基准": f"{od.get('开仓价', 0):,.2f}",
            "平仓/实时": f"{od.get('平仓价', 0):,.2f}" if od.get('平仓价') else "运行中",
            "盈亏结果": od.get("结果") if od.get("结果") else f"{int(rem)}s"
        })
    st.table(df_show)
