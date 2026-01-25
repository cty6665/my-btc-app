import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

# --- 1. 环境与依赖检测 ---
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    st.error("请安装 plotly: pip install plotly")
    st.stop()

# ==========================================
# 页面配置与 CSS 样式注入 (严格按照 375px 移动端设计)
# ==========================================
st.set_page_config(page_title="Event Contract Pro", layout="wide", initial_sidebar_state="collapsed")

# 颜色常量
COLOR_UP = "#00B578"
COLOR_DN = "#FF3141"
COLOR_BG = "#FFFFFF"
COLOR_SEC_BG = "#F5F5F7"
COLOR_TEXT_MAIN = "#000000"
COLOR_TEXT_SUB = "#8E8E93"

st.markdown(f"""
<style>
    /* 全局重置，模拟手机环境 */
    .stApp {{
        background-color: #f0f2f5; 
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .mobile-container {{
        max-width: 450px; /* 稍微放宽一点适应PC浏览，模拟手机 */
        margin: 0 auto;
        background-color: #FFFFFF;
        min-height: 100vh;
        box-shadow: 0 0 20px rgba(0,0,0,0.1);
        position: relative;
        padding-bottom: 50px;
    }}
    
    /* 1. 导航栏 */
    .nav-bar {{
        height: 44px;
        border-bottom: 1px solid #E5E5EA;
        display: flex; align-items: center; justify-content: center;
        font-size: 18px; font-weight: 700; color: {COLOR_TEXT_MAIN};
        background: #FFF;
        position: sticky; top: 0; z-index: 100;
    }}

    /* 2. 交易对与赔率 */
    .odds-section {{
        height: 60px;
        display: flex; justify-content: space-between; align-items: center;
        padding: 0 16px;
        background: #FFF;
    }}
    .pair-title {{ font-size: 24px; font-weight: 700; color: #000; }}
    .odds-group {{ display: flex; gap: 12px; }}
    .odds-tag {{ font-size: 14px; font-weight: 600; }}
    .odds-up {{ color: {COLOR_UP}; }}
    .odds-dn {{ color: {COLOR_DN}; }}

    /* 3. 图表控制栏 */
    .chart-controls {{
        height: 40px; background: {COLOR_SEC_BG};
        display: flex; align-items: center; justify-content: space-between;
        padding: 0 16px;
    }}
    .index-price {{ font-size: 14px; color: {COLOR_TEXT_SUB}; }}
    
    /* 周期按钮覆盖 Streamlit 默认样式 */
    div[data-testid="stHorizontalBlock"] button {{
        padding: 2px 8px !important;
        font-size: 12px !important;
        border: none !important;
        background-color: transparent !important;
        color: {COLOR_TEXT_SUB} !important;
    }}
    div[data-testid="stHorizontalBlock"] button:focus, div[data-testid="stHorizontalBlock"] button:active {{
        color: {COLOR_UP} !important;
        font-weight: bold !important;
    }}

    /* 3.3 技术指标文字 */
    .tech-info {{
        background: {COLOR_SEC_BG};
        padding: 8px 16px;
        font-size: 10px; color: {COLOR_TEXT_SUB};
        font-family: monospace;
        line-height: 1.4;
    }}

    /* 4. 交易输入区 */
    .input-row {{
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 16px;
        border-bottom: 1px solid {COLOR_SEC_BG};
        height: 50px;
    }}
    .input-label {{ font-size: 16px; color: #000; }}
    .input-value {{ font-size: 16px; font-weight: 600; }}
    .input-sub {{ font-size: 12px; color: {COLOR_TEXT_SUB}; margin-top: 2px; text-align: right; }}

    /* 5. 核心按钮 */
    .btn-container {{
        display: flex; gap: 12px; padding: 16px;
    }}
    /* 强制覆盖 Streamlit 按钮样式 */
    .stButton button {{
        width: 100%;
        height: 44px !important;
        border-radius: 8px !important;
        font-size: 18px !important;
        font-weight: 700 !important;
        border: none !important;
        color: #FFFFFF !important;
    }}
    /* 通过 Key 来区分颜色的 CSS hack 在 Streamlit 较难，改用 columns 布局配合内联样式 */

    /* 6. 订单列表 */
    .order-tabs {{
        display: flex; border-bottom: 1px solid {COLOR_SEC_BG};
    }}
    .order-tab {{
        flex: 1; text-align: center; padding: 10px 0; font-size: 16px; color: {COLOR_TEXT_SUB}; cursor: pointer;
    }}
    .order-tab.active {{
        color: #000; border-bottom: 2px solid {COLOR_UP};
    }}
    .order-item {{
        padding: 12px 16px;
        border-bottom: 1px solid {COLOR_SEC_BG};
    }}
    .order-row-1 {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
    .order-symbol {{ font-size: 16px; font-weight: 600; color: #000; display: flex; align-items: center; gap: 4px; }}
    .order-row-2 {{ font-size: 12px; color: {COLOR_TEXT_SUB}; margin-bottom: 2px; }}
    .order-row-3 {{ font-size: 12px; color: {COLOR_TEXT_SUB}; display: flex; justify-content: space-between; }}
    
    /* 成功动画 */
    @keyframes scaleIn {{ 0% {{ transform: scale(0); opacity: 0; }} 100% {{ transform: scale(1); opacity: 1; }} }}
    .success-overlay {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(255,255,255,0.9); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        animation: scaleIn 0.3s ease-out;
    }}
    .checkmark {{ width: 80px; height: 80px; stroke: {COLOR_UP}; stroke-width: 2; fill: none; animation: stroke 0.6s cubic-bezier(0.65, 0, 0.45, 1) forwards; }}
    .checkmark__check {{ transform-origin: 50% 50%; stroke-dasharray: 48; stroke-dashoffset: 48; animation: stroke 0.3s cubic-bezier(0.65, 0, 0.45, 1) 0.8s forwards; }}
    @keyframes stroke {{ 100% {{ stroke-dashoffset: 0; }} }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 核心逻辑与数据处理
# ==========================================
DB_FILE = "event_contract_db.json"

def get_beijing_time(): return datetime.utcnow() + timedelta(hours=8)

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                orders = data.get('orders', [])
                # 修复时间对象
                for od in orders:
                    for key in ['结算时间', '开仓时间', '平仓时间']:
                        if od.get(key) and isinstance(od[key], str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return data.get('balance', 1000.0), orders
        except Exception as e:
            return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    ser = []
    for od in orders:
        tmp = od.copy()
        for key in ['结算时间', '开仓时间', '平仓时间']:
            if tmp.get(key) and isinstance(tmp[key], datetime):
                tmp[key] = tmp[key].strftime('%Y-%m-%d %H:%M:%S')
        ser.append(tmp)
    with open(DB_FILE, "w") as f: json.dump({"balance": balance, "orders": ser}, f)

# 初始化 Session State
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()
if 'chart_interval' not in st.session_state:
    st.session_state.chart_interval = '1m'
if 'chart_mode' not in st.session_state:
    st.session_state.chart_mode = '原生K线' # '原生K线' or 'TradingView'

# 获取 K 线数据 (增强轮询版)
def get_klines_smart(symbol, interval):
    # 映射周期
    binance_interval = interval
    gate_interval = interval
    
    # 优先尝试 Gate.io (不需要API Key，频率限制宽松)
    try:
        g_sym = symbol.replace("USDT", "_USDT")
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g_sym}&interval={gate_interval}&limit=60"
        res = requests.get(url, timeout=2).json()
        if isinstance(res, list) and len(res) > 0:
            df = pd.DataFrame(res).iloc[:, [0, 5, 3, 4, 2]] # Time, Open, High, Low, Close
            df.columns = ['time','open','high','low','close']
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s') + timedelta(hours=8)
            for c in ['open','high','low','close']: df[c] = df[c].astype(float)
            return df
    except:
        pass

    # 备选 Binance
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={binance_interval}&limit=60"
        res = requests.get(url, timeout=2).json()
        df = pd.DataFrame(res).iloc[:, :5]
        df.columns = ['time','open','high','low','close']
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8)
        for c in ['open','high','low','close']: df[c] = df[c].astype(float)
        return df
    except:
        return pd.DataFrame()

def get_current_price(symbol):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=1).json()
        return float(res['price'])
    except:
        return None

# ==========================================
# 绘图逻辑 (满足所有视觉要求)
# ==========================================
def render_native_chart(df, symbol):
    if df.empty:
        st.warning("数据加载中或网络异常...")
        return

    # 1. 指标计算
    # BOLL
    df['ma20'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['up'] = df['ma20'] + 2 * df['std']
    df['dn'] = df['ma20'] - 2 * df['std']
    
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['sig']

    last = df.iloc[-1]
    
    # 2. UI: 指标文字显示
    st.markdown(f"""
    <div class="tech-info">
        <div>BOLL(20,2) UP:{last['up']:.2f} MB:{last['ma20']:.2f} DN:{last['dn']:.2f}</div>
        <div>MACD(12,26,9) DIF:{last['macd']:.4f} DEA:{last['sig']:.4f} MACD:{last['hist']:.4f}</div>
    </div>
    """, unsafe_allow_html=True)

    # 3. 绘图 (Plotly)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.75, 0.25])

    # K线 (绿涨红跌，纯色)
    fig.add_trace(go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        increasing_line_color=COLOR_UP, increasing_fillcolor=COLOR_UP,
        decreasing_line_color=COLOR_DN, decreasing_fillcolor=COLOR_DN,
        showlegend=False
    ), row=1, col=1)

    # BOLL (加粗，颜色区分)
    fig.add_trace(go.Scatter(x=df['time'], y=df['up'], line=dict(color='rgba(31, 119, 180, 0.6)', width=2), name='UP'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['dn'], line=dict(color='rgba(227, 119, 194, 0.6)', width=2), name='DN'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['ma20'], line=dict(color='#FFB11B', width=2), name='MB'), row=1, col=1) # 金色中轨

    # MACD
    fig.add_trace(go.Bar(x=df['time'], y=df['hist'], marker_color=df['hist'].apply(lambda x: COLOR_UP if x>=0 else COLOR_DN)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['macd'], line=dict(color='#FCD535', width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['sig'], line=dict(color='#8E8E93', width=1)), row=2, col=1)

    # ===============================================
    # 4. 重点：持仓标记 (虚线 + 箭头)
    # ===============================================
    for order in st.session_state.orders:
        if order['状态'] == '待结算' and order.get('资产') == symbol:
            color = COLOR_UP if order['方向'] == '看涨' else COLOR_DN
            arrow_sym = "triangle-up" if order['方向'] == '看涨' else "triangle-down"
            price = order['开仓价']
            
            # 画虚线 (整个X轴延伸，或从开仓时间开始)
            fig.add_hline(y=price, line_dash="dash", line_color=color, line_width=1.5, row=1, col=1)
            
            # 画箭头 (定位在最新K线右侧或开仓位置，这里选择开仓时间标记)
            # 为了防止开仓时间在图表外，我们画在最新时间点旁边，并标注
            fig.add_annotation(
                x=df['time'].iloc[-1], # 标记在最新位置方便看到
                y=price,
                text="OPEN",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                arrowcolor=color,
                bgcolor=color,
                font=dict(color="white", size=8),
                row=1, col=1
            )

    # 布局微调
    fig.update_layout(
        margin=dict(t=10, b=0, l=0, r=40), # 右侧留出Y轴空间
        height=320,
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
        xaxis_rangeslider_visible=False,
        showlegend=False,
        dragmode='pan'
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor=COLOR_SEC_BG, side='right') # Y轴在右侧

    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': True})

# ==========================================
# 主界面构建 (Fragment 局部刷新)
# ==========================================
@st.fragment
def main_interface():
    st_autorefresh(interval=2000, key="data_refresher")
    
    # 容器：模拟手机
    with st.container():
        st.markdown('<div class="mobile-container">', unsafe_allow_html=True)
        
        # 1. 顶部导航
        st.markdown('<div class="nav-bar">事件合约</div>', unsafe_allow_html=True)

        # 全局状态控制
        col_hidden = st.columns([1,1]) # 隐藏的辅助控件
        with col_hidden[0]:
            symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "DOGEUSDT"], label_visibility="collapsed")
        
        # 获取价格
        curr_price = get_current_price(symbol)
        display_price = f"{curr_price:,.2f}" if curr_price else "Loading..."

        # 2. 交易对与赔率
        st.markdown(f"""
        <div class="odds-section">
            <div class="pair-title">{symbol}</div>
            <div class="odds-group">
                <div class="odds-tag odds-up">上涨：80%!</div>
                <div class="odds-tag odds-dn">下跌：80%!</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 3. 图表区域
        # 3.1 控制栏
        col_c1, col_c2 = st.columns([4, 6])
        with col_c1:
            st.markdown(f'<div style="height:40px; line-height:40px; padding-left:16px; color:#8E8E93; font-size:12px;">指数价格 {display_price}</div>', unsafe_allow_html=True)
        with col_c2:
            # 周期选择器 (交互式)
            intervals = ["1m", "5m", "15m", "1h"]
            s_cols = st.columns(len(intervals))
            for i, inter in enumerate(intervals):
                with s_cols[i]:
                    if st.button(inter, key=f"btn_{inter}"):
                        st.session_state.chart_interval = inter

        # 3.2 图表主体
        # 模式切换
        mode = st.radio("Display", ["原生K线", "TradingView"], horizontal=True, label_visibility="collapsed", key="mode_sel")
        
        if mode == "TradingView":
             tv_i = "1" if st.session_state.chart_interval == "1m" else st.session_state.chart_interval.replace("m", "")
             components.html(f"""
                <div id="tv"></div>
                <script src="https://s3.tradingview.com/tv.js"></script>
                <script>
                new TradingView.widget({{
                    "width": "100%", "height": 360, "symbol": "BINANCE:{symbol}",
                    "interval": "{tv_i}", "timezone": "Asia/Shanghai", "theme": "light",
                    "style": "1", "locale": "zh_CN", "toolbar_bg": "#f1f3f6", "enable_publishing": false,
                    "hide_top_toolbar": true, "save_image": false, "container_id": "tv",
                    "studies": ["BB@tv-basicstudies", "MACD@tv-basicstudies"]
                }});
                </script>
             """, height=360)
        else:
            # 原生图表
            df = get_klines_smart(symbol, st.session_state.chart_interval)
            render_native_chart(df, symbol)

        # 4. 交易输入区
        amount = 10.0 # 默认
        
        # 模拟输入行 UI
        st.markdown('<div style="background:#FFF; margin-top:10px;">', unsafe_allow_html=True)
        
        # 行1: 数量
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown('<div style="padding:16px 16px 0; font-size:16px;">数量(USDT)</div>', unsafe_allow_html=True)
        with c2:
            amt_input = st.number_input("Amount", min_value=1.0, value=10.0, step=10.0, label_visibility="collapsed")

        st.markdown(f"""
            <div style="padding: 0 16px 12px; text-align:right; font-size:12px; color:#8E8E93; border-bottom:1px solid #F5F5F7;">
                可用 {st.session_state.balance:,.2f} USDT
            </div>
            <div class="input-row">
                <span class="input-label">支付率</span>
                <div style="text-align:right">
                    <div class="input-value" style="color:{COLOR_UP}">80%!</div>
                    <div class="input-sub">{amt_input * 0.8:.2f} USDT</div>
                </div>
            </div>
            <div class="input-row">
                <span class="input-label">U本位合约</span>
                <span class="input-value" style="color:#000">{st.session_state.balance:,.2f} USDT+</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 5. 核心按钮区
        st.markdown('<br>', unsafe_allow_html=True)
        b_col1, b_col2 = st.columns(2)
        
        # 逻辑处理：点击按钮
        action = None
        with b_col1:
            if st.button("上涨", use_container_width=True):
                # 注入绿色样式
                st.markdown(f"""<style>div[data-testid="column"]:nth-of-type(1) button {{background-color: {COLOR_UP} !important;}}</style>""", unsafe_allow_html=True)
                action = "看涨"
        with b_col2:
            if st.button("下跌", use_container_width=True):
                # 注入红色样式
                st.markdown(f"""<style>div[data-testid="column"]:nth-of-type(2) button {{background-color: {COLOR_DN} !important;}}</style>""", unsafe_allow_html=True)
                action = "看跌"

        # 下单处理
        if action and curr_price:
            if st.session_state.balance >= amt_input:
                st.session_state.balance -= amt_input
                new_order = {
                    "资产": symbol, "方向": action, "金额": amt_input,
                    "开仓价": curr_price, "平仓价": None,
                    "开仓时间": get_beijing_time(),
                    "结算时间": get_beijing_time() + timedelta(minutes=1), # 测试用1分钟结算
                    "平仓时间": None,
                    "状态": "待结算", "结果": None, "支付率": "80%!" # 添加容错字段
                }
                st.session_state.orders.append(new_order)
                save_db(st.session_state.balance, st.session_state.orders)
                st.session_state.show_success = True
                st.rerun()
            else:
                st.error("余额不足！")

        # 6. 订单列表区
        st.markdown('<div style="background:#FFF; min-height:300px; margin-top:20px;">', unsafe_allow_html=True)
        
        # 结算逻辑
        need_save = False
        active_orders = []
        history_orders = []
        now = get_beijing_time()
        
        for o in st.session_state.orders:
            # 自动结算判定
            if o['状态'] == '待结算' and now >= o['结算时间']:
                # 获取结算价格
                settle_price = get_current_price(o['资产'])
                if settle_price:
                    o['平仓价'] = settle_price
                    o['平仓时间'] = now
                    is_win = (o['方向']=='看涨' and settle_price > o['开仓价']) or \
                             (o['方向']=='看跌' and settle_price < o['开仓价'])
                    
                    if is_win:
                        payout = o['金额'] * 1.8
                        st.session_state.balance += payout
                        o['结果'] = f"赢 +{payout - o['金额']:.2f}"
                    else:
                        o['结果'] = f"输 -{o['金额']:.2f}"
                    o['状态'] = '已结算'
                    need_save = True
            
            if o['状态'] == '待结算':
                active_orders.append(o)
            else:
                history_orders.insert(0, o) # 最新的在上面
        
        if need_save:
            save_db(st.session_state.balance, st.session_state.orders)

        # Tab 切换
        tab_choice = st.radio("Tabs", [f"已开仓({len(active_orders)})", "已平仓"], horizontal=True, label_visibility="collapsed")
        
        # 渲染列表函数
        def render_order_item(o, is_history=False):
            direction_color = COLOR_UP if o['方向'] == '看涨' else COLOR_DN
            arrow = "↑" if o['方向'] == '看涨' else "↓"
            time_fmt = "%m-%d %H:%M:%S"
            
            # 使用 .get 避免 KeyError
            open_t = o.get('开仓时间').strftime(time_fmt) if isinstance(o.get('开仓时间'), datetime) else str(o.get('开仓时间', ''))
            close_t = o.get('平仓时间').strftime(time_fmt) if isinstance(o.get('平仓时间'), datetime) and o.get('平仓时间') else "--"
            close_p = f"{o.get('平仓价', 0):.2f}" if o.get('平仓价') else "--"
            pay_rate = o.get('支付率', '80%!') # 容错默认值

            html = f"""
            <div class="order-item">
                <div class="order-row-1">
                    <div class="order-symbol">
                        {o.get('资产', 'Unknown')} 
                        <span style="color:{direction_color}; font-weight:bold;">{arrow}</span>
                    </div>
                    <div style="font-size:14px; color:#8E8E93">数量(USDT) {o.get('金额', 0)}</div>
                </div>
                <div class="order-row-2">
                    开仓价 {o.get('开仓价', 0):.2f} &nbsp;&nbsp; 开仓时间 {open_t}
                </div>
                <div class="order-row-3">
                    <span style="color:{COLOR_UP}">支付率 {pay_rate}</span>
                    <span>平仓价 {close_p} &nbsp; {close_t}</span>
                </div>
            """
            # 如果是持仓，显示倒计时
            if not is_history:
                rem = (o['结算时间'] - now).total_seconds()
                html += f'<div style="text-align:right; color:{COLOR_UP}; font-weight:bold; margin-top:4px;">倒计时 {int(rem)}s</div>'
            else:
                res_color = COLOR_UP if "赢" in str(o.get('结果','')) else COLOR_DN
                html += f'<div style="text-align:right; color:{res_color}; font-weight:bold; margin-top:4px;">{o.get("结果", "")}</div>'
            
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)

        if "已开仓" in tab_choice:
            for o in active_orders: render_order_item(o, False)
        else:
            for o in history_orders: render_order_item(o, True)

        st.markdown('</div></div>', unsafe_allow_html=True) # End mobile-container

# 成功动画层
if 'show_success' not in st.session_state: st.session_state.show_success = False
if st.session_state.show_success:
    st.markdown(f'<div class="success-overlay"><svg class="checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52"><circle class="checkmark__circle" cx="26" cy="26" r="25" fill="none" stroke="{COLOR_UP}"/><path class="checkmark__check" fill="none" d="M14.1 27.2l7.1 7.2 16.7-16.8"/></svg><h2 style="color: {COLOR_UP}; margin-top: 20px;">开仓成功</h2></div>', unsafe_allow_html=True)
    time.sleep(1.2)
    st.session_state.show_success = False
    st.rerun()

# 运行主程序
main_interface()
