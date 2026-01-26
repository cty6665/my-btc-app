import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 样式与配置 (完全保留，未改动你的卡片)
# ==========================================
st.set_page_config(page_title="Binance Pro", layout="wide", initial_sidebar_state="collapsed")
DB_FILE = "trading_db.json"

st.markdown("""
<style>
    .stApp { background-color: #fcfcfc; }
    /* 核心补丁：隐藏刷新时的加载条，减少闪烁感 */
    [data-testid="stStatusWidget"] { display: none !important; }
    
    [data-testid="stHorizontalBlock"] { align-items: center !important; }
    .data-card {
        background: #ffffff; padding: 12px; border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); border-top: 4px solid #FCD535;
        text-align: center; margin-bottom: 8px;
    }
    .balance-border { border-top: 4px solid #0ECB81; }
    .card-label { color: #848e9c; font-size: 0.8rem; }
    .card-value { color: #1e2329; font-size: 1.4rem; font-weight: 800; }
    .stats-container {
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
        background: #f8f9fa; padding: 15px; border-radius: 10px; margin-bottom: 15px;
    }
    .stat-item { text-align: center; border-right: 1px solid #eee; }
    .stat-item:last-child { border-right: none; }
    .stat-label { font-size: 0.75rem; color: #848e9c; }
    .stat-val { font-size: 1rem; font-weight: bold; margin-top: 4px; }
    .order-card-container {
        position: relative; background: white; border-radius: 10px;
        margin-bottom: 12px; border: 1px solid #eee; overflow: hidden;
    }
    .order-progress-bg { padding: 15px; width: 100%; height: 100%; position: relative; }
    .order-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; position: relative; z-index: 5; }
    .order-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; position: relative; z-index: 5; }
    .grid-label { color: #848e9c; font-size: 0.7rem; }
    .grid-val { color: #1e2329; font-size: 0.85rem; font-weight: 600; margin-top: 2px; }
    
    /* 防止刷新时页面跳动：固定 K 线容器高度 */
    .chart-container { min-height: 450px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 基础逻辑
# ==========================================
def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

@st.cache_data(ttl=1)
def get_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return None

@st.cache_data(ttl=2)
def get_klines_smart_source(symbol, interval='1m'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :6]
        df.columns = ['time','open','high','low','close','vol']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f); orders = data.get('orders', [])
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if od.get(key) and isinstance(od[key], str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

if 'balance' not in st.session_state: st.session_state.balance, st.session_state.orders = load_db()
if 'bet' not in st.session_state: st.session_state.bet = 100.0
if 'coin' not in st.session_state: st.session_state.coin = "BTCUSDT"
if 'interval' not in st.session_state: st.session_state.interval = "1m"
if 'mode' not in st.session_state: st.session_state.mode = "原生 K 线"
if 'dur' not in st.session_state: st.session_state.dur = 5
if 'show_success' not in st.session_state: st.session_state.show_success = False

# ==========================================
# 3. 彻底隔离的刷新组件
# ==========================================

@st.fragment
def chart_fragment():
    # 只有在原生代码模式下才开启刷新，TV 模式不碰它
    if st.session_state.mode == "原生 K 线":
        st_autorefresh(interval=3000, key="chart_refresh")
    
    now = get_beijing_time()
    curr_p = get_price(st.session_state.coin)
    
    # 余额与价格卡片
    c1, c2 = st.columns(2)
    c1.markdown(f'<div class="data-card balance-border"><div class="card-label">可用余额</div><div class="card-value">${st.session_state.balance:,.2f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="data-card"><div class="card-label">{st.session_state.coin} 现价</div><div class="card-value">${(curr_p if curr_p else 0):,.2f}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="chart-container">', unsafe_allow_html=True)
    if st.session_state.mode == "TradingView":
        tv_i = "1" if st.session_state.interval == "1m" else st.session_state.interval.replace("m", "")
        tv_html = f'<div style="height:450px;"><div id="tv" style="height:450px;"></div><script src="https://s3.tradingview.com/tv.js"></script><script>new TradingView.widget({{"autosize":true,"symbol":"BINANCE:{st.session_state.coin}","interval":"{tv_i}","theme":"light","style":"1","locale":"zh_CN","container_id":"tv","studies":["BB@tv-basicstudies","MACD@tv-basicstudies"]}});</script></div>'
        components.html(tv_html, height=450)
    else:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        df_k = get_klines_smart_source(st.session_state.coin, st.session_state.interval)
        if not df_k.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            # 主 K 线
            fig.add_trace(go.Candlestick(x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'], increasing_fillcolor='#0ECB81', decreasing_fillcolor='#F6465D'), row=1, col=1)
            
            # 标记待结算订单
            for o in st.session_state.orders:
                if o['状态'] == "待结算" and o['资产'] == st.session_state.coin:
                    color = "#0ECB81" if o['方向'] == "看涨" else "#F6465D"
                    fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=color, row=1, col=1)

            # 更新布局，uirevision 是防止闪烁跳动的核心
            fig.update_layout(
                height=450, 
                margin=dict(t=5,b=5,l=0,r=0), 
                xaxis_rangeslider_visible=False, 
                plot_bgcolor='white', 
                showlegend=False, 
                uirevision=st.session_state.coin # 锁定视图，不随刷新晃动
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    st.markdown('</div>', unsafe_allow_html=True)

@st.fragment
def order_flow_fragment():
    # 订单流每秒跳动一次，处理数字倒计时
    st_autorefresh(interval=1000, key="order_refresh")
    now = get_beijing_time()
    
    # 检查结算
    upd = False
    for od in st.session_state.orders:
        if od['状态'] == "待结算" and now >= od['结算时间']:
            p_final = get_price(od['资产'])
            if p_final:
                od['平仓价'] = p_final
                win = (od['方向']=="看涨" and od['平仓价']>od['开仓价']) or (od['方向']=="看跌" and od['平仓价']<od['开仓价'])
                st.session_state.balance += (od['金额'] * 1.8) if win else 0
                od['状态'], od['结果'] = "已结算", "W" if win else "L"
                upd = True
    if upd: save_db(st.session_state.balance, st.session_state.orders)

    # 显示结算统计卡片 (完全沿用你的 CSS)
    all_settled = [o for o in st.session_state.orders if o['状态']=="已结算"]
    today_p = sum([(o['金额']*0.8 if o['结果']=="W" else -o['金额']) for o in all_settled if o['结算时间'].date() == now.date()])
    
    st.markdown("---")
    st.markdown(f"""
    <div class="stats-container">
        <div class="stat-item"><div class="stat-label">今日盈亏</div><div class="stat-val">{today_p:+.2f}</div></div>
        <div class="stat-item"><div class="stat-label">累计订单</div><div class="stat-val">{len(all_settled)}</div></div>
        <div class="stat-item"><div class="stat-label">服务器时间</div><div class="stat-val">{now.strftime("%H:%M:%S")}</div></div>
        <div class="stat-item"><div class="stat-label">系统状态</div><div class="stat-val" style="color:#0ecb81">RUNNING</div></div>
    </div>
    """, unsafe_allow_html=True)

    # 订单动态列表 (自然跳动效果)
    for o in reversed(st.session_state.orders[-10:]):
        if o['状态'] == "待结算":
            total_sec = (o['结算时间'] - o['开仓时间']).total_seconds()
            past_sec = (now - o['开仓时间']).total_seconds()
            pct = min(100, max(0, int((past_sec / total_sec) * 100)))
            bg = f"background: linear-gradient(90deg, rgba(252, 213, 53, 0.08) {pct}%, white {pct}%);"
            res_txt = f"倒计时 {max(0, int(total_sec - past_sec))}s"
            p_val = "---"; p_color = "#222"
        else:
            win = o.get('结果')=="W"; bg = f"background: {'rgba(14, 203, 129, 0.05)' if win else 'rgba(246, 70, 93, 0.05)'};"
            res_txt = "已平仓"; p_val = f"{o['金额']*0.8 if win else -o['金额']:+.2f}"; p_color = "#0ecb81" if win else "#f6465d"

        st.markdown(f"""
        <div class="order-card-container" style="{bg}">
            <div class="order-progress-bg">
                <div class="order-header">
                    <div class="symbol-info"><span>{'↗' if o['方向']=='看涨' else '↘'} {o['资产']}</span><span style="font-size:0.7rem; color:#848e9c; margin-left:10px;">{res_txt}</span></div>
                    <div style="font-weight:800; color:{p_color}">{p_val} USDT</div>
                </div>
                <div class="order-grid">
                    <div class="grid-item"><span class="grid-label">金额</span><span class="grid-val">${o['金额']}</span></div>
                    <div class="grid-item"><span class="grid-label">开仓价</span><span class="grid-val">{o['开仓价']:,.2f}</span></div>
                    <div class="grid-item"><span class="grid-label">平仓价</span><span class="grid-val">{o.get('平仓价', 0):,.2f if o.get('平仓价') else '---'}</span></div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ==========================================
# 4. 静态控制区
# ==========================================
# (这部分代码只有在切换币对或点击买卖时才会重绘，自动刷新不影响这里)

t1, t2, t3 = st.columns(3)
with t1:
    st.session_state.mode = st.selectbox("图表源", ["原生 K 线", "TradingView"], index=0 if st.session_state.mode=="原生 K 线" else 1)
with t2:
    st.session_state.coin = st.selectbox("交易币对", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], key="c_sel")
with t3:
    st.session_state.dur = st.selectbox("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟")

chart_fragment()

st.markdown("<br>", unsafe_allow_html=True)
o1, o2 = st.columns(2)
if o1.button("🟢 买涨 (UP)", use_container_width=True):
    p = get_price(st.session_state.coin)
    if st.session_state.balance >= st.session_state.bet:
        st.session_state.balance -= st.session_state.bet
        st.session_state.orders.append({"资产": st.session_state.coin, "方向": "看涨", "开仓价": p, "金额": st.session_state.bet, "开仓时间": get_beijing_time(), "结算时间": get_beijing_time() + timedelta(minutes=st.session_state.dur), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders); st.rerun()

if o2.button("🔴 买跌 (DOWN)", use_container_width=True):
    p = get_price(st.session_state.coin)
    if st.session_state.balance >= st.session_state.bet:
        st.session_state.balance -= st.session_state.bet
        st.session_state.orders.append({"资产": st.session_state.coin, "方向": "看跌", "开仓价": p, "金额": st.session_state.bet, "开仓时间": get_beijing_time(), "结算时间": get_beijing_time() + timedelta(minutes=st.session_state.dur), "状态": "待结算"})
        save_db(st.session_state.balance, st.session_state.orders); st.rerun()

order_flow_fragment()
