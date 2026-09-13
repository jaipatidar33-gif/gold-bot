import requests, time
import pandas as pd

TG = "8941406579:AAFy7sk6aW6ltjPF7WwFf7k2cSHAcVhD3OA"
CI = "5885172416"
DK = "a5b46acb32794be5b116e70884a6d95a"

def fetch(i, s):
    u = "https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=" + i + "&outputsize=" + str(s) + "&apikey=" + DK
    r = requests.get(u, timeout=30).json()
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

def run(session):
    data = {}
    for n, i, s in [("daily", "1day", 150), ("h1", "1h", 250), ("m5", "5min", 300)]:
        data[n] = fetch(i, s)
        time.sleep(10)
    if data["daily"] is None or data["h1"] is None or data["m5"] is None:
        return
    daily = data["daily"]
    h1 = data["h1"]
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
    closes = h1["close"].tolist()
    e200 = ema(closes, 200)
    if cur > e200:
        bull.append("Above EMA200")
    else:
        bear.append("Below EMA200")
    r = rsi(closes)
    if r < 30:
        bull.append("RSI Oversold " + str(round(r, 1)))
    if r > 70:
        bear.append("RSI Overbought " + str(round(r, 1)))
    if 50 < r < 70:
        bull.append("RSI Bullish " + str(round(r, 1)))
    if 30 < r < 50:
        bear.append("RSI Bearish " + str(round(r, 1)))
    bS = len(bull)
    sS = len(bear)
    conf = max(bS, sS)
    action = "WAIT"
    entry = 0
    sl = 0
    tp1 = 0
    tp2 = 0
    tp3 = 0
    if bS > sS and bS >= 2:
        action = "BUY"
        entry = cur
        sl = cur - adr * 0.5
        tp1 = cur + adr * 0.5
        tp2 = cur + adr
        tp3 = cur + adr * 1.5
    elif sS > bS and sS >= 2:
        action = "SELL"
        entry = cur
        sl = cur + adr * 0.5
        tp1 = cur - adr * 0.5
        tp2 = cur - adr
        tp3 = cur - adr * 1.5
    sl_pips = 0
    rr = 0
    if action != "WAIT":
        sl_pips = abs(entry - sl) * 10
        rr = abs(tp1 - entry) / abs(entry - sl)
    em = "GOLD"
    if session == "MORNING":
        em = "MORN"
    if session == "NY_OPEN":
        em = "NY-OPEN"
    if session == "NY_CLOSE":
        em = "NY-CLOSE"
    if action == "WAIT":
        text = em + " No Signal " + session + "\nPrice: " + str(round(cur, 2)) + "\nBull " + str(bS) + " Bear " + str(sS)
    else:
        rs = bull if action == "BUY" else bear
        text = em + " " + action + " - " + session
        text = text + "\nEntry: " + str(round(entry, 2))
        text = text + "\nSL: " + str(round(sl, 2)) + " (" + str(round(sl_pips)) + " pips)"
        text = text + "\nTP1: " + str(round(tp1, 2))
        text = text + "\nTP2: " + str(round(tp2, 2))
        text = text + "\nTP3: " + str(round(tp3, 2))
        text = text + "\nRR: 1:" + str(round(rr, 2))
        text = text + "\nConf: " + str(conf)
        text = text + "\nReasons:\n" + "\n".join(rs[:6])
    requests.post("https://api.telegram.org/bot" + TG + "/sendMessage", data={"chat_id": CI, "text": text}, timeout=30)
    print("Done: " + action)

if __name__ == "__main__":
    run("MORNING")
