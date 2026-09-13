import requests, time
import pandas as pd

TG = "8941406579:AAFy7sk6aW6ltjPF7WwFf7k2cSHAcVhD3OA"
CI = "5885172416"
DK = "a5b46acb32794be5b116e70884a6d95a"

def fetch(i, s):
    u = "https://api.twelvedata.com/time_series"
    p = {"symbol": "XAU/USD", "interval": i, "outputsize": s, "apikey": DK}
    r = requests.get(u, params=p, timeout=30).json()
    if "values" not in r:
        return None
    d = pd.DataFrame(r["values"])
    d["dt"] = pd.to_datetime(d["datetime"])
    for c in ["open", "high", "low", "close"]:
        d[c] = d[c].astype(float)
    return d.sort_values("dt").reset_index(drop=True)

def ema(a, p):
    k = 2.0 / (p + 1)
    e = a[0]
    for x in a[1:]:
        e = x * k + e * (1 - k)
    return e

def rsi(a, p=14):
    g = 0
    l = 0
    for i in range(len(a) - p, len(a)):
        d = a[i] - a[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    if l == 0:
        return 100
    return 100 - 100 / (1 + (g / p) / (l / p))

def run():
    data = {}
    tfs = [("daily", "1day", 150), ("h4", "4h", 200), ("h1", "1h", 250), ("m15", "15min", 200), ("m5", "5min", 200)]
    for n, i, s in tfs:
        data[n] = fetch(i, s)
        time.sleep(8)
    if any(v is None for v in data.values()):
        print("Fetch failed")
        return
    daily = data["daily"]
    h4 = data["h4"]
    h1 = data["h1"]
    m15 = data["m15"]
    m5 = data["m5"]
    cur = m5["close"].iloc[-1]
    bull = []
    bear = []
    d_hi = daily["high"].max()
    d_lo = daily["low"].min()
    d_mid = (d_hi + d_lo) / 2
    if cur > d_mid:
        bull.append("Above 50%")
    else:
        bear.append("Below 50%")
    adr = (daily.tail(30)["high"] - daily.tail(30)["low"]).mean()
    if h4.iloc[-1]["close"] > h4["high"].iloc[-12:-1].max():
        bull.append("4H BOS UP")
    if h4.iloc[-1]["close"] < h4["low"].iloc[-12:-1].min():
        bear.append("4H BOS DN")
    if h1.iloc[-1]["close"] > h1["high"].iloc[-15:-1].max():
        bull.append("1H MSS UP")
    if h1.iloc[-1]["close"] < h1["low"].iloc[-15:-1].min():
        bear.append("1H MSS DN")
    if m15.iloc[-1]["close"] > m15["high"].iloc[-10:-1].max():
        bull.append("15M MSS UP")
    if m15.iloc[-1]["close"] < m15["low"].iloc[-10:-1].min():
        bear.append("15M MSS DN")
    closes = h1["close"].tolist()
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    if cur > e50 and e50 > e200:
        bull.append("EMA50>200")
    if cur < e50 and e50 < e200:
        bear.append("EMA50<200")
    if cur > e200:
        bull.append("Above EMA200")
    else:
        bear.append("Below EMA200")
    r = rsi(closes)
    if r < 30:
        bull.append("RSI Oversold")
    if r > 70:
        bear.append("RSI Overbought")
    if 50 < r < 70:
        bull.append("RSI Bullish")
    if 30 < r < 50:
        bear.append("RSI Bearish")
    m_now = ema(closes[-50:], 12) - ema(closes[-50:], 26)
    m_prev = ema(closes[-51:-1], 12) - ema(closes[-51:-1], 26)
    if m_now > 0 and m_prev <= 0:
        bull.append("MACD UP")
    if m_now < 0 and m_prev >= 0:
        bear.append("MACD DN")
    if m_now > 0:
        bull.append("MACD Positive")
    else:
        bear.append("MACD Negative")
    pdh = daily["high"].iloc[-2]
    pdl = daily["low"].iloc[-2]
    if abs(cur - pdh) < adr * 0.25:
        bear.append("Near PDH")
    if abs(cur - pdl) < adr * 0.25:
        bull.append("Near PDL")
    bS = len(bull)
    sS = len(bear)
    conf = max(bS, sS)
    if conf < 4:
        print("Conf " + str(conf) + " skip")
        return
    if bS > sS:
        action = "LONG"
        reasons = bull
    else:
        action = "SHORT"
        reasons = bear
    entry = cur
    if action == "LONG":
    sl = cur - 18
    tp1 = cur + 18
    tp2 = cur + 27
    tp3 = cur + 36
else:
    sl = cur + 18
    tp1 = cur - 18
    tp2 = cur - 27
    tp3 = cur - 36
    sl_pips = abs(entry - sl) * 10
    rr = abs(tp1 - entry) / abs(entry - sl)
    text = "GOLD " + action
    text = text + "\nEntry: " + str(round(entry, 2))
    text = text + "\nSL: " + str(round(sl, 2)) + " (" + str(round(sl_pips)) + " pips)"
    text = text + "\nTP1: " + str(round(tp1, 2))
    text = text + "\nTP2: " + str(round(tp2, 2))
    text = text + "\nTP3: " + str(round(tp3, 2))
    text = text + "\nRR: 1:" + str(round(rr, 2))
    text = text + "\nConf: " + str(conf) + "/10"
    text = text + "\nReasons:\n" + "\n".join(reasons[:8])
    requests.post("https://api.telegram.org/bot" + TG + "/sendMessage",
                  data={"chat_id": CI, "text": text}, timeout=30)
    print("Sent: " + action)

run()
