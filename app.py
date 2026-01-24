import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境检测 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置与视觉锁定 (绝不改动你喜欢的按钮和样式)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #ffffff; }
    .stButton button { background: #FCD535 !important; color: #000 !important; font-weight: bold !important; height: 55px !important; border-radius: 8px !important; border: none !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; font-family: monospace; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } }
    /* 表格字体微调，确保列多也不乱 */
    .stTable { font-size: 0.75rem !important; }
    th { background-color: #f8f9fa !important; }
</style>
""", unsafe_allow_html=True)

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# ==========================================
# 数据处理核心 (保留双源逻辑)
# ==========================================
def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

def get_klines_smart_source(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    # 尝试 Gate.io (修复列数报错)
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval=1m&limit=60"
        res = requests.get(url, timeout=3, headers=headers).json()
        if isinstance(res, list) and len(res) > 0:
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2, 1]]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Gate.io"
    except: pass
    # 尝试 Binance
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=2).json()
        if isinstance(res, list):
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Binance"
    except: pass
    return pd.DataFrame(), None

# ==========================================
# 数据库管理
# ==========================================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if od.get(key) and isinstance(od[key], str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(tmp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 侧边栏 (锁定你喜欢的设置)
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    chart_mode = st.radio("数据源", ["原生 K 线 (流畅优化版)", "TradingView (官方直连)"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    duration = st.radio("周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

# ==========================================
# 局部刷新容器 (解决一闪一闪的关键)
# ==========================================
@st.fragment
def live_ui():
    # 仅在此函数内每3秒刷新
    st_autorefresh(interval=3000, key="live_refresh")
    
    curr_p = get_price(coin)
    now_time = get_beijing_time()

    # 1. 自动结算
    if curr_p:
        updated = False
        for od in st.session_state.orders:
            if od['状态'] == "待结算" and now_time >= od['结算时间']:
                cp_final = get_price(od['资产'])
                if cp_final:
                    od['平仓价'] = cp_final
                    win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                    st.session_state.balance += (od['金额'] * 1.8) if win else 0
                    od['收益'] = (od['金额'] * 0.8) if win else -od['金额']
                    od['状态'], od['结果'] = "已结算", "W" if win else "L"
                    updated = True
        if updated: save_db(st.session_state.balance, st.session_state.orders)

    # 2. 顶部数值
    c1, c2 = st.columns(2)
    c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
    c2.metric(f"{coin} 实时现价", f"${curr_p:,.2f}" if curr_p else "连接中...")

    # 3. K 线渲染
    if chart_mode.startswith("TradingView"):
        tv_html = f"""
        <div style="height:500px;"><div id="tv" style="height:500px;"></div>
        <script src="https://s3.tradingview.com/tv.js"></script>
        <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","timezone":"Asia/Shanghai","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies"]}});</script></div>
        """
        components.html(tv_html, height=500)
    else:
        df_k, src = get_klines_smart_source(coin)
        if not df_k.empty:
            # 强化布林带：增加中轨 MA20
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['std'] = df_k['close'].rolling(20).std()
            df_k['up'] = df_k['ma'] + 2*df_k['std']
            df_k['dn'] = df_k['ma'] - 2*df_k['std']
            
            fig = go.Figure()
            # 1. 布林带填充 (上下轨染色)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(0,100,255,0.1)', width=0.5), showlegend=False))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(0,100,255,0.1)', width=0.5), fill='tonexty', fillcolor='rgba(0,100,255,0.05)', showlegend=False))
            # 2. 中轨
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['ma'], line=dict(color='rgba(150,150,150,0.4)', width=1, dash='dot'), showlegend=False))
            # 3. 蜡烛图 (优化颜色：实心)
            fig.add_trace(go.Candlestick(
                x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
                increasing_fillcolor='#0ECB81', increasing_line_color='#0ECB81',
                decreasing_fillcolor='#F6465D', decreasing_line_color='#F6465D'
            ))
            
            fig.update_layout(
                height=500, margin=dict(t=10,b=10,l=0,r=0), 
                xaxis_rangeslider_visible=False,
                dragmode='pan', # 默认平移，单指拖动，双指缩放
                plot_bgcolor='white', paper_bgcolor='white'
            )
            # 针对手机端缩放优化
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displayModeBar': False})
        else:
            st.error("K 线加载中...")

# 运行局部刷新区
live_ui()

# ==========================================
# 交易操作 (这块不会闪烁)
# ==========================================
now_static = get_beijing_time()
curr_p_static = get_price(coin)

b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and curr_p_static:
    if st.session_state.balance >= bet:
        with st.status("交易撮合中...") as s:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看涨", "开仓价": curr_p_static, "平仓价": None, 
                "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration), 
                "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and curr_p_static:
    if st.session_state.balance >= bet:
        with st.status("交易撮合中...") as s:
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看跌", "开仓价": curr_p_static, "平仓价": None, 
                "金额": bet, "开仓时间": now_static, "结算时间": now_static+timedelta(minutes=duration), 
                "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

# ==========================================
# 统计与高级交易流水 (彻底重构)
# ==========================================
st.markdown("---")
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
t_pnl = sum(o['收益'] for o in settled if o['开仓时间'].date() == now_static.date())

m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")
m3.metric("总盈亏", f"${sum(o['收益'] for o in settled):.1f}")
m4.metric("总胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")

st.subheader("📋 交易流水记录")
if not st.session_state.orders:
    st.info("💡 请开启你的第一笔交易，开启盈利之旅！")
else:
    table_data = []
    # 只取最近15笔，防止手机端过长
    for o in reversed(st.session_state.orders[-15:]):
        rem = (o['结算时间'] - now_static).total_seconds()
        table_data.append({
            "币种": o['资产'].replace("USDT", ""),
            "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
            "金额": f"${o['金额']}",
            "开仓价": f"{o['开仓价']:,.2f}",
            "平仓价": f"{o['平仓价']:,.2f}" if o['平仓价'] else "---",
            "开仓时间": o['开仓时间'].strftime('%H:%M:%S'),
            "平仓时间": o['结算时间'].strftime('%H:%M:%S'),
            "结果": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
        })
    # 使用 st.table 展现最稳定的手机端视觉
    st.table(table_data)
