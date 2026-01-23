import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. 数据库持久化逻辑 (余额 + 详细订单)
# ==========================================
DB_FILE = "trading_db.json"
st.set_page_config(page_title="Gemini Pro Trader", layout="wide", initial_sidebar_state="collapsed")

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                balance = data.get('balance', 1000.0)
                orders = data.get('orders', [])
                # 恢复时间对象
                for od in orders:
                    for key in ['开仓时间', '结算时间', '平仓时间']:
                        if od.get(key) and isinstance(od[key], str) and od[key] != "-":
                            try:
                                od[key] = datetime.strptime(od[key], '%Y-%m-%d %H:%M:%S')
                            except: pass
                return balance, orders
        except: return 1000.0, []
    return 1000.0, []

def save_db(balance, orders):
    serialized = []
    for od in orders:
        temp = od.copy()
        for key in ['开仓时间', '结算时间', '平仓时间']:
            if isinstance(temp.get(key), datetime):
                temp[key] = temp[key].strftime('%Y-%m-%d %H:%M:%S')
        serialized.append(temp)
    with open(DB_FILE, "w") as f:
        json.dump({"balance": balance, "orders": serialized}, f, indent=4)

if 'balance' not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# 自定义专业 UI 样式
st.markdown("""
<style>
    .stApp { background-color: #FFFFFF; color: #000; }
    .stButton button { background-color: #FCD535 !important; color: #000 !important; font-weight: bold; border-radius: 5px; height: 3em; }
    .metric-card { background: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 5px solid #FCD535; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .win-text { color: #02C076; font-weight: bold; }
    .loss-text { color: #CF304A; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# 每 5 秒强制刷新一次页面，保持行情和倒计时同步
st_autorefresh(interval=5000, key="global_refresh")

# ==========================================
# 2. 增强型行情获取 (API通行证 + 跨源备份)
# ==========================================
def get_price(symbol):
    headers = {'X-MBX-APIKEY': "OV8COob7B14HYTG100sMaNPTkhSJ01dpqFVZSQa2HdRZRVhxBrwHdOFAIFNuWS8t"}
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", headers=headers, timeout=2).json()
        return float(res['price'])
    except:
        try:
            g_sym = symbol.replace("USDT", "_USDT")
            res = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g_sym}", timeout=2).json()
            return float(res[0]['last'])
        except: return None

# ==========================================
# 3. 侧边栏与参数设置
# ==========================================
with st.sidebar:
    st.header("⚙️ 终端控制")
    coin = st.selectbox("交易资产", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], index=0)
    duration = st.radio("结算周期", [5, 10, 30, 60], format_func=lambda x: f"{x} 分钟", index=0)
    bet = st.number_input("下单金额 (USDT)", 10.0, 5000.0, 100.0)
    if st.button("🚨 重置账户与清空记录"):
        st.session_state.balance, st.session_state.orders = 1000.0, []
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        save_db(1000.0, [])
        st.rerun()

current_price = get_price(coin)
now = datetime.now()

# ==========================================
# 4. 核心结算逻辑
# ==========================================
if current_price is not None:
    updated = False
    for od in st.session_state.orders:
        if od.get("状态") == "待结算" and now >= od.get("结算时间"):
            p_close = get_price(od["资产"]) # 跨币种核心：获取订单当时对应的资产价
            if p_close:
                od["平仓价"] = p_close
                od["平仓时间"] = now
                win = (od["方向"] == "看涨" and od["平仓价"] > od["开仓价"]) or \
                      (od["方向"] == "看跌" and od["平仓价"] < od["开仓价"])
                if win: st.session_state.balance += od["金额"] * 1.8
                od.update({
                    "状态": "已结算", 
                    "结果": "W" if win else "L", 
                    "收益": (od["金额"] * 0.8) if win else -od["金额"]
                })
                updated = True
    if updated: save_db(st.session_state.balance, st.session_state.orders)

# ==========================================
# 5. 战报统计计算
# ==========================================
settled = [o for o in st.session_state.orders if o.get("状态") == "已结算"]
today_str = now.strftime('%Y-%m-%d')
today_orders = [o for o in settled if o.get("结算时间").strftime('%Y-%m-%d') == today_str]

today_pnl = sum([o.get("收益", 0) for o in today_orders])
total_pnl = sum([o.get("收益", 0) for o in settled])
win_rate = (len([o for o in settled if o.get("结果") == "W"]) / len(settled) * 100) if settled else 0

# ==========================================
# 6. 【指令增强版】针对图表重载优化的渲染逻辑
# ==========================================
# 准备当前资产的活跃订单数据
active_orders_js = [
    {"price": o['开仓价'], "color": "#02C076" if o['方向'] == "看涨" else "#CF304A"} 
    for o in st.session_state.orders if o['状态'] == '待结算' and o['资产'] == coin
]
# 准备历史结算数据
history_marks_js = [
    {"time": int(o['开仓时间'].timestamp()), "price": o['开仓价'], "res": o['结果']}
    for o in st.session_state.orders if o.get("状态") == "已结算" and o.get("资产") == coin
]

tv_html = f"""
<div id="tv_chart_container" style="height:450px;"></div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
    // 1. 初始化图表变量
    var tvWidget = new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{coin}",
        "interval": "1",
        "theme": "light",
        "style": "1",
        "locale": "zh_CN",
        "container_id": "tv_chart_container",
        "hide_side_toolbar": false,
        "allow_symbol_change": false,
        "timezone": "Asia/Shanghai"
    }});

    // 2. 定义核心绘图函数
    function drawEverything() {{
        try {{
            var chart = tvWidget.chart();
            if (!chart) return;

            // 清除之前的线和形状，避免重复
            chart.removeAllShapes();

            // 绘制当前待结算的虚线
            var active = {json.dumps(active_orders_js)};
            active.forEach(function(o) {{
                chart.createShape({{time: 0, price: o.price}}, {{
                    shape: 'horizontal_line',
                    lock: true,
                    overrides: {{
                        linecolor: o.color,
                        linestyle: 2,
                        linewidth: 2,
                        showLabel: true,
                        textcolor: o.color,
                        fontsize: 12
                    }}
                }});
            }});

            // 绘制历史 W/L 箭头和文字
            var marks = {json.dumps(history_marks_js)};
            marks.forEach(function(m) {{
                var isWin = m.res === "W";
                chart.createShape({{time: m.time, price: m.price}}, {{
                    shape: isWin ? 'arrow_up' : 'arrow_down',
                    lock: true,
                    text: isWin ? "WIN (W)" : "LOSS (L)",
                    overrides: {{
                        color: isWin ? "#02C076" : "#CF304A",
                        showLabel: true,
                        fontsize: 14,
                        fontBold: true,
                        textcolor: isWin ? "#02C076" : "#CF304A"
                    }}
                }});
            }});
        }} catch(e) {{
            console.error("Drawing Error:", e);
        }}
    }}

    // 3. 关键：确保图表完全就绪后触发展开
    tvWidget.onChartReady(function() {{
        // 给绘图引擎一点点缓冲时间
        setTimeout(drawEverything, 800);
    }});
</script>
"""
components.html(tv_html, height=460)

# ==========================================
# 7. 主界面渲染 (修正 ValueError 处理)
# ==========================================
c1, c2, c3 = st.columns(3)
display_price = current_price if current_price is not None else 0.0

with c1: st.markdown(f"<div class='metric-card'><b>可用余额</b><br><h2 style='margin:0;'>${st.session_state.balance:,.2f}</h2></div>", unsafe_allow_html=True)
with c2: st.markdown(f"<div class='metric-card'><b>{coin} 实时价</b><br><h2 style='margin:0;'>${display_price:,.2f}</h2></div>", unsafe_allow_html=True)
with c3: st.markdown(f"<div class='metric-card'><b>总胜率</b><br><h2 style='margin:0;'>{win_rate:.1f}%</h2></div>", unsafe_allow_html=True)

components.html(tv_html, height=460)

# 下单区
col_up, col_down = st.columns(2)
if col_up.button("🟢 看涨 (BUY UP)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看涨", "开仓价": current_price, "平仓价": None, "金额": bet,
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

if col_down.button("🔴 看跌 (SELL DOWN)") and current_price:
    if st.session_state.balance >= bet:
        st.session_state.balance -= bet
        st.session_state.orders.append({
            "资产": coin, "方向": "看跌", "开仓价": current_price, "平仓价": None, "金额": bet,
            "开仓时间": now, "结算时间": now + timedelta(minutes=duration), "状态": "待结算", "结果": None
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

# 实时战报与详细流水
st.write("---")
st.markdown(f"**📈 今日盈亏:** `${today_pnl:,.2f}` | **🌍 累计盈亏:** `${total_pnl:,.2f}`")

st.subheader(f"📋 {coin} 详细执行流水")
if st.session_state.orders:
    history = []
    for od in reversed(st.session_state.orders[-15:]):
        rem = (od.get("结算时间", now) - now).total_seconds()
        
        # 格式化平仓/实时价显示
        if od.get('平仓价'):
            p_display = f"{od['平仓价']:,.2f}"
        else:
            p_display = f"📡 {display_price:,.2f}"
            
        history.append({
            "资产": od.get("资产"),
            "方向": "上涨 ↗️" if od["方向"] == "看涨" else "下跌 ↘️",
            "投入": f"{od['金额']} U",
            "开仓基准": f"{od['开仓价']:,.2f}",
            "当前/平仓": p_display,
            "开仓时间": od['开仓时间'].strftime('%H:%M:%S') if isinstance(od.get('开仓时间'), datetime) else "-",
            "平仓时间": od['平仓时间'].strftime('%H:%M:%S') if isinstance(od.get('平仓时间'), datetime) else "等待中...",
            "状态/结果": od['结果'] if od['结果'] else f"倒计时 {int(rem)}s"
        })
    st.table(history)


