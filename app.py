import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import threading
import time
from datetime import datetime

# =========================
# 页面 & 样式（偏币安）
# =========================
st.set_page_config(
    page_title="BTC 模拟行情",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
    html, body, [class*="css"]  {
        background-color: #0b0e11;
        color: #eaecef;
    }
    .stPlotlyChart {
        background-color: #0b0e11;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================
# 全局状态
# =========================
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(
        columns=["time", "open", "high", "low", "close"]
    )

if "running" not in st.session_state:
    st.session_state.running = True


# =========================
# 模拟行情线程（假数据）
# =========================
def price_feed():
    price = 42000.0
    while st.session_state.running:
        now = datetime.now()

        open_ = price
        change = np.random.normal(0, 15)
        close = price + change
        high = max(open_, close) + abs(np.random.normal(0, 8))
        low = min(open_, close) - abs(np.random.normal(0, 8))
        price = close

        new_row = pd.DataFrame(
            [[now, open_, high, low, close]],
            columns=["time", "open", "high", "low", "close"]
        )

        st.session_state.df = pd.concat(
            [st.session_state.df, new_row],
            ignore_index=True
        ).tail(300)

        time.sleep(1)


# =========================
# 启动线程（只启动一次）
# =========================
if "thread_started" not in st.session_state:
    t = threading.Thread(target=price_feed, daemon=True)
    t.start()
    st.session_state.thread_started = True


# =========================
# 计算布林带（修复版）
# =========================
def add_bollinger(df, n=20):
    df = df.copy()
    df["ma"] = df["close"].rolling(n).mean()
    df["std"] = df["close"].rolling(n).std()
    df["upper"] = df["ma"] + 2 * df["std"]
    df["lower"] = df["ma"] - 2 * df["std"]
    return df


# =========================
# UI
# =========================
st.markdown("## BTC/USDT 模拟行情（币安风格）")

df = st.session_state.df

if len(df) < 25:
    st.info("行情初始化中...")
    st.stop()

df = add_bollinger(df)

# =========================
# K线 + 布林
# =========================
fig = go.Figure()

fig.add_trace(
    go.Candlestick(
        x=df["time"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="K线",
        increasing_line_color="#0ecb81",
        decreasing_line_color="#f6465d",
    )
)

fig.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["upper"],
        line=dict(color="rgba(255,255,255,0.3)", width=1),
        name="上轨",
    )
)

fig.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["lower"],
        line=dict(color="rgba(255,255,255,0.3)", width=1),
        fill="tonexty",
        fillcolor="rgba(255,255,255,0.05)",
        name="下轨",
    )
)

fig.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["ma"],
        line=dict(color="#f0b90b", width=1),
        name="中轨",
    )
)

fig.update_layout(
    height=650,
    xaxis_rangeslider_visible=False,
    plot_bgcolor="#0b0e11",
    paper_bgcolor="#0b0e11",
    font=dict(color="#eaecef"),
    margin=dict(l=10, r=10, t=30, b=10),
)

st.plotly_chart(fig, use_container_width=True)

# =========================
# 自动刷新（关键）
# =========================
time.sleep(1)
st.experimental_rerun()
