import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ==========================================
# 1. 基础配置与数据持久化
# ==========================================
DATA_FILE = "trading_data.csv"
st.set_page_config(page_title="Frontend Price Pro", layout="wide", initial_sidebar_state="collapsed")

def load_data():
    if os.path.exists(DATA_FILE):
        try: return float(pd.read_csv(DATA_FILE)['balance'].iloc[0])
        except: return 1000.0
    return 1000.0

def save_data(balance):
    pd.DataFrame({"balance": [balance]}).to_csv(DATA_FILE, index=False)

if 'balance' not in st.session_state: st.session_state.balance = load_data()
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 2. 核心黑科技：前端价格注入框
# ==========================================
# 这个输入框是“价格搬运工”，JS 会往这里填值
with st.sidebar:
    st.header("⚙️ 终端控制")
    # 隐藏的实时报价接收器
    injected_price = st.number_input("实时同步价", value=0.0, format="%.2f")
    coin = st.selectbox("品种", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    duration = st.radio("结算周期", [1, 5, 10, 30])
    bet = st.number_input("下单金额", 10.0, 5000.0, 50.0)
    
    if st.button("🚨 重置账户"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_data(1000.0)
        st.rerun()

# ==========================================
# 3. UI 样式
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; }
    .price-card { background: #F8F9FA; border-radius: 12px; padding: 20px; text-align: center; border: 1px solid #EEE; margin-bottom: 10px; }
    .price-val { font-size: 48px; font-weight: bold; color: #02C076; font-family: monospace; }
    .stButton button { width: 100%; height: 60px; font-size: 22px !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. 主界面：TV 图表 + 价格抓取脚本
# ==========================================
c1, c2 = st.columns([2, 1])

with c1:
    # TradingView 控件
    tv_html = f"""
        <div id="tv-chart" style="height:500px;"></div>
        <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
        <script type="text/javascript">
        var widget = new TradingView.widget({{
          "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1",
          "timezone": "Asia/Shanghai", "theme": "light", "style": "1",
          "locale": "zh_CN", "container_id": "tv-chart",
          "withdateranges": true, "hide_side_toolbar": false,
          "allow_symbol_change": true, "save_image": false,
          "studies": ["MAExp@tv-basicstudies"]
        }});
        </script>
    """
    components.html(tv_html, height=500)

with c2:
    st.markdown('<div class="price-card">', unsafe_allow_html=True)
    st.write("📈 实时行情")
    if injected_price > 0:
        st.markdown(f'<div class="price-val">${injected_price:,.2f}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="price-val" style="color:orange; font-size:24px;">等待图表报价...</div>', unsafe_allow_html=True)
    st.write(f"可用余额: **${st.session_state.balance:.2f}**")
    st.markdown('</div>', unsafe_allow_html=True)

    # 下单区
    col_up, col_down = st.columns(2)
    now = datetime.now()
    
    # 只要注入的价格 > 0，按钮就生效
    if col_up.button("🟢 看涨"):
        if injected_price > 0 and st.session_state.balance >= bet:
            st.session_state.balance -= bet
            save_data(st.session_state.balance)
            st.session_state.orders.append({
                "方向": "看涨", "开仓价": injected_price, "金额": bet,
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

    if col_down.button("🔴 看跌"):
        if injected_price > 0 and st.session_state.balance >= bet:
            st.session_state.balance -= bet
            save_data(st.session_state.balance)
            st.session_state.orders.append({
                "方向": "看跌", "开仓价": injected_price, "金额": bet,
                "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算"
            })
            st.rerun()

# ==========================================
# 5. 自动结算逻辑
# ==========================================
# 使用注入的价格进行实时结算
if injected_price > 0:
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "看涨" and injected_price > od["开仓价"]) or \
                  (od["方向"] == "看跌" and injected_price < od["开仓价"])
            st.session_state.balance += (od["金额"] * 1.8) if win else 0
            od["状态"] = "已结算 (WIN)" if win else "已结算 (LOSS)"
            save_data(st.session_state.balance)

# 历史记录
st.write("---")
st.write("📜 最近交易")
for od in reversed(st.session_state.orders[-3:]):
    st.write(f"{od['方向']} @ {od['开仓价']} | 状态: {od['状态']}")
