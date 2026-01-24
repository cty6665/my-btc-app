import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 1. 核心环境检测 (确保 Plotly 可用) ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# ==========================================
# 基础配置 (红线：数据库、CSS、双源价格)
# ==========================================
st.set_page_config(page_title="Binance Pro Terminal", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

# --- 手机端适配 CSS (保持你最喜欢的样式) ---
st.markdown("""
<style>
    .stApp { background-color: #ffffff; }
    .stButton button { background: #FCD535 !important; color: #000 !important; font-weight: bold !important; height: 55px !important; border-radius: 8px !important; border: none !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; white-space: nowrap !important; font-family: monospace; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; white-space: nowrap !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } }
    .stTable { font-size: 0.85rem !important; }
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

# --- 核心：双源价格获取 ---
def get_price(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # Binance
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=3).json()
        return float(res['price'])
    except:
        try:
            # Gate.io Backup
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", headers=headers, timeout=3).json()
            return float(res[0]['last'])
        except: return None

# --- 原生 K 线获取 (彻底修复逻辑) ---
def get_klines_direct(symbol):
    try:
        # 延长 timeout 到 5 秒，确保云端网络能拉取到数据
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=5).json()
        
        # 严格对应币安返回的字段
        df = pd.DataFrame(res, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'q_av', 'trades', 'tb_base', 'tb_quote', 'ignore'
        ])
        
        # 转换数据类型
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        # --- 优化指标计算 ---
        # 布林带
        df['ma20'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'] = df['ma20'] + 2 * df['std']
        df['dn'] = df['ma20'] - 2 * df['std']
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd_v'] = exp1 - exp2
        df['macd_s'] = df['macd_v'].ewm(span=9, adjust=False).mean()
        df['macd_h'] = df['macd_v'] - df['macd_s']
        
        return df
    except Exception as e:
        # st.sidebar.error(f"K线接口报错: {e}") # 调试用
        return pd.DataFrame()

# ==========================================
# 控制区
# ==========================================
with st.sidebar:
    st.header("⚙️ 控制台")
    chart_mode = st.radio("图表模式", ["TradingView", "原生 K 线 (优化版)"], index=0)
    st.divider()
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额", 10.0, 5000.0, 50.0)
    if st.button("🚨 重置账户数据"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = get_beijing_time()

# 结算逻辑
if current_price:
    updated = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            close_p = get_price(od['资产'])
            if close_p:
                od['平仓价'] = close_p
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                if win: 
                    st.session_state.balance += od['金额'] * 1.8
                    od['收益'] = od['金额'] * 0.8
                else: od['收益'] = -od['金额']
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 显示区 (高度统一 500px)
# ==========================================
c1, c2 = st.columns(2)
c1.metric("账户余额", f"${st.session_state.balance:,.2f}")
c2.metric(f"{coin} 现价", f"${current_price:,.2f}" if current_price else "获取中...")

if chart_mode == "TradingView":
    tv_script = f"""
    <div style="height:500px; width:100%;">
      <div id="tradingview_chart" style="height:500px; width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true, "symbol": "BINANCE:{coin}", "interval": "1", "timezone": "Asia/Shanghai",
        "theme": "light", "style": "1", "locale": "zh_CN", "toolbar_bg": "#f1f3f6",
        "container_id": "tradingview_chart", "studies": ["BB@tv-basicstudies", "MACD@tv-basicstudies"] 
      }});
      </script>
    </div>
    """
    components.html(tv_script, height=500)
else:
    # --- 原生 K 线绘图优化区 ---
    if HAS_PLOTLY:
        df_k = get_klines_direct(coin)
        if not df_k.empty:
            # 创建子图：主图 70%，MACD 30%
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                               vertical_spacing=0.03, row_heights=[0.7, 0.3])
            
            # 1. 蜡烛图
            fig.add_trace(go.Candlestick(
                x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
                name='价格', increasing_line_color='#0ECB81', decreasing_line_color='#F6465D'
            ), row=1, col=1)
            
            # 2. 布林带 (优化视觉：使用虚线和半透明填充)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['up'], line=dict(color='rgba(173,216,230,0.4)', width=1), name='上轨'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(173,216,230,0.4)', width=1), fill='tonexty', fillcolor='rgba(173,216,230,0.05)', name='下轨'), row=1, col=1)
            
            # 3. MACD 柱状图
            macd_colors = ['#0ECB81' if val >= 0 else '#F6465D' for val in df_k['macd_h']]
            fig.add_trace(go.Bar(x=df_k['time'], y=df_k['macd_h'], marker_color=macd_colors, name='MACD柱'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['macd_v'], line=dict(color='#2962FF', width=1), name='DIF'), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_k['time'], y=df_k['macd_s'], line=dict(color='#FF6D00', width=1), name='DEA'), row=2, col=1)
            
            # 布局优化
            fig.update_layout(
                height=500,
                margin=dict(t=10, b=10, l=10, r=10),
                xaxis_rangeslider_visible=False,
                paper_bgcolor='white',
                plot_bgcolor='white',
                showlegend=False
            )
            fig.update_xaxes(showgrid=False, zeroline=False)
            fig.update_yaxes(showgrid=True, gridcolor='#F0F3F8', zeroline=False)
            
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else:
            # 增强反馈：如果加载不出来，显示具体的引导
            st.error("📉 原生 K 线加载失败。可能原因：API 请求超时或网络波动。")
            st.info("💡 建议：请先切换到 TradingView 模式，或稍等几秒自动刷新。")
    else:
        st.error("模块缺失：请确保已在 requirements.txt 中安装 plotly")

# 交易操作 (动画细节)
b1, b2 = st.columns(2)
if b1.button("🟢 买涨 (UP)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("🚀 正在撮合订单...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="✅ 开仓成功！", state="complete")
        st.rerun()

if b2.button("🔴 买跌 (DOWN)", use_container_width=True) and current_price:
    if st.session_state.balance >= bet:
        with st.status("🚀 正在撮合订单...", expanded=False) as s:
            time.sleep(0.4)
            st.session_state.balance -= bet
            st.session_state.orders.append({"资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet, "开仓时间": now, "结算时间": now+timedelta(minutes=duration), "状态": "待结算", "结果": None})
            save_db(st.session_state.balance, st.session_state.orders)
            s.update(label="✅ 开仓成功！", state="complete")
        st.rerun()

# ==========================================
# 统计与流水
# ==========================================
st.markdown("---")
settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
t_pnl = sum(o['收益'] for o in settled if o['开仓时间'].date() == now.date())
m1,m2,m3,m4 = st.columns(4)
m1.metric("今日盈亏", f"${t_pnl:.1f}")
m2.metric("今日胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")
m3.metric("总盈亏", f"${sum(o['收益'] for o in settled):.1f}")
m4.metric("总胜率", f"{int(len([o for o in settled if o['结果']=='W'])/len(settled)*100) if settled else 0}%")

st.subheader("📋 交易流水记录")

if not st.session_state.orders:
    # 还原你喜欢的仪式感细节
    st.info("✨ 虚位以待！请开启你的第一笔交易，开启财富之门！")
else:
    data = []
    for o in reversed(st.session_state.orders[-15:]):
        rem = (o['结算时间'] - now).total_seconds()
        data.append({
            "时间": o['开仓时间'].strftime('%H:%M:%S'),
            "方向": "涨 ↗️" if o['方向']=="看涨" else "跌 ↘️",
            "金额": f"${o['金额']}",
            "开仓价": f"{o['开仓价']:,.2f}",
            "平仓价": f"{o['平仓价']:,.2f}" if o['平仓价'] else "交易中...",
            "结果/倒计时": o['结果'] if o['结果'] else f"{int(max(0,rem))}秒"
        })
    st.table(data)
