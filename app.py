import streamlit as st
import pandas as pd
import requests, json, os, time
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# ======================
# 基础配置
# ======================
st.set_page_config(
    page_title="事件合约",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_FILE = "event_contract_db.json"

# ======================
# 全局样式（Binance Mobile）
# ======================
st.markdown("""
<style>
.stApp { background:#FFFFFF; max-width:420px; margin:auto; }
h1,h2,h3,h4 { margin:0; padding:0; }

.header {
    height:44px; display:flex; align-items:center; justify-content:center;
    font-size:18px; font-weight:700;
    border-bottom:1px solid #E5E5EA;
}

.pair-bar {
    height:60px; padding:8px 16px;
    display:flex; justify-content:space-between; align-items:center;
    border-bottom:1px solid #F5F5F7;
}

.pair-name { font-size:24px; font-weight:700; }
.odds-up { color:#00B578; font-weight:600; }
.odds-down { color:#FF3141; font-weight:600; }

.section { padding:8px 0; }

.btn-up button {
    background:#00B578!important; color:#FFF!important;
    height:44px; border-radius:8px!important;
    font-size:18px!important; font-weight:700!important;
}
.btn-down button {
    background:#FF3141!important; color:#FFF!important;
    height:44px; border-radius:8px!important;
    font-size:18px!important; font-weight:700!important;
}

.order-item {
    padding:12px 16px;
    border-bottom:1px solid #F5F5F7;
}
.order-row { display:flex; justify-content:space-between; }
.small { font-size:12px; color:#8E8E93; }

</style>
""", unsafe_allow_html=True)

# ======================
# 工具函数
# ======================
def bj_time():
    return datetime.utcnow() + timedelta(hours=8)

def get_price(symbol):
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=2
        ).json()
        return float(r["price"])
    except:
        try:
            g = symbol.replace("USDT","_USDT")
            r = requests.get(
                f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={g}",
                timeout=2
            ).json()
            return float(r[0]["last"])
        except:
            return None

def get_klines(symbol, interval):
    try:
        g = symbol.replace("USDT","_USDT")
        r = requests.get(
            f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={g}&interval={interval}&limit=120",
            timeout=3
        ).json()
        df = pd.DataFrame(r).iloc[:,[0,5,3,4,2,1]]
        df.columns=["time","open","high","low","close","vol"]
        df["time"]=pd.to_datetime(df["time"].astype(int),unit="s")+timedelta(hours=8)
        df[["open","high","low","close"]] = df[["open","high","low","close"]].astype(float)
        return df
    except:
        return pd.DataFrame()

def load_db():
    if os.path.exists(DB_FILE):
        d=json.load(open(DB_FILE))
        for o in d["orders"]:
            for k in ["open_time","close_time"]:
                o[k]=datetime.strptime(o[k],"%Y-%m-%d %H:%M:%S")
        return d["balance"], d["orders"]
    return 1000.0, []

def save_db(balance, orders):
    out=[]
    for o in orders:
        t=o.copy()
        for k in ["open_time","close_time"]:
            t[k]=t[k].strftime("%Y-%m-%d %H:%M:%S")
        out.append(t)
    json.dump({"balance":balance,"orders":out}, open(DB_FILE,"w"))

if "balance" not in st.session_state:
    st.session_state.balance, st.session_state.orders = load_db()

# ======================
# Header
# ======================
st.markdown('<div class="header">事件合约</div>', unsafe_allow_html=True)

# ======================
# 交易对 & 赔率
# ======================
coin = st.selectbox("", ["BTCUSDT","ETHUSDT","SOLUSDT"], index=0)

st.markdown(f"""
<div class="pair-bar">
  <div class="pair-name">{coin}</div>
  <div>
    <span class="odds-up">上涨 80%</span>&nbsp;&nbsp;
    <span class="odds-down">下跌 80%</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ======================
# 图表
# ======================
mode = st.radio("K线", ["原生 K 线","TradingView"], horizontal=True)
interval = st.radio("周期", ["1m","5m","15m","1h"], horizontal=True)

if mode=="TradingView":
    components.html(f"""
    <div style="height:320px">
    <script src="https://s3.tradingview.com/tv.js"></script>
    <script>
    new TradingView.widget({{
        autosize:true,
        symbol:"BINANCE:{coin}",
        interval:"{interval.replace('m','')}",
        theme:"light",
        locale:"zh_CN",
        container_id:"tv"
    }});
    </script>
    <div id="tv" style="height:320px"></div>
    </div>
    """, height=320)
else:
    import plotly.graph_objects as go
    df = get_klines(coin, interval)
    if not df.empty:
        df["ma"]=df.close.rolling(20).mean()
        df["std"]=df.close.rolling(20).std()
        df["up"]=df.ma+2*df.std
        df["dn"]=df.ma-2*df.std

        fig=go.Figure()
        fig.add_candlestick(
            x=df.time, open=df.open, high=df.high,
            low=df.low, close=df.close,
            increasing_fillcolor="#00B578",
            decreasing_fillcolor="#FF3141"
        )
        fig.add_scatter(x=df.time,y=df.up,line=dict(color="#00B578",width=3))
        fig.add_scatter(x=df.time,y=df.dn,line=dict(color="#FF3141",width=3))
        fig.add_scatter(x=df.time,y=df.ma,line=dict(color="#FCD535",width=3))

        for o in st.session_state.orders:
            if o["status"]=="OPEN" and o["symbol"]==coin:
                fig.add_hline(
                    y=o["open_price"],
                    line=dict(
                        color="#00B578" if o["side"]=="UP" else "#FF3141",
                        dash="dash"
                    ),
                    annotation_text="⬆️" if o["side"]=="UP" else "⬇️"
                )

        fig.update_layout(height=320,margin=dict(l=0,r=0,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)

# ======================
# 下单
# ======================
amount = st.number_input("数量(USDT)",10.0,5000.0,100.0)

c1,c2 = st.columns(2)
price = get_price(coin)
now = bj_time()

def place(side):
    if st.session_state.balance>=amount:
        st.session_state.balance-=amount
        st.session_state.orders.append({
            "symbol":coin,
            "side":side,
            "open_price":price,
            "close_price":None,
            "amount":amount,
            "open_time":now,
            "close_time":now+timedelta(minutes=5),
            "status":"OPEN"
        })
        save_db(st.session_state.balance, st.session_state.orders)
        st.rerun()

with c1:
    st.markdown('<div class="btn-up">', unsafe_allow_html=True)
    if st.button("上涨"):
        place("UP")
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="btn-down">', unsafe_allow_html=True)
    if st.button("下跌"):
        place("DOWN")
    st.markdown('</div>', unsafe_allow_html=True)

# ======================
# 订单列表
# ======================
st.markdown("### 已开仓")
for o in reversed(st.session_state.orders):
    st.markdown(f"""
    <div class="order-item">
      <div class="order-row">
        <b>{o['symbol']} {"⬆️" if o['side']=="UP" else "⬇️"}</b>
        <span class="small">USDT {o['amount']}</span>
      </div>
      <div class="small">
        开仓价 {o['open_price']} | {o['open_time']}
      </div>
      <div class="small">
        平仓时间 {o['close_time']}
      </div>
    </div>
    """, unsafe_allow_html=True)
