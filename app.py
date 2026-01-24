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
# 基础配置与 CSS
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #ffffff; }
    .stButton button { background: #FCD535 !important; color: #000 !important; font-weight: bold !important; height: 55px !important; border-radius: 8px !important; border: none !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; font-family: monospace; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } }
    .stTable { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=3000, key="global_refresh")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

# ==========================================
# 核心：修复后的多源 K 线获取 (Gate.io 修复版)
# ==========================================

def get_price(symbol):
    """现价三渠道保障"""
    try: # 1. Binance
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=2).json()
        return float(res['price'])
    except:
        try: # 2. Gate.io
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except:
            try: # 3. HTX
                res = requests.get(f"https://api.huobi.pro/market/trade?symbol={symbol.lower()}", timeout=2).json()
                return float(res['tick']['data'][0]['price'])
            except: return None

def get_klines_smart_source(symbol):
    """
    针对 Restricted Location 优化的 K 线逻辑
    顺序：Gate.io (最稳) -> HTX (备用) -> Binance (可能被封)
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # --- 1. Gate.io (针对你遇到的 8 列问题进行了修复) ---
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval=1m&limit=60"
        res = requests.get(url, timeout=3, headers=headers).json()
        if isinstance(res, list) and len(res) > 0:
            # Gate.io 返回: [时间, 成交量, 收盘, 最高, 最低, 开盘, 成交额, 状态]
            df = pd.DataFrame(res)
            # 无论返回几列，我们只取需要的索引
            df = df[[0, 5, 3, 4, 2, 1]] # 对应 [t, o, h, l, c, v]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Gate.io"
    except Exception as e:
        pass

    # --- 2. HTX / 火币 (API 限制最少) ---
    try:
        h_sym = symbol.lower()
        url = f"https://api.huobi.pro/market/history/kline?symbol={h_sym}&period=1min&size=60"
        res = requests.get(url, timeout=3, headers=headers).json()
        if res.get('status') == 'ok':
            df = pd.DataFrame(res['data'])
            df['time'] = pd.to_datetime(df['id'], unit='s') + timedelta(hours=8)
            return df[['time', 'open', 'high', 'low', 'close', 'vol']], "HTX"
    except:
        pass

    # --- 3. Binance (最后尝试) ---
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=2).json()
        if isinstance(res, list):
            df = pd.DataFrame(res).iloc[:, :6]
            df.columns = ['time', 'open', 'high', 'low', 'close', 'vol']
            df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df, "Binance"
    except:
        pass

    return pd.DataFrame(), None

# ==========================================
# 逻辑初始化与数据库
# ==========================================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if isinstance(od.get(key), str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if isinstance(tmp.get(key), datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(tmp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 侧边栏与控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    chart_mode = st.radio("图表数据源", ["原生 K 线 (多源备份)", "TradingView (官方直连)"], index=0)
    st.divider()
    coin = st.selectbox("选择交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额", 10.0, 5000.0, 100.0)
    if st.button("🚨 重置账户"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = get_beijing_time()

# 自动结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            cp = get_price(od['资产'])
            if cp:
                od['平仓价'] = cp
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                if win: 
                    st.session_state.balance += od['金额'] * 1.8
                    od['收益'] = od['金额'] * 0.8
                else: od['收益'] = -od['金额']
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# UI 渲染层
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 实时现价", f"${current_price:,.2f}" if current_price else "同步中...")

if chart_mode.startswith("TradingView"):
    tv_script = f"""
    <div style="height:500px; width:100%;">
      <div id="tv_chart" style="height:500px;"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{coin}","interval":"1","timezone":"Asia/Shanghai","theme":"light","style":"1","locale":"zh_CN","container_id":"tv_chart","studies":["BB@tv-basicstudies"]}});</script>
    </div>
    """
    components.html(tv_script, height=500)
else:
    if HAS_PLOTLY:
        df_k, source = get_klines_smart_source(coin)
        if not df_k.empty:
            # 布林带计算
            df_k['ma'] = df_k['close'].rolling(20).mean()
            df_k['up'] = df_k['ma'] + 2*df_k['close'].rolling(20).std()
            df_k['dn'] = df_k['ma'] - 2*df_k['close'].rolling(20).std()
            
            fig = make_subplots(rows=1, cols=1)
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(173,216,230,0.5)'), name='BB_Up'))
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(173,216,230,0.5)'), name='BB_Dn'))
            
            fig.update_layout(height=500, margin=dict(t=0,b=0,l=0,r=0), xaxis_rangeslider_visible=False, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            st.caption(f"📍 数据源: {source} (实时每3秒刷新)")
        else:
            st.error("📉 警告：所有后端数据通道均被防火墙拦截。")
            st.info("💡 请在左侧切换到 'TradingView' 模式，该模式不经过后端，可直接显示。")

# --- 下单按钮 ---
b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("🚀 撮合交易中...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="✅ 买涨成功", state="complete")
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("🚀 撮合交易中...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="✅ 买跌成功", state="complete")
        st.rerun()

# ==========================================
# 流水与仪式感
# ==========================================
st.markdown("---")
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
t_pnl = sum(o['收益'] for o in settled if o['开仓时间'].date() == now.date())

m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")
m3.metric("总盈亏", f"${sum(o['收益'] for o in settled):.1f}")
m4.metric("总胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")

st.subheader("📋 交易流水")
if not st.session_state.orders:
    st.info("💡 请开启你的第一笔交易，开启盈利之旅！")
else:
    data = []
    for o in reversed(st.session_state.orders[-10:]):
        rem = (o['结算时间'] - now).total_seconds()
        data.append({
            "时间": o['开仓时间'].strftime('%H:%M:%S'),
            "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
            "金额": f"${o['金额']}",
            "开仓价": f"{o['开仓价']:,.2f}",
            "结果/倒计时": o['结果'] if o['结果'] else f"{int(max(0,rem))}秒"
        })
    st.table(data)
