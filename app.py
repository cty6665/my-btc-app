import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

# --- 1. 环境检测与库加载 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    st.error("请安装依赖: pip install plotly pandas requests streamlit-autorefresh")
    st.stop()

# ==========================================
# UI 深度定制 CSS (仿币安移动端)
# ==========================================
st.set_page_config(page_title="Binance Event", layout="wide", initial_sidebar_state="collapsed")

# 币安配色常量
BINANCE_GREEN = "#0ECB81"
BINANCE_RED = "#F6465D"
BINANCE_BLACK = "#1E2329"
BINANCE_GRAY = "#848E9C"
BINANCE_LIGHT_GRAY = "#F5F5F5"
BINANCE_GOLD = "#FCD535"

st.markdown(f"""
<style>
    /* 全局重置：模拟手机 APP 容器 */
    .stApp {{
        background-color: #FFFFFF;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    
    /* 隐藏 Streamlit 默认的 Header 和 Footer */
    header {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .block-container {{
        padding-top: 0px !important;
        padding-bottom: 40px !important;
        padding-left: 0px !important;
        padding-right: 0px !important;
        max-width: 100%;
    }}

    /* --- 1. 顶部行情栏样式 --- */
    .market-header {{
        padding: 12px 16px;
        background: #FFF;
        border-bottom: 1px solid #EAECEF;
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: sticky;
        top: 0;
        z-index: 999;
    }}
    .symbol-name {{
        font-size: 20px;
        font-weight: 700;
        color: {BINANCE_BLACK};
        display: flex;
        align-items: center;
    }}
    .price-box {{
        text-align: right;
    }}
    .price-main {{
        font-size: 20px;
        font-weight: 600;
        font-family: 'Roboto Mono', monospace; /* 数字等宽防跳动 */
    }}
    .price-sub {{
        font-size: 12px;
        font-weight: 500;
        margin-top: 2px;
    }}
    .color-up {{ color: {BINANCE_GREEN}; }}
    .color-down {{ color: {BINANCE_RED}; }}

    /* --- 2. 模拟原生 Tabs (时间单位选择) --- */
    /* 覆盖 Streamlit Radio 样式使其看起来像 Segmented Control */
    div.row-widget.stRadio > div {{
        flex-direction: row;
        background-color: #FFF;
        gap: 10px;
        justify-content: flex-start;
        overflow-x: auto;
    }}
    div.row-widget.stRadio > div > label {{
        background-color: {BINANCE_LIGHT_GRAY};
        border-radius: 4px;
        padding: 6px 12px;
        border: 1px solid transparent;
        color: {BINANCE_GRAY};
        font-size: 13px;
        font-weight: 500;
        flex: 1;
        text-align: center;
        white-space: nowrap;
        margin-right: 0px;
    }}
    /* 选中状态模拟 (Streamlit 较难完美控制，这里利用 checked 属性的伪类 hack 比较复杂，
       更简单的办法是利用 Streamlit 的 pills (新版) 或 自定义 CSS) */
    div.row-widget.stRadio > div > label[data-baseweb="radio"] > div:first-child {{
        display: none; /* 隐藏圆圈 */
    }}

    /* --- 3. 交易输入区美化 --- */
    .input-label {{
        font-size: 12px;
        color: {BINANCE_GRAY};
        margin-bottom: 4px;
    }}
    .balance-row {{
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: {BINANCE_GRAY};
        margin-top: 8px;
        padding: 0 4px;
    }}
    .highlight {{
        color: {BINANCE_BLACK};
        font-weight: 600;
    }}
    
    /* 输入框样式重写 */
    .stTextInput input {{
        background-color: {BINANCE_LIGHT_GRAY};
        border: none;
        border-radius: 4px;
        color: {BINANCE_BLACK};
        font-weight: 600;
        text-align: center;
        padding: 10px;
    }}
    .stTextInput input:focus {{
        box-shadow: none;
        border: 1px solid {BINANCE_GOLD};
    }}

    /* --- 4. 底部大按钮 --- */
    /* 强制覆盖 Streamlit 按钮样式 */
    .stButton button {{
        width: 100%;
        border-radius: 4px;
        border: none;
        color: white;
        font-size: 16px;
        font-weight: 600;
        padding: 12px 0;
        height: 48px;
        line-height: 1.2;
    }}
    
    /* 成功弹窗动画 */
    @keyframes scaleIn {{ 0% {{ transform: scale(0); opacity: 0; }} 100% {{ transform: scale(1); opacity: 1; }} }}
    .success-overlay {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.5); z-index: 99999;
        display: flex; align-items: center; justify-content: center;
        animation: scaleIn 0.2s ease-out;
    }}
    .success-card {{
        background: white; padding: 24px; border-radius: 12px; width: 280px; text-align: center;
    }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 逻辑层 (保持原有逻辑，增强容错)
# ==========================================
DB_FILE = "trading_db_v2.json"

def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

# 增强型 K 线获取（防报错）
def get_klines_smart(symbol, interval='15m'):
    # 尝试 Gate
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={interval}&limit=50"
        res = requests.get(url, timeout=1.5).json()
        if isinstance(res, list):
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2]]
            df.columns = ['time','open','high','low','close']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df
    except: pass
    
    # 备用 Binance
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=50"
        res = requests.get(url, timeout=1.5).json()
        df = pd.DataFrame(res).iloc[:, :5]
        df.columns = ['time','open','high','low','close']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

def get_realtime_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except: return 0.0

def load_db():
    if not os.path.exists(DB_FILE): return 1000.0, []
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            # 时间反序列化
            orders = data.get('orders', [])
            for o in orders:
                if '结算时间' in o: o['结算时间'] = datetime.strptime(o['结算时间'], '%Y-%m-%d %H:%M:%S')
                if '开仓时间' in o: o['开仓时间'] = datetime.strptime(o['开仓时间'], '%Y-%m-%d %H:%M:%S')
            return data.get('balance', 1000.0), orders
    except: return 1000.0, []

def save_db(balance, orders):
    ser_orders = []
    for o in orders:
        tmp = o.copy()
        if isinstance(tmp.get('结算时间'), datetime): tmp['结算时间'] = tmp['结算时间'].strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(tmp.get('开仓时间'), datetime): tmp['开仓时间'] = tmp['开仓时间'].strftime('%Y-%m-%d %H:%M:%S')
        ser_orders.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser_orders}, f)

# 初始化 Session
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ==========================================
# 页面主体绘制
# ==========================================
@st.fragment
def main_ui():
    st_autorefresh(interval=2000, key="data_loop") # 2秒刷新
    
    # 1. 顶部自定义 Header (模拟 App 顶部栏)
    symbol = "BTCUSDT"
    curr_price = get_realtime_price(symbol)
    
    # 计算简单的涨跌样式（这里仅做演示，实际需要24h数据，这里用固定颜色模拟效果）
    price_color_cls = "color-up" # 假设是涨
    price_str = f"{curr_price:,.2f}"
    
    st.markdown(f"""
    <div class="market-header">
        <div class="symbol-name">
            <span style="margin-right:4px;">BTC/USDT</span>
            <span style="font-size:12px; background:#F5F5F5; color:#848E9C; padding:2px 4px; border-radius:2px;">永续</span>
        </div>
        <div class="price-box">
            <div class="price-main {price_color_cls}">{price_str}</div>
            <div class="price-sub {price_color_cls}">+1.25%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. 图表区域 (原生 K 线 + BOLL + MACD)
    # UI 调整：尽可能让图表贴边
    k_interval = st.select_slider("Timeframe", options=["1m", "15m", "1h", "4h", "1d"], value="15m", label_visibility="collapsed")
    
    df = get_klines_smart(symbol, k_interval)
    if not df.empty:
        # 计算指标
        df['ma20'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'] = df['ma20'] + 2*df['std']
        df['dn'] = df['ma20'] - 2*df['std']
        
        # 绘图
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
        
        # 蜡烛图
        fig.add_trace(go.Candlestick(
            x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            increasing_line_color=BINANCE_GREEN, increasing_fillcolor=BINANCE_GREEN,
            decreasing_line_color=BINANCE_RED, decreasing_fillcolor=BINANCE_RED,
            showlegend=False
        ), row=1, col=1)
        
        # BOLL 线 (细线，颜色模仿截图)
        fig.add_trace(go.Scatter(x=df['time'], y=df['up'], line=dict(color='#FCD535', width=1), name='UP'), row=1, col=1) # 黄
        fig.add_trace(go.Scatter(x=df['time'], y=df['ma20'], line=dict(color='#E377C2', width=1), name='MB'), row=1, col=1) # 粉
        fig.add_trace(go.Scatter(x=df['time'], y=df['dn'], line=dict(color='#9467BD', width=1), name='DN'), row=1, col=1) # 紫
        
        # MACD (简单模拟成交量区域，为了省空间不做完整MACD，或者放Volume)
        # 这里为了模仿截图的 MACD 区域：
        df['macd'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        fig.add_trace(go.Bar(x=df['time'], y=df['macd'], marker_color=df['macd'].apply(lambda x: BINANCE_GREEN if x>0 else BINANCE_RED)), row=2, col=1)

        # 布局精修
        fig.update_layout(
            margin=dict(t=10, b=0, l=0, r=45), # 右侧留出 Y 轴空间
            height=350,
            paper_bgcolor='white',
            plot_bgcolor='white',
            xaxis_rangeslider_visible=False,
            dragmode='pan',
            hovermode='x unified'
        )
        fig.update_xaxes(showgrid=False, showticklabels=False) # 隐藏X轴标签
        fig.update_yaxes(showgrid=True, gridcolor='#F5F5F5', side='right', tickfont=dict(size=10, color=BINANCE_GRAY))
        
        # 绘制开仓虚线 (如果持有订单)
        active_orders = [o for o in st.session_state.orders if o['状态'] == '待结算']
        for o in active_orders:
            color = BINANCE_GREEN if o['方向'] == '看涨' else BINANCE_RED
            fig.add_hline(y=o['开仓价'], line_dash="dash", line_color=color, line_width=1, row=1, col=1)
            
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': True})

    # 3. 核心交易面板 (完全模仿截图下半部分)
    st.markdown('<div style="padding: 0 16px;">', unsafe_allow_html=True) # 增加左右内边距

    # 时间单位选择 (Time Unit)
    st.markdown('<div class="input-label">时间单位</div>', unsafe_allow_html=True)
    # 使用 columns 模拟按钮组
    t_cols = st.columns(4)
    duration_map = {"10 分钟": 10, "30 分钟": 30, "1 小时": 60, "1 天": 1440}
    selected_label = st.radio("Duration_Hidden", list(duration_map.keys()), horizontal=True, label_visibility="collapsed")
    duration = duration_map[selected_label]

    # 金额输入 (Amount)
    st.markdown('<div class="input-label" style="margin-top:12px;">数量 (USDT)</div>', unsafe_allow_html=True)
    amount = st.number_input("Amount", value=100.0, step=10.0, label_visibility="collapsed")
    
    # 余额与支付率 (Balance & Payout)
    st.markdown(f"""
    <div class="balance-row">
        <div>可用 <span class="highlight">{st.session_state.balance:.2f} USDT</span></div>
        <div>支付率 <span class="highlight" style="color:{BINANCE_GREEN}">80%</span></div>
    </div>
    <div class="balance-row">
        <div style="font-size:10px;">U本位合约</div>
        <div style="font-size:10px;">预计收益: {(amount*0.8):.2f} USDT</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True) # End padding div

    # 4. 底部操作按钮 (Fixed Bottom Logic 模拟)
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 使用 Streamlit columns 布局按钮
    btn_col1, btn_col2 = st.columns([1, 1], gap="small")
    
    # 注入特定列的 CSS 来改变按钮颜色
    # 这是一个比较 Hack 的方法，通过 nth-of-type 定位 columns
    
    with btn_col1:
        # 上涨按钮 (绿色)
        st.markdown(f"""
        <style>
        div[data-testid="column"]:nth-of-type(1) .stButton button {{
            background-color: {BINANCE_GREEN} !important;
            color: white !important;
        }}
        </style>
        """, unsafe_allow_html=True)
        if st.button("↗ 上涨", use_container_width=True):
            handle_order("看涨", amount, curr_price, duration)

    with btn_col2:
        # 下跌按钮 (红色)
        st.markdown(f"""
        <style>
        div[data-testid="column"]:nth-of-type(2) .stButton button {{
            background-color: {BINANCE_RED} !important;
            color: white !important;
        }}
        </style>
        """, unsafe_allow_html=True)
        if st.button("↘ 下跌", use_container_width=True):
            handle_order("看跌", amount, curr_price, duration)

    # 5. 持仓/订单列表 (放在最下面)
    render_order_list()

def handle_order(direction, amount, price, duration_mins):
    if st.session_state.balance < amount:
        st.toast("余额不足！", icon="⚠️")
        return
    
    now = get_beijing_time()
    st.session_state.balance -= amount
    st.session_state.orders.append({
        "time": now.strftime("%H:%M:%S"),
        "方向": direction,
        "开仓价": price,
        "金额": amount,
        "开仓时间": now,
        "结算时间": now + timedelta(minutes=duration_mins),
        "状态": "待结算",
        "结果": "--"
    })
    save_db(st.session_state.balance, st.session_state.orders)
    st.session_state.show_success = True
    st.rerun()

def render_order_list():
    st.markdown("""<div style="height:1px; background:#EAECEF; margin: 20px 0;"></div>""", unsafe_allow_html=True)
    st.subheader("当前持仓")
    
    active = [o for o in st.session_state.orders if o['状态'] == "待结算"]
    if not active:
        st.caption("暂无持仓")
        return
        
    for o in active:
        # 简单结算逻辑检测
        now = get_beijing_time()
        rem_sec = (o['结算时间'] - now).total_seconds()
        
        # 颜色
        d_color = BINANCE_GREEN if o['方向'] == "看涨" else BINANCE_RED
        d_arrow = "多" if o['方向'] == "看涨" else "空"
        
        # 卡片式布局
        st.markdown(f"""
        <div style="background:{BINANCE_LIGHT_GRAY}; padding:12px; border-radius:8px; margin-bottom:8px; font-size:13px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                <span style="font-weight:bold; color:{d_color}">[{d_arrow}] BTCUSDT</span>
                <span style="font-family:monospace; font-weight:bold;">${o['金额']}</span>
            </div>
            <div style="display:flex; justify-content:space-between; color:{BINANCE_GRAY};">
                <span>开: {o['开仓价']:.2f}</span>
                <span>倒计时: <span style="color:{BINANCE_BLACK}">{int(rem_sec)}s</span></span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 结算逻辑 (简化版，实际应在后端或循环中处理)
        if rem_sec <= 0:
            curr = get_realtime_price("BTCUSDT")
            win = (o['方向']=="看涨" and curr>o['开仓价']) or (o['方向']=="看跌" and curr<o['开仓价'])
            payout = o['金额'] * 1.8 if win else 0
            st.session_state.balance += payout
            o['状态'] = "已结算"
            o['结果'] = f"+{payout:.2f}" if win else "-100%"
            save_db(st.session_state.balance, st.session_state.orders)
            st.rerun()

# 成功弹窗逻辑
if 'show_success' not in st.session_state: st.session_state.show_success = False
if st.session_state.show_success:
    st.markdown(f"""
    <div class="success-overlay">
        <div class="success-card">
            <h3 style="color:{BINANCE_GREEN}; margin:0;">下单成功</h3>
            <p style="color:{BINANCE_GRAY}; margin-top:8px;">订单已提交至队列</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    time.sleep(1.5)
    st.session_state.show_success = False
    st.rerun()

main_ui()
