import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 页面配置与 UI 增强 (针对手机端优化)
# ==========================================
st.set_page_config(
    page_title="Gemini Pro Terminal",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    /* 全局样式 */
    .stApp { background-color: #FFFFFF; color: #000; }
    
    /* 指标卡片 */
    .metric-card { 
        background: #f8f9fa; padding: 12px; border-radius: 10px; 
        border-left: 5px solid #FCD535; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }

    /* 下单按钮：手机端超大尺寸，方便盲操 */
    .stButton>button {
        width: 100% !important;
        height: 70px !important;
        font-size: 22px !important;
        font-weight: bold !important;
        border-radius: 12px !important;
        margin-bottom: 5px;
    }
    
    /* 移动端间距微调 */
    @media (max-width: 640px) {
        .block-container { padding: 0.5rem !important; }
        .stMetric { margin-bottom: 0px !important; }
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 数据库持久化逻辑
# ==========================================
DB_FILE = "trading_db.json"
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['开仓时间', '结算时间', '平仓时间']:
                        if od.get(key) and isinstance(od[key], str) and od[key] != "-":
                            try: od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                            except: pass
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

# 5秒全局自动刷新
st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 3. 核心行情接口
# ==========================================
def get_price(symbol):
    # 使用备用接口确保不挂加速器也能尽可能访问
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except:
        return None

# ==========================================
# 4. 侧边栏控制面板
# ==========================================
with st.sidebar:
    st.header("⚙️ 交易设置")
    coin = st.selectbox("选择币种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算时间", [5, 10, 30, 60], format_func=lambda x: f"{x}分钟")
    bet = st.number_input("下单金额 (U)", 10.0, 5000.0, 100.0)
    if st.button("🚨 清空所有数据"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = datetime.now()

# 自动结算逻辑
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
# 5. 【核心】指标预装版图表渲染
# ==========================================
# 已锁定指标：MACD + Bollinger Bands + Volume
tv_html = f"""
<div id="tv_container" style="height:380px;"></div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
    new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{coin}",
        "interval": "1",
        "theme": "light",
        "style": "1",
        "locale": "zh_CN",
        "container_id": "tv_container",
        "hide_side_toolbar": false,
        "allow_symbol_change": false,
        "timezone": "Asia/Shanghai",
        "hide_volume": false,
        "studies": [
            "BB@tv-basicstudies",
            "MACD@tv-basicstudies"
        ]
    }});
</script>
"""

# ==========================================
# 6. 主界面 UI 渲染
# ==========================================
c1, c2, c3 = st.columns(3)
with c1: st.markdown(f"<div class='metric-card'><b>账户余额</b><br><h2>${st.session_state.balance:,.2f}</h2></div>", unsafe_allow_html=True)
with c2: st.markdown(f"<div class='metric-card'><b>实时价格</b><br><h2>${current_price:,.2f if current_price else 0}</h2></div>", unsafe_allow_html=True)
with c3:
    settled_list = [o for o in st.session_state.orders if o.get('状态') == '已结算']
    wr = (len([o for o in settled_list if o['结果'] == 'W']) / len(settled_list) * 100) if settled_list else 0
    st.markdown(f"<div class='metric-card'><b>综合胜率</b><br><h2>{wr:.1f}%</h2></div>", unsafe_allow_html=True)

# 渲染图表
components.html(tv_html, height=390)

# 下单区 (并排大按钮)
col_up, col_down = st.columns(2)
if col_up.button("🟢 买入看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

if col_down.button("🔴 卖出看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# 交易账本
st.write("---")
st.subheader("📋 实时执行账本")
if st.session_state.orders:
    df_data = []
    for od in reversed(st.session_state.orders[-12:]):
        rem_sec = (od.get("结算时间", now) - now).total_seconds()
        status_text = od.get('结果', f"倒计时 {int(rem_sec)}s" if rem_sec > 0 else "结算中...")
        df_data.append({
            "资产": od['资产'],
            "方向": "涨 ↗️" if od['方向'] == "看涨" else "跌 ↘️",
            "入场价": f"{od['开仓价']:,.2f}",
            "入场时间": od['开仓时间'].strftime('%H:%M:%S'),
            "平仓时间": od['平仓时间'].strftime('%H:%M:%S') if od.get('平仓时间') else "-",
            "状态/结果": status_text
        })
    st.table(df_data)
