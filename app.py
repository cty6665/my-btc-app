import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 环境依赖与容错 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置 (红线保留：数据库、CSS、双源价格)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

# 注入你最爱的手机端 CSS (保留 1.1rem 字体和四列布局)
st.markdown("""
<style>
    .stApp { background-color: #ffffff; }
    .stButton button { background: #FCD535 !important; color: #000 !important; font-weight: bold !important; height: 55px !important; border-radius: 8px !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; font-family: monospace; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } }
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=3000, key="global_refresh")

def get_beijing_time():
    return datetime.utcnow() + timedelta(hours=8)

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

# --- 核心：双源价格获取 (保留心脏逻辑) ---
def get_price(symbol):
    """只获取当前价格，用于结算和Header显示，不涉及K线"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # 主源：Binance
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        try:
            # 备源：Gate.io
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", headers=headers, timeout=2).json()
            return float(res[0]['last'])
        except:
            return None

# --- 原生 K 线获取 (仅在原生模式下调用) ---
def get_klines_direct(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=3).json()
        df = pd.DataFrame(res, columns=['time','open','high','low','close','vol','x','x','x','x','x','x'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        
        # 指标计算
        df['ma'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'] = df['ma'] + 2*df['std']
        df['dn'] = df['ma'] - 2*df['std']
        
        # MACD
        exp12 = df['close'].ewm(span=12).mean()
        exp26 = df['close'].ewm(span=26).mean()
        df['dif'] = exp12 - exp26
        df['dea'] = df['dif'].ewm(span=9).mean()
        df['hist'] = (df['dif'] - df['dea']) * 2
        return df
    except:
        return pd.DataFrame()

# ==========================================
# 控制区与图表逻辑分离
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制台")
    # 这里是切换开关
    chart_mode = st.radio("图表数据源", ["TradingView (前端直连)", "原生 Plotly (后端直连)"], index=0)
    
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("周期", [1, 5, 30], format_func=lambda x: f"{x}m", index=0)
    bet = st.number_input("金额", 10.0, 5000.0, 50.0)
    
    if st.button("重置系统"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_db(1000.0, [])
        st.rerun()

# 1. 获取当前价 (这一步必须做，否则没法结算，但数据量极小)
current_price = get_price(coin)
now = get_beijing_time()

# 2. 结算逻辑 (后台静默运行)
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            close_p = get_price(od['资产']) # 结算时再请求一次对应资产
            if close_p:
                od['平仓价'] = close_p
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                if win: 
                    st.session_state.balance += od['金额'] * 1.8
                    od['收益'] = od['金额'] * 0.8
                else:
                    od['收益'] = -od['金额']
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 显视区：根据模式严格分离渲染
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 现价", f"${current_price:,.2f}" if current_price else "同步中...")

# --- 核心修改：if/else 彻底隔离 ---
if chart_mode.startswith("TradingView"):
    # 【模式 A：TradingView】
    # 绝对不运行 get_klines_direct()，完全靠前端 Widget
    # 这就是你说的“TV API 调用”，它在前端 JS 里
    tv_script = f"""
    <div class="tradingview-widget-container" style="height:400px">
      <div id="tradingview_chart"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{coin}",
        "interval": "1",
        "timezone": "Asia/Shanghai",
        "theme": "light",
        "style": "1",
        "locale": "zh_CN",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "hide_top_toolbar": false,
        "container_id": "tradingview_chart",
        "studies": ["BB@tv-basicstudies", "MACD@tv-basicstudies"] 
      }});
      </script>
    </div>
    """
    components.html(tv_script, height=400)

else:
    # 【模式 B：原生 K 线】
    # 只有选这个模式，Python 才会去请求历史 K 线
    if HAS_PLOTLY:
        df_k = get_klines_direct(coin) # 👈 只有在这里才调用 API
        if not df_k.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.02)
            
            # K线
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], name='K'), row=1, col=1)
            # 布林
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(100,100,100,0.3)'), showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(100,100,100,0.3)'), fill='tonexty', showlegend=False), row=1, col=1)
            # MACD
            colors = ['#2ebd85' if v>=0 else '#f6465d' for v in df_k['hist']]
            fig.add_trace(go.Bar(x=df_k['time'], y=df_k['hist'], marker_color=colors, name='MACD'), row=2, col=1)
            
            fig.update_layout(height=400, margin=dict(t=10,b=10,l=10,r=10), xaxis_rangeslider_visible=False)
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor='#eee')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else:
            st.warning(f"原生接口请求超时，请切换回 TradingView 或检查网络。")
    else:
        st.error("环境缺失 Plotly，无法渲染原生图表。")

# ==========================================
# 交易操作区 (开仓动画回归)
# ==========================================
b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交订单中...", expanded=False) as s:
            time.sleep(0.3)
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, 
                "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), 
                "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("提交订单中...", expanded=False) as s:
            time.sleep(0.3)
            st.session_state.balance -= bet
            st.session_state.orders.append({
                "资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, 
                "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), 
                "状态": "待结算", "结果": None
            })
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="🚀 开仓成功", state="complete")
        st.rerun()

# ==========================================
# 统计与流水 (完整保留)
# ==========================================
st.markdown("---")
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
today_orders = [o for o in settled if o['开仓时间'].date() == now.date()]

t_pnl = sum(o['收益'] for o in today_orders)
t_wr = (len([o for o in today_orders if o['结果']=='W'])/len(today_orders)*100) if today_orders else 0
all_pnl = sum(o['收益'] for o in settled)
all_wr = (len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0

m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(t_wr)}%")
m3.metric("总盈亏", f"${all_pnl:.1f}")
m4.metric("总胜率", f"{int(all_wr)}%")

st.subheader("交易流水")
if st.session_state.orders:
    data = []
    for o in reversed(st.session_state.orders[-15:]):
        rem = (o['结算时间'] - now).total_seconds()
        data.append({
            "时间": o['开仓时间'].strftime('%H:%M:%S'),
            "方向": "🟢涨" if o['方向']=="看涨" else "🔴跌",
            "金额": o['金额'],
            "入场": f"{o['开仓价']:.2f}",
            "平仓": f"{o['平仓价']:.2f}" if o['平仓价'] else "运行中",
            "结果": o['结果'] if o['结果'] else f"{int(max(0,rem))}s"
        })
    st.table(data)
