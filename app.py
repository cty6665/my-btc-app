import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import time

# --- 仅在必要时加载绘图库，不影响其他逻辑 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except:
    HAS_PLOTLY = False

# ==========================================
# 1. 数据库持久化 (完全保留你的原始逻辑和命名)
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")

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

# --- 手机端优化 CSS (完全保留) ---
st.markdown("""
<style>
    .stApp { background:#FFF; }
    .stButton button { background:#FCD535 !important; color:#000 !important; font-weight:bold !important; height: 55px !important; border-radius: 10px !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; } }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 行情获取 (恢复你提供的双保险逻辑，确保直连可用)
# ==========================================
def get_price(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        # 币安接口
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=5).json()
        return float(res['price'])
    except:
        try:
            # Gate.io 备份逻辑
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=5).json()
            return float(res[0]['last'])
        except: return None

# 获取K线用于原生绘图 (增加超时至5秒提高云端成功率)
def get_klines_data(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res, columns=['time','open','high','low','close','vol','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open','high','low','close']: df[col] = df[col].astype(float)
        return df
    except: return pd.DataFrame()

# ==========================================
# 3. 界面与参数控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    # 增加切换开关
    chart_engine = st.radio("K线引擎", ["TradingView", "原生K线 (直连)"], index=0)
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额 (U)", 10.0, 1000.0, 50.0)
    if st.button("🚨 清空记录并重置"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = get_beijing_time()

# 结算逻辑 (恢复完整的平仓价对比逻辑)
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

# 数据统计 (恢复完整命名)
settled_orders = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
today_str = now.strftime('%Y-%m-%d')
today_orders = [o for o in settled_orders if o.get("开仓时间") and o.get("开仓时间").strftime('%Y-%m-%d') == today_str]
today_pnl = sum([o.get("收益", 0) for o in today_orders])
today_wr = (len([o for o in today_orders if o.get("结果") == "W"]) / len(today_orders) * 100) if today_orders else 0
total_pnl = sum([o.get("收益", 0) for o in settled_orders])
total_wr = (len([o for o in settled_orders if o.get("结果") == "W"]) / len(settled_orders) * 100) if settled_orders else 0

# ==========================================
# 4. UI 布局与图表 (整合原生绘图)
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "同步中")

if chart_engine == "TradingView":
    tv_html = f"""<div style="height:380px;"><script src="https://s3.tradingview.com/tv.js"></script>
    <div id="tv-chart" style="height:380px;"></div>
    <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","theme":"light","style":"1","locale":"zh_CN","container_id":"tv-chart","hide_side_toolbar":false,"allow_symbol_change":false,"studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>"""
    components.html(tv_html, height=380)
else:
    # 原生 K 线绘制逻辑
    df_k = get_klines_data(coin)
    if not df_k.empty and HAS_PLOTLY:
        # 指标计算 (BB + MACD)
        df_k['ma20'] = df_k['close'].rolling(20).mean()
        df_k['std'] = df_k['close'].rolling(20).std()
        df_k['up'], df_k['dn'] = df_k['ma20'] + 2*df_k['std'], df_k['ma20'] - 2*df_k['std']
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(173,216,230,0.4)'), name='BB_Up'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(173,216,230,0.4)'), fill='tonexty', name='BB_Dn'), row=1, col=1)
        # MACD
        exp1 = df_k['close'].ewm(span=12).mean()
        exp2 = df_k['close'].ewm(span=26).mean()
        macd = exp1 - exp2
        sig = macd.ewm(span=9).mean()
        hist = macd - sig
        fig.add_trace(go.Bar(x=df_k['time'], y=hist, name='MACD'), row=2, col=1)
        
        fig.update_layout(height=380, margin=dict(l=0,r=0,t=0,b=0), template="plotly_white", xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    else:
        st.warning("原生 K 线数据加载中...请确保 requirements.txt 包含 plotly")

# --- 恢复开仓提示动画 (完全保留你的 status 动画逻辑) ---
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (UP)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在开仓...", expanded=False) as status:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.4)
            status.update(label="🚀 开仓成功", state="complete")
        st.toast(f"成功开仓: {coin} 看涨", icon="📈")
        st.rerun()

if col_down.button("🔴 看跌 (DOWN)") and current_price:
    if st.session_state.balance >= bet:
        with st.status("正在开仓...", expanded=False) as status:
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            time.sleep(0.4)
            status.update(label="🚀 开仓成功", state="complete")
        st.toast(f"成功开仓: {coin} 看跌", icon="📉")
        st.rerun()

# --- 统计显示 ---
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("今日盈亏", f"${today_pnl:.1f}")
m2.metric("今日胜率", f"{int(today_wr)}%")
m3.metric("总盈亏", f"${total_pnl:.1f}")
m4.metric("总胜率", f"{int(total_wr)}%")
st.markdown("---")

# ==========================================
# 6. 历史记录 (恢复完整的列信息：时间、方向、金额、入场价、平仓价、结果)
# ==========================================
st.subheader("📋 交易流水")
if st.session_state.orders:
    df_show = []
    for od in reversed(st.session_state.orders[-10:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        p_close_val = od.get("平仓价")
        df_show.append({
            "时间": od.get("开仓时间").strftime('%H:%M:%S') if od.get("开仓时间") else "-",
            "方向": "涨 ↗️" if od.get("方向") == "看涨" else "跌 ↘️",
            "金额": f"${od.get('金额')}",
            "入场价": f"{od.get('开仓价', 0):,.2f}",
            "平仓价": f"{p_close_val:,.2f}" if p_close_val else "运行中",
            "结果": od.get("结果") if od.get("结果") else f"{int(max(0,rem))}s"
        })
    st.table(df_show)
