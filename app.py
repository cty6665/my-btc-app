import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 基础配置
# ==========================================
st.set_page_config(page_title="Trade Pro Mobile", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000000; }
    .price-text { font-family: 'Consolas', monospace; font-size: 32px; font-weight: bold; color: #02C076; }
    .pos-card { border-left: 5px solid #FCD535; padding: 10px; background: #F8F9FA; margin-bottom: 8px; border-radius: 8px; border: 1px solid #EEE; color: #000; }
    div[data-testid="stMetricValue"] { color: #000000 !important; }
    .stButton button { width: 100%; height: 55px; font-size: 18px !important; font-weight: bold; }
    p, span, label { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

# 5秒强制刷新，确保行情实时
st_autorefresh(interval=5000, key="auto_refresh_logic")

# ==========================================
# 2. 实时行情函数 (修复版)
# ==========================================
def fetch_realtime_data(symbol, interval):
    # 增加随机数防止 API 缓存
    ts = int(time.time() * 1000)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=60&t={ts}"
    try:
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=['time','open','high','low','close','v','ct','qa','tr','tb','tq','ig'])
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for col in ['open','high','low','close']: df[col] = df[col].astype(float)
            
            # 获取最新的那一口成交价
            ticker = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            curr_p = float(requests.get(ticker, timeout=2).json()['price'])
            return curr_p, df
    except:
        # 备用方案：CryptoCompare
        try:
            fsym = symbol.replace("USDT", "")
            cc_url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym=USDT&limit=60"
            cc_res = requests.get(cc_url, timeout=3).json()
            df_cc = pd.DataFrame(cc_res['Data']['Data'])
            df_cc['time'] = pd.to_datetime(df_cc['time'], unit='s') + timedelta(hours=8)
            return df_cc['close'].iloc[-1], df_cc
        except:
            return None, None

# ==========================================
# 3. 数据持久化初始化
# ==========================================
if 'balance' not in st.session_state: st.session_state.balance = 1000.0
if 'orders' not in st.session_state: st.session_state.orders = []

# ==========================================
# 4. 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    target_coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    interval_choice = st.selectbox("K线周期", ['1m', '5m', '15m', '1h'], index=0)
    
    unit_map = {"5分钟": 5, "10分钟": 10, "30分钟": 30, "1小时": 60, "1天": 1440}
    dur_label = st.radio("结算时长", list(unit_map.keys()), index=1)
    duration_mins = unit_map[dur_label]
    
    st.divider()
    if st.button("🚨 格式化账户 (重置)"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        st.rerun()

# ==========================================
# 5. 核心交易逻辑
# ==========================================
price, df = fetch_realtime_data(target_coin, interval_choice)
now = datetime.now()

if price:
    # 自动结算
    for od in st.session_state.orders:
        if od["状态"] == "待结算" and now >= od["结算时间"]:
            win = (od["方向"] == "看涨" and price > od["开仓价"]) or (od["方向"] == "看跌" and price < od["开仓价"])
            if win:
                st.session_state.balance += od["金额"] * 1.8
                od.update({"状态": "已结算", "结果": "WIN", "颜色": "#02C076"})
            else:
                od.update({"状态": "已结算", "结果": "LOSS", "颜色": "#CF304A"})

# 统计
finished = [od for od in st.session_state.orders if od['状态']=='已结算']
total_p = sum([(od['金额']*0.8 if od['结果']=='WIN' else -od['金额']) for od in finished])
win_r = (len([od for od in finished if od['结果']=='WIN']) / len(finished) * 100) if finished else 0.0

# ==========================================
# 6. UI 渲染
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("总盈亏", f"${total_p:.1f}")
c2.metric("胜率", f"{win_r:.0f}%")
c3.metric("余额", f"${st.session_state.balance:.1f}")

st.divider()

if price and not df.empty:
    st.markdown(f"**{target_coin}** <span class='price-text'>${price:,.2f}</span>", unsafe_allow_html=True)
    
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color='#02C076', decreasing_line_color='#CF304A'
    )])
    fig.update_layout(height=380, template="plotly_white", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.warning("⚠️ 正在尝试连接全球行情源，请稍候...")

st.subheader("⚡ 极速下单")
order_val = st.number_input("下单金额 (U)", 10.0, 5000.0, 50.0, step=10.0)
col_l, col_s = st.columns(2)

if col_l.button("🟢 看涨 (LONG)", type="primary"):
    if st.session_state.balance >= order_val:
        st.session_state.balance -= order_val
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "看涨", "开仓价": price, "金额": order_val, "状态": "待结算", "结果": None
        })
        st.rerun()

if col_s.button("🔴 看跌 (SHORT)"):
    if st.session_state.balance >= order_val:
        st.session_state.balance -= order_val
        st.session_state.orders.append({
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration_mins),
            "方向": "看跌", "开仓价": price, "金额": order_val, "状态": "待结算", "结果": None
        })
        st.rerun()

st.divider()
st.write("📋 历史记录 (最近5笔)")
for od in reversed(st.session_state.orders[-5:]):
    rc = od.get("颜色", "#FCD535")
    st.markdown(f"""
    <div class="pos-card">
        <b>{od['方向']}</b> | 开仓: ${od['开仓价']:.2f} | {od['金额']}U <br>
        <span style="color:{rc}">状态: {od['状态']} {od['结果'] if od['结果'] else ''}</span>
    </div>
    """, unsafe_allow_html=True)

# 临时数据导出（防止丢失）
with st.expander("💾 数据备份与恢复 (防止刷新丢失)"):
    st.write("如果担心手机端数据丢失，可以复制下方内容保存到记事本：")
    backup_data = {"balance": st.session_state.balance, "orders_count": len(st.session_state.orders)}
    st.json(backup_data)
