import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# --- 核心环境检测与容错 ---
# 解决环境依赖未生效问题：即使报错也不崩溃，而是降级处理
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except (ImportError, ModuleNotFoundError):
    HAS_PLOTLY = False

# ==========================================
# 1. 基础配置与数据库 (保持红线逻辑)
# ==========================================
st.set_page_config(
    page_title="Binance Pro Terminal", 
    page_icon="📊", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

DB_FILE = "trading_db.json"

def get_beijing_time():
    """获取北京时间"""
    return datetime.utcnow() + timedelta(hours=8)

def load_db():
    """加载数据库，保持原有变量命名一致性"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                # 修复时间对象的反序列化
                for od in orders:
                    for key in ['结算时间', '开仓时间']:
                        if isinstance(od.get(key), str):
                            od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                return balance, orders
        except: 
            return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    """保存数据库，确保数据完整性"""
    serialized_orders = []
    for od in orders:
        temp = od.copy()
        for key in ['结算时间', '开仓时间']:
            if isinstance(temp.get(key), datetime):
                temp[key] = temp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized_orders.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized_orders}, f)

# 初始化 Session State
if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# --- 手机端适配 CSS (你要求的 UX 核心) ---
# 保持字体 1.1rem，强制不换行，保持黄色按钮风格
st.markdown("""
<style>
    /* 全局背景微调，更护眼 */
    .stApp { background-color: #ffffff; }
    
    /* 按钮样式 - 保持之前的醒目黄 */
    .stButton button { 
        background: #FCD535 !important; 
        color: #1E2329 !important; 
        font-weight: 800 !important; 
        height: 55px !important; 
        border-radius: 8px !important; 
        border: none !important;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        transition: all 0.2s;
    }
    .stButton button:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.15); }
    
    /* 核心数值显示优化 (Mobile Optimization) */
    [data-testid="stMetricValue"] { 
        font-size: 1.1rem !important; 
        font-weight: 700 !important;
        white-space: nowrap !important; 
        font-family: 'Roboto Mono', monospace;
    }
    [data-testid="stMetricLabel"] { 
        font-size: 0.8rem !important; 
        color: #707A8A !important;
        white-space: nowrap !important; 
    }
    
    /* 侧边栏与布局微调 */
    section[data-testid="stSidebar"] { background-color: #F7F9FA; }
    
    /* 手机端四列强制并排 (红线要求) */
    @media (max-width: 640px) { 
        [data-testid="column"] { width: 25% !important; min-width: 25% !important; padding: 0 2px !important; } 
    }
    
    /* 表格紧凑化 */
    .stTable { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

# 自动刷新：每 3 秒刷新一次（平衡实时性与性能）
st_autorefresh(interval=3000, key="global_refresh")

# ==========================================
# 2. 行情获取 (The Backup Logic - 绝对红线)
# ==========================================
def get_price(symbol):
    """
    双源行情获取：
    1. 优先币安 (Binance)
    2. 失败则切换 Gate.io (Backup)
    """
    # 增加 User-Agent 伪装，减少被拦截概率
    headers = {
        'User-Agent': 'Mozilla/5.0', 
        'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"
    }
    try:
        # Source 1: Binance
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        res = requests.get(url, headers=headers, timeout=3).json() # timeout设为3秒，快速失败切换
        return float(res['price'])
    except Exception:
        try:
            # Source 2: Gate.io (Backup Logic)
            g_sym = symbol.replace("USDT", "_USDT")
            url = f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}"
            res = requests.get(url, headers=headers, timeout=3).json()
            return float(res[0]['last'])
        except Exception:
            return None

def get_klines_direct(symbol):
    """
    获取原生 K 线数据，包含布林带与 MACD 计算
    """
    try:
        # 获取 60 根 1分钟 K线
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=60"
        res = requests.get(url, timeout=5).json()
        
        # 数据清洗
        df = pd.DataFrame(res, columns=['time','open','high','low','close','vol','ct','qa','tr','tb','tq','ig'])
        df['time'] = pd.to_datetime(df['time'], unit='ms') + timedelta(hours=8) # 转北京时间
        for col in ['open','high','low','close']: 
            df[col] = df[col].astype(float)
            
        # --- 技术指标计算 (新增功能) ---
        # 1. 布林带 (Bollinger Bands)
        df['ma20'] = df['close'].rolling(20).mean()
        df['std'] = df['close'].rolling(20).std()
        df['up'] = df['ma20'] + 2 * df['std']
        df['dn'] = df['ma20'] - 2 * df['std']
        
        # 2. MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd_v'] = exp1 - exp2
        df['macd_s'] = df['macd_v'].ewm(span=9, adjust=False).mean()
        df['macd_h'] = (df['macd_v'] - df['macd_s']) * 2 # 柱状图放大一点方便看
        
        return df
    except:
        return pd.DataFrame()

# ==========================================
# 3. 侧边栏与控制逻辑
# ==========================================
with st.sidebar:
    st.header("⚙️ 交易终端")
    chart_choice = st.radio("图表引擎", ["TradingView (推荐)", "原生直连 (MACD+BB)"], index=0)
    
    st.markdown("---")
    coin = st.selectbox("交易对", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"], index=0)
    duration = st.radio("结算周期", [1, 5, 10, 30], format_func=lambda x: f"{x} 分钟", index=0) # 增加1分钟选项方便测试
    bet = st.number_input("下单金额 (USDT)", min_value=10.0, max_value=5000.0, value=50.0, step=10.0)
    
    st.markdown("---")
    if st.button("🚨 重置账户"):
        st.session_state.balance = 1000.0
        st.session_state.orders = []
        save_db(1000.0, [])
        st.rerun()

# 实时获取价格
current_price = get_price(coin)
now = get_beijing_time()

# ==========================================
# 4. 结算逻辑 (核心算法)
# ==========================================
if current_price:
    updated = False
    for od in st.session_state.orders:
        # 只有在“待结算”且时间到达时才处理
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            # 获取结算时的价格（这里也应该复用 get_price 以利用双源逻辑）
            p_close = get_price(od.get("资产", coin)) 
            
            if p_close:
                od["平仓价"] = p_close # 【红线保持】写入平仓价
                
                # 判定胜负
                is_win = False
                if od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]: is_win = True
                elif od["方向"] == "看跌" and od["平仓价"] < od["开仓价"]: is_win = True
                
                # 资金结算 (1.8倍赔率 = 本金 + 0.8收益)
                if is_win:
                    st.session_state.balance += od["金额"] * 1.8
                    od["收益"] = od["金额"] * 0.8
                    od["结果"] = "W"
                else:
                    od["收益"] = -od["金额"]
                    od["结果"] = "L"
                
                od["状态"] = "已结算"
                updated = True
    
    if updated:
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# ==========================================
# 5. 统计数据计算 (保持变量名一致性)
# ==========================================
settled_orders = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
today_str = now.strftime('%Y-%m-%d')
today_orders = [o for o in settled_orders if o.get("开仓时间") and o.get("开仓时间").strftime('%Y-%m-%d') == today_str]

today_pnl = sum([o.get("收益", 0) for o in today_orders])
today_wr = (len([o for o in today_orders if o.get("结果") == "W"]) / len(today_orders) * 100) if today_orders else 0
total_pnl = sum([o.get("收益", 0) for o in settled_orders])
total_wr = (len([o for o in settled_orders if o.get("结果") == "W"]) / len(settled_orders) * 100) if settled_orders else 0

# ==========================================
# 6. UI 布局：头部仪表盘 & K线
# ==========================================
# 顶部两列：余额与现价
c1, c2 = st.columns(2)
c1.metric("账户余额 (USDT)", f"${st.session_state.balance:,.2f}", delta=f"{today_pnl:,.2f} 今日")
c2.metric(f"{coin} 实时价", f"${current_price:,.2f}" if current_price else "连接中...", delta=None)

# 图表区域
if chart_choice == "TradingView":
    # TradingView 插件
    tv_html = f"""
    <div style="height:400px; border-radius:10px; overflow:hidden;">
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
      "save_image": false,
      "container_id": "tradingview_chart",
      "studies": ["BB@tv-basicstudies", "MACD@tv-basicstudies"]
    }});
    </script>
    <div id="tradingview_chart" style="height:400px;"></div>
    </div>
    """
    components.html(tv_html, height=400)

else:
    # --- 原生 Plotly 绘图 (包含布林带 + MACD) ---
    if HAS_PLOTLY:
        df_k = get_klines_direct(coin)
        if not df_k.empty:
            # 创建子图：主图(K线+BB)占70%，副图(MACD)占30%
            fig = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.05, 
                row_heights=[0.7, 0.3]
            )
            
            # 1. K线图 (红涨绿跌 - 国际标准)
            fig.add_trace(go.Candlestick(
                x=df_k['time'], open=df_k['open'], high=df_k['high'], low=df_k['low'], close=df_k['close'],
                name='Price', increasing_line_color='#0ECB81', decreasing_line_color='#F6465D'
            ), row=1, col=1)
            
            # 2. 布林带 (透明填充)
            fig.add_trace(go.Scatter(
                x=df_k['time'], y=df_k['up'], line=dict(color='rgba(112, 122, 138, 0.3)', width=1), name='Upper'
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=df_k['time'], y=df_k['dn'], line=dict(color='rgba(112, 122, 138, 0.3)', width=1), 
                fill='tonexty', fillcolor='rgba(112, 122, 138, 0.05)', name='Lower'
            ), row=1, col=1)
            
            # 3. MACD
            # 柱状图颜色根据涨跌变化
            colors = ['#0ECB81' if v >= 0 else '#F6465D' for v in df_k['macd_h']]
            fig.add_trace(go.Bar(
                x=df_k['time'], y=df_k['macd_h'], marker_color=colors, name='MACD Hist'
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=df_k['time'], y=df_k['macd_v'], line=dict(color='#2962FF', width=1), name='DIF'
            ), row=2, col=1)
            fig.add_trace(go.Scatter(
                x=df_k['time'], y=df_k['macd_s'], line=dict(color='#FF6D00', width=1), name='DEA'
            ), row=2, col=1)
            
            # 布局优化
            fig.update_layout(
                height=400, 
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor='#ffffff',
                paper_bgcolor='#ffffff',
                showlegend=False,
                xaxis_rangeslider_visible=False,
                xaxis2_rangeslider_visible=False
            )
            # 移除网格线，看起来更像专业行情
            fig.update_xaxes(showgrid=False, zeroline=False)
            fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0', zeroline=False)
            
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': True})
        else:
            st.info("⌛ 原生数据加载中 (API 连接慢)...")
    else:
        st.error("⚠️ 缺少 Plotly 库。请在 requirements.txt 中添加 'plotly' 并重启 App。")

# ==========================================
# 7. 交易操作区 (带动画 - UX Status)
# ==========================================
col_up, col_down = st.columns(2)

# 看涨按钮逻辑
if col_up.button(f"🟢 买涨 (看涨)", use_container_width=True):
    if current_price:
        if st.session_state.balance >= bet:
            # 【红线保持】使用 st.status + sleep 制造开仓仪式感
            with st.status("正在提交订单到交易所...", expanded=False) as status:
                st.write("连接撮合引擎...")
                time.sleep(0.3)
                st.write("锁定入场价格...")
                time.sleep(0.3)
                
                # 扣款与记录
                st.session_state.balance -= bet
                new_order = {
                    "资产": coin, 
                    "方向": "看涨", 
                    "开仓价": current_price, 
                    "平仓价": None, # 初始为空，不可删
                    "金额": bet, 
                    "开仓时间": now, 
                    "结算时间": now + timedelta(minutes=duration), 
                    "状态": "待结算", 
                    "结果": None
                }
                st.session_state.orders.append(new_order)
                save_db(st.session_state.balance, st.session_state.orders)
                
                status.update(label="🚀 开仓成功！", state="complete", expanded=False)
            st.rerun()
        else:
            st.error("余额不足！")

# 看跌按钮逻辑
if col_down.button(f"🔴 买跌 (看跌)", use_container_width=True):
    if current_price:
        if st.session_state.balance >= bet:
            with st.status("正在提交订单到交易所...", expanded=False) as status:
                st.write("连接撮合引擎...")
                time.sleep(0.3)
                st.write("锁定入场价格...")
                time.sleep(0.3)
                
                st.session_state.balance -= bet
                new_order = {
                    "资产": coin, 
                    "方向": "看跌", 
                    "开仓价": current_price, 
                    "平仓价": None, 
                    "金额": bet, 
                    "开仓时间": now, 
                    "结算时间": now + timedelta(minutes=duration), 
                    "状态": "待结算", 
                    "结果": None
                }
                st.session_state.orders.append(new_order)
                save_db(st.session_state.balance, st.session_state.orders)
                
                status.update(label="🚀 开仓成功！", state="complete", expanded=False)
            st.rerun()
        else:
            st.error("余额不足！")

# ==========================================
# 8. 核心统计数据 (四列布局 - CSS 适配)
# ==========================================
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("今日盈亏", f"${today_pnl:+.1f}")
m2.metric("今日胜率", f"{int(today_wr)}%")
m3.metric("总账户盈亏", f"${total_pnl:+.1f}")
m4.metric("总胜率", f"{int(total_wr)}%")
st.markdown("---")

# ==========================================
# 9. 交易流水表 (Data Integrity - 1:1 还原)
# ==========================================
st.subheader("📋 交易流水")

if st.session_state.orders:
    df_show = []
    # 倒序显示，最新的在最上面
    for od in reversed(st.session_state.orders[-15:]): 
        # 计算剩余时间
        rem_seconds = (od.get("结算时间", now) - now).total_seconds()
        
        # 格式化数据，严格保留“入场价”和“平仓价”的对比
        df_show.append({
            "时间": od.get("开仓时间").strftime('%H:%M:%S'),
            "方向": "🟢 涨" if od.get("方向") == "看涨" else "🔴 跌",
            "金额": f"${od.get('金额')}",
            "入场价": f"{od.get('开仓价', 0):,.2f}",
            # 如果没平仓，显示倒计时，如果平仓了，显示平仓价格
            "平仓价": f"{od.get('平仓价', 0):,.2f}" if od.get("平仓价") else "⏳ 运行中",
            "结果": od.get("结果") if od.get("结果") else f"{int(max(0, rem_seconds))}s"
        })
    
    # 渲染表格
    st.table(df_show)
else:
    st.caption("暂无交易记录，请开始你的第一笔交易。")
