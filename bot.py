import requests, time, os, json, base64
import pandas as pd
from datetime import datetime, timezone, timedelta

TG = os.environ.get("TG_TOKEN")
CI = os.environ.get("TG_CHAT")
DK = os.environ.get("TD_KEY")
GH_TOKEN = os.environ.get("GITHUB_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
STATE_FILE = "state.json"


# ==================== STATE ====================
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"position": None, "counter": None, "last_session": "",
                "session_open": None, "session_open_time": "",
                "exhaust_alerted": "", "ny_close_alerted": "",
                "weekend_alerted": "", "last_normal_run": "",
                "last_hold_msg": "", "neutral_alerted": "",
                "last_mode": "", "last_sl_time": "",
                "daily_loss": 0, "wins": 0, "losses": 0,
                "today_trades": 0, "today_date": "",
                "daily_summary_sent": "", "last_signal_price": 0,
                "last_signal_dir": "", "confluence_history": [],
                "peak_equity": 1000, "current_equity": 1000,
                "active_trades": [], "closed_trades": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    if not GH_TOKEN or not GH_REPO:
        return
    api = "https://api.github.com/repos/" + GH_REPO + "/contents/" + STATE_FILE
    headers = {"Authorization": "token " + GH_TOKEN}
    try:
        r = requests.get(api, headers=headers)
        sha = r.json().get("sha") if r.status_code == 200 else None
        content = base64.b64encode(json.dumps(state, indent=2).encode()).decode()
        data = {"message": "state update", "content": content}
        if sha:
            data["sha"] = sha
        requests.put(api, headers=headers, json=data, timeout=30)
    except Exception as e:
        print("State save failed: " + str(e))


def send_telegram(msg):
    try:
        requests.post(
            "https://api.telegram.org/bot" + TG + "/sendMessage",
            data={"chat_id": CI, "text": msg},
            timeout=30,
        )
    except Exception as e:
        print("Telegram send failed: " + str(e))


# ==================== TIME / HOLIDAY ====================
def to_ist(dt_utc):
    return dt_utc + timedelta(hours=5, minutes=30)


def ist_now():
    return to_ist(datetime.now(timezone.utc))


def format_ist_time(dt_utc):
    ist = to_ist(dt_utc)
    h24 = ist.hour
    m = ist.minute
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return str(h12) + ":" + str(m).zfill(2) + " " + ampm + " IST"


def format_ist_date(dt_utc):
    ist = to_ist(dt_utc)
    return ist.strftime("%d-%m-%Y")


def is_weekend():
    """Saturday / Sunday market closed"""
    dow = datetime.now(timezone.utc).weekday()
    # 5 = Saturday, 6 = Sunday
    return dow in [5, 6]


def get_us_holidays(year):
    """US market holidays (rough dates)"""
    holidays = [
        (1, 1),   # New Year
        (7, 4),   # Independence Day
        (12, 25), # Christmas
    ]
    # MLK (3rd Mon Jan)
    holidays.append((1, 20))
    # Presidents (3rd Mon Feb)
    holidays.append((2, 17))
    # Memorial (last Mon May)
    holidays.append((5, 26))
    # Labor (1st Mon Sep)
    holidays.append((9, 1))
    # Thanksgiving (4th Thu Nov)
    holidays.append((11, 27))
    return holidays


def is_holiday():
    now = datetime.now(timezone.utc)
    holidays = get_us_holidays(now.year)
    for m, d in holidays:
        if now.month == m and now.day == d:
            return True
    return False


def is_market_open():
    """Market open Mon-Fri (Friday full), closed Sat/Sun + holidays"""
    if is_weekend():
        return False
    if is_holiday():
        return False
    return True


# ==================== DST / SESSION ====================
def get_dst_flags():
    try:
        now_utc = pd.Timestamp.now(tz='UTC')
        ny_dst = now_utc.tz_convert('America/New_York').dst().total_seconds() > 0
        london_dst = now_utc.tz_convert('Europe/London').dst().total_seconds() > 0
        sydney_dst = now_utc.tz_convert('Australia/Sydney').dst().total_seconds() > 0
        return ny_dst, london_dst, sydney_dst
    except Exception:
        return False, False, False


def get_session():
    h = datetime.now(timezone.utc).hour
    ny_dst, london_dst, sydney_dst = get_dst_flags()
    london_open = 7 if london_dst else 8
    london_close = 16 if london_dst else 17
    ny_open = 12 if ny_dst else 13
    ny_close = 21 if ny_dst else 22
    if ny_close <= h or h < 9:
        return "SYDNEY"
    if 9 <= h < london_open:
        return "TOKYO"
    if london_open <= h < ny_open:
        return "LONDON"
    if ny_open <= h < london_close:
        return "NY_OVERLAP"
    if london_close <= h < ny_close:
        return "NEWYORK"
    return "SYDNEY"


def is_active_session(session):
    return session in ["LONDON", "NY_OVERLAP", "NEWYORK"]


def get_session_segment(m5, session):
    today = m5["dt"].iloc[-1].date()
    ny_dst, london_dst, sydney_dst = get_dst_flags()
    london_open = 7 if london_dst else 8
    ny_open = 12 if ny_dst else 13
    london_close = 16 if london_dst else 17
    ny_close = 21 if ny_dst else 22
    if session == "SYDNEY":
        return m5[(m5["dt"].dt.date == today) & ((m5["dt"].dt.hour >= ny_close) | (m5["dt"].dt.hour < 9))]
    if session == "TOKYO":
        return m5[(m5["dt"].dt.date == today) & (m5["dt"].dt.hour >= 9) & (m5["dt"].dt.hour < london_open)]
    if session == "LONDON":
        return m5[(m5["dt"].dt.date == today) & (m5["dt"].dt.hour >= london_open) & (m5["dt"].dt.hour < ny_open)]
    if session == "NY_OVERLAP":
        return m5[(m5["dt"].dt.date == today) & (m5["dt"].dt.hour >= ny_open) & (m5["dt"].dt.hour < london_close)]
    if session == "NEWYORK":
        return m5[(m5["dt"].dt.date == today) & (m5["dt"].dt.hour >= london_close) & (m5["dt"].dt.hour < ny_close)]
    return m5.tail(50)


def is_session_transition(old_session, new_session):
    if not old_session or old_session == new_session:
        return False
    valid = [
        ("SYDNEY", "TOKYO"), ("TOKYO", "LONDON"),
        ("LONDON", "NY_OVERLAP"), ("NY_OVERLAP", "NEWYORK"),
        ("NEWYORK", "SYDNEY"),
    ]
    return (old_session, new_session) in valid


def is_ny_close():
    now = datetime.now(timezone.utc)
    ny_dst, _, _ = get_dst_flags()
    ny_close_h = 21 if ny_dst else 22
    return now.hour == ny_close_h and now.minute < 10


def is_friday_close():
    """Friday 20:00 UTC = weekend close warning"""
    now = datetime.now(timezone.utc)
    return now.weekday() == 4 and now.hour == 20 and now.minute < 10


# ==================== NEWS ====================
def is_news_time():
    now = datetime.now(timezone.utc)
    h, m, dow = now.hour, now.minute, now.weekday()
    ny_dst, _, _ = get_dst_flags()
    nfp_h = 12 if ny_dst else 13
    cpi_h = 12 if ny_dst else 13
    fed_h = 18 if ny_dst else 19
    if dow == 4 and h == nfp_h and 25 <= m <= 40:
        return "NFP"
    if dow in [0, 1, 2, 3, 4] and h == fed_h and 55 <= m <= 65:
        return "FED"
    if dow in [0, 1, 2, 3, 4] and h == cpi_h and 25 <= m <= 40:
        return "CPI"
    return None


def is_pre_news():
    now = datetime.now(timezone.utc)
    h, m, dow = now.hour, now.minute, now.weekday()
    ny_dst, _, _ = get_dst_flags()
    nfp_h = 12 if ny_dst else 13
    cpi_h = 12 if ny_dst else 13
    fed_h = 18 if ny_dst else 19
    if dow == 4 and h == nfp_h and 10 <= m <= 24:
        return "NFP in " + str(25 - m) + " min"
    if dow in [0, 1, 2, 3, 4] and h == fed_h and 40 <= m <= 54:
        return "FED in " + str(55 - m) + " min"
    if dow in [0, 1, 2, 3, 4] and h == cpi_h and 10 <= m <= 24:
        return "CPI in " + str(25 - m) + " min"
    return None


def get_news_day():
    now = datetime.now(timezone.utc)
    dow, d = now.weekday(), now.day
    w = []
    if dow == 4 and 1 <= d <= 7:
        w.append("NFP Friday")
    if dow == 2 and 10 <= d <= 14:
        w.append("CPI Day")
    if dow == 3 and 15 <= d <= 21:
        w.append("FOMC Possible")
    return w


# ==================== DATA ====================
def fetch(i, s):
    u = "https://api.twelvedata.com/time_series"
    p = {"symbol": "XAU/USD", "interval": i, "outputsize": s, "apikey": DK}
    try:
        r = requests.get(u, params=p, timeout=20).json()
    except Exception:
        return None
    if "values" not in r:
        return None
    d = pd.DataFrame(r["values"])
    d["dt"] = pd.to_datetime(d["datetime"])
    for c in ["open", "high", "low", "close"]:
        d[c] = d[c].astype(float)
    return d.sort_values("dt").reset_index(drop=True)


def fetch_live_price():
    try:
        u = "https://api.twelvedata.com/price"
        p = {"symbol": "XAU/USD", "apikey": DK}
        r = requests.get(u, params=p, timeout=8).json()
        if "price" in r:
            return float(r["price"])
    except Exception as e:
        print("Live price failed: " + str(e))
    return None


# ==================== INDICATORS ====================
def ema(a, p):
    k = 2.0 / (p + 1)
    e = a[0]
    for x in a[1:]:
        e = x * k + e * (1 - k)
    return e


def sma(a, p):
    if len(a) < p:
        return a[-1]
    return sum(a[-p:]) / p


def rsi(a, p=14):
    if len(a) < p + 1:
        return 50
    g = l = 0
    for i in range(len(a) - p, len(a)):
        d = a[i] - a[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    if l == 0:
        return 100
    return 100 - 100 / (1 + (g / p) / (l / p))


def atr(df, p=14):
    if len(df) < p + 1:
        return 0
    tr = []
    for i in range(len(df) - p, len(df)):
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        pc = df["close"].iloc[i - 1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr) / p


def swings(df, w=3):
    H, L = [], []
    for i in range(w, len(df) - w):
        if df["high"].iloc[i] == df["high"].iloc[i - w:i + w + 1].max():
            H.append(df["high"].iloc[i])
        if df["low"].iloc[i] == df["low"].iloc[i - w:i + w + 1].min():
            L.append(df["low"].iloc[i])
    return H, L


def find_fvg(df):
    out = []
    for i in range(2, len(df)):
        c1h, c1l = df["high"].iloc[i - 2], df["low"].iloc[i - 2]
        c3h, c3l = df["high"].iloc[i], df["low"].iloc[i]
        if c1h < c3l:
            out.append({"t": "B", "ce": (c1h + c3l) / 2})
        if c1l > c3h:
            out.append({"t": "S", "ce": (c1l + c3h) / 2})
    return out


def find_ob(df):
    b_ob = s_ob = None
    for i in range(len(df) - 3, max(len(df) - 30, 0), -1):
        c = df.iloc[i]
        n1 = df.iloc[i + 1]
        n2 = df.iloc[i + 2]
        if b_ob is None and c["close"] < c["open"] and n1["close"] > n1["open"] and n2["close"] > n2["open"]:
            b_ob = {"top": c["open"], "bot": c["close"]}
        if s_ob is None and c["close"] > c["open"] and n1["close"] < n1["open"] and n2["close"] < n2["open"]:
            s_ob = {"top": c["close"], "bot": c["open"]}
    return b_ob, s_ob


def check_choch(df):
    H, L = swings(df)
    if len(H) < 3 or len(L) < 3:
        return None
    if H[-1] > H[-2] and L[-1] > L[-2]:
        return "BULL"
    if H[-1] < H[-2] and L[-1] < L[-2]:
        return "BEAR"
    return None


def check_displacement(df, atr_val):
    if len(df) < 3 or atr_val == 0:
        return None
    c = df.iloc[-1]
    body = abs(c["close"] - c["open"])
    if body > atr_val * 1.5:
        return "BULL" if c["close"] > c["open"] else "BEAR"
    return None


def check_equal_levels(levels, tol=5):
    if len(levels) < 2:
        return False
    for i in range(len(levels) - 1):
        if abs(levels[i] - levels[i + 1]) < tol:
            return True
    return False


def check_adx(df, p=14):
    if len(df) < p * 2:
        return 0
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(len(df) - p * 2, len(df)):
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        pc = df["close"].iloc[i - 1]
        ph = df["high"].iloc[i - 1]
        pl = df["low"].iloc[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
        up = h - ph
        dn = pl - l
        plus_dm.append(up if up > dn and up > 0 else 0)
        minus_dm.append(dn if dn > up and dn > 0 else 0)
    atr_v = sum(tr_list[-p:]) / p
    if atr_v == 0:
        return 0
    plus_di = 100 * (sum(plus_dm[-p:]) / p) / atr_v
    minus_di = 100 * (sum(minus_dm[-p:]) / p) / atr_v
    if plus_di + minus_di == 0:
        return 0
    return 100 * abs(plus_di - minus_di) / (plus_di + minus_di)


def bollinger_squeeze(df, p=20):
    if len(df) < p + 10:
        return False
    closes = df["close"].tolist()
    ma = sum(closes[-p:]) / p
    std = (sum([(x - ma) ** 2 for x in closes[-p:]]) / p) ** 0.5
    width_now = (2 * std) / ma if ma else 0
    widths = []
    for i in range(len(closes) - 20, len(closes)):
        m = sum(closes[i - p:i]) / p
        s = (sum([(x - m) ** 2 for x in closes[i - p:i]]) / p) ** 0.5
        widths.append((2 * s) / m if m else 0)
    if not widths:
        return False
    avg_width = sum(widths) / len(widths)
    return width_now < avg_width * 0.7


def atr_sl_tp(df_h1, direction, cur):
    atr_val = atr(df_h1)
    if atr_val == 0:
        atr_val = 15
    sl_dist = max(atr_val, 15)
    if direction == "LONG":
        return cur - sl_dist, cur + sl_dist, cur + sl_dist * 1.5, cur + sl_dist * 2.0
    else:
        return cur + sl_dist, cur - sl_dist, cur - sl_dist * 1.5, cur - sl_dist * 2.0


def check_momentum(m5):
    if len(m5) < 4:
        return None, 0
    ranges = (m5["high"] - m5["low"]).tail(20)
    avg_range = ranges.mean()
    if avg_range == 0:
        return None, 0
    last3 = m5.tail(3)
    last3_move = abs(last3["close"].iloc[-1] - last3["open"].iloc[0])
    speed = last3_move / avg_range
    direction = "BULL" if last3["close"].iloc[-1] > last3["open"].iloc[-1] else "BEAR"
    if speed > 1.2:
        return "FAST_" + direction, speed
    if speed > 0.7:
        return "MED_" + direction, speed
    return "SLOW", speed


def check_price_action(m5):
    if len(m5) < 2:
        return []
    signals = []
    c1 = m5.iloc[-1]
    c2 = m5.iloc[-2]
    body = abs(c1["close"] - c1["open"])
    uw = c1["high"] - max(c1["close"], c1["open"])
    dw = min(c1["close"], c1["open"]) - c1["low"]
    if body == 0:
        body = 0.01
    if dw > body * 2.5 and uw < body * 0.5:
        signals.append("PA: Bull Rejection")
    if uw > body * 2.5 and dw < body * 0.5:
        signals.append("PA: Bear Rejection")
    if c1["close"] > c1["open"] and body > (c1["high"] - c1["low"]) * 0.7:
        signals.append("PA: Strong Bull")
    if c1["close"] < c1["open"] and body > (c1["high"] - c1["low"]) * 0.7:
        signals.append("PA: Strong Bear")
    if c2["close"] < c2["open"] and c1["close"] > c1["open"] and c1["close"] > c2["open"]:
        signals.append("PA: Bull Engulf")
    if c2["close"] > c2["open"] and c1["close"] < c1["open"] and c1["close"] < c2["open"]:
        signals.append("PA: Bear Engulf")
    return signals


def check_5m_engulf(m5):
    if len(m5) < 2:
        return None
    c1 = m5.iloc[-1]
    c2 = m5.iloc[-2]
    if c1["close"] > c1["open"] and c2["close"] < c2["open"]:
        if c1["close"] > c2["open"] and c1["open"] < c2["close"]:
            return "BULL"
    if c1["close"] < c1["open"] and c2["close"] > c2["open"]:
        if c1["close"] < c2["open"] and c1["open"] > c2["close"]:
            return "BEAR"
    return None


def session_vwap(m5, session):
    seg = get_session_segment(m5, session)
    if len(seg) == 0:
        return None
    tp = (seg["high"] + seg["low"] + seg["close"]) / 3
    return tp.mean()


def session_high_low(m5, session):
    seg = get_session_segment(m5, session)
    if len(seg) == 0:
        return None, None
    return seg["high"].max(), seg["low"].min()


def prev_session_close(m5):
    today = m5["dt"].iloc[-1].date()
    yesterday = today - pd.Timedelta(days=1)
    ny_dst, _, _ = get_dst_flags()
    london_close = 16 if ny_dst else 17
    ny_close = 21 if ny_dst else 22
    seg = m5[(m5["dt"].dt.date == yesterday) & (m5["dt"].dt.hour >= london_close) & (m5["dt"].dt.hour < ny_close)]
    if len(seg) == 0:
        return None
    return seg["close"].iloc[-1]


def rsi_divergence(df, lookback=20):
    closes = df["close"].tolist()
    if len(closes) < lookback + 14:
        return None
    recent = closes[-lookback:]
    rsi_now = rsi(closes)
    rsi_prev = rsi(closes[:-5])
    price_high_now = max(recent[-5:])
    price_high_prev = max(recent[-15:-5])
    if price_high_now > price_high_prev and rsi_now < rsi_prev:
        return "BEARISH"
    price_low_now = min(recent[-5:])
    price_low_prev = min(recent[-15:-5])
    if price_low_now < price_low_prev and rsi_now > rsi_prev:
        return "BULLISH"
    return None


def volume_spike(m5):
    ranges = (m5["high"] - m5["low"]).tail(20)
    avg_range = ranges.mean()
    if avg_range == 0:
        return False
    current_range = m5["high"].iloc[-1] - m5["low"].iloc[-1]
    return current_range > avg_range * 1.5


def session_liquidity_map(h1, m15, cur):
    H1, L1 = swings(h1)
    bsl_list = sorted([x for x in H1 if x > cur])[:3]
    ssl_list = sorted([x for x in L1 if x < cur], reverse=True)[:3]
    return {
        "nearest_bsl": bsl_list[0] if bsl_list else None,
        "nearest_ssl": ssl_list[0] if ssl_list else None,
        "far_bsl": bsl_list[-1] if len(bsl_list) > 1 else None,
        "far_ssl": ssl_list[-1] if len(ssl_list) > 1 else None,
    }


def detect_session_exhaustion(m5, m15, h1, session, cur):
    seg = get_session_segment(m5, session)
    if len(seg) < 3:
        return None, 0, {}
    session_high = seg["high"].max()
    session_low = seg["low"].min()
    session_range = session_high - session_low
    daily_ranges = m5.groupby(m5["dt"].dt.date).agg({"high": "max", "low": "min"})
    daily_ranges["range"] = daily_ranges["high"] - daily_ranges["low"]
    adr = daily_ranges["range"].tail(14).mean()
    range_used = session_range / adr if adr > 0 else 0
    rsi_val = rsi(m15["close"].tolist())
    ny_dst, london_dst, sydney_dst = get_dst_flags()
    london_open = 7 if london_dst else 8
    london_close = 16 if london_dst else 17
    ny_open = 12 if ny_dst else 13
    ny_close = 21 if ny_dst else 22
    session_starts = {"SYDNEY": ny_close, "TOKYO": 9, "LONDON": london_open,
                      "NY_OVERLAP": ny_open, "NEWYORK": london_close}
    session_ends = {"SYDNEY": 9, "TOKYO": london_open, "LONDON": ny_open,
                    "NY_OVERLAP": london_close, "NEWYORK": ny_close}
    start_h = session_starts.get(session, 0)
    end_h = session_ends.get(session, 0)
    now_h = datetime.now(timezone.utc).hour
    if end_h > start_h:
        elapsed = (now_h - start_h) / (end_h - start_h)
    else:
        elapsed = 0.5
    elapsed = max(0, min(1, elapsed))
    recent_ranges = (m5["high"] - m5["low"]).tail(5)
    prev_ranges = (m5["high"] - m5["low"]).tail(15).head(10)
    vol_decline = recent_ranges.mean() < prev_ranges.mean() * 0.7 if len(prev_ranges) > 0 else False
    H1, L1 = swings(h1)
    swept_high = len(H1) >= 3 and any(abs(session_high - x) < 1.5 for x in H1[-3:])
    swept_low = len(L1) >= 3 and any(abs(session_low - x) < 1.5 for x in L1[-3:])
    mid = (session_high + session_low) / 2
    bull_score = 0
    bear_score = 0
    if range_used > 0.6:
        if cur > mid: bear_score += 1
        else: bull_score += 1
    if rsi_val > 70: bear_score += 1
    if rsi_val < 30: bull_score += 1
    if elapsed > 0.6:
        if cur > mid: bear_score += 1
        else: bull_score += 1
    if vol_decline:
        if cur > mid: bear_score += 1
        else: bull_score += 1
    if swept_high and cur < session_high: bear_score += 1
    if swept_low and cur > session_low: bull_score += 1
    info = {
        "range_used": round(range_used * 100, 1),
        "rsi": round(rsi_val, 1),
        "elapsed": round(elapsed * 100, 1),
        "vol_decline": vol_decline,
        "sess_high": round(session_high, 2),
        "sess_low": round(session_low, 2),
        "mid": round(mid, 2),
    }
    if range_used < 0.5:
        return None, 0, info
    if bear_score >= 4 and bear_score > bull_score:
        return "BEAR_EXHAUST", bear_score, info
    if bull_score >= 4 and bull_score > bear_score:
        return "BULL_EXHAUST", bull_score, info
    return None, 0, info


def is_session_grace_period(state, session):
    session_open_time = state.get("session_open_time", "")
    if not session_open_time:
        return False
    try:
        open_dt = datetime.strptime(session_open_time, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except Exception:
        return False
    now_utc = datetime.now(timezone.utc)
    mins_since_open = (now_utc - open_dt).total_seconds() / 60
    return mins_since_open < 30


# ==================== NEW: DAILY/WEEKLY LEVELS ====================
def get_daily_open(daily):
    if len(daily) < 1:
        return None
    return daily["open"].iloc[-1]


def get_weekly_open(daily):
    if len(daily) < 5:
        return None
    return daily["open"].iloc[-5]


def detect_judas_swing(m5, session):
    """Judas swing: fake move in first 30 min, then reverse"""
    seg = get_session_segment(m5, session)
    if len(seg) < 6:
        return None
    early = seg.head(6)
    if len(early) < 6:
        return None
    early_high = early["high"].max()
    early_low = early["low"].min()
    cur = seg["close"].iloc[-1]
    session_open = early["open"].iloc[0]
    up_fake = early_high - session_open
    dn_fake = session_open - early_low
    if up_fake > 15 and cur < session_open:
        return "JUDAS_BEAR"
    if dn_fake > 15 and cur > session_open:
        return "JUDAS_BULL"
    return None


# ==================== NEW: FILTERS ====================
def check_late_signal(state, cur, session_open):
    """Skip if price already moved 30+ pips"""
    if not session_open:
        return False
    move = abs(cur - session_open)
    return move > 30


def check_contradiction(state, action):
    """Block signal if contradiction with exhaust"""
    exhaust = state.get("exhaust_alerted", "")
    if "BULL_EXHAUST" in exhaust and action == "SHORT":
        return True
    if "BEAR_EXHAUST" in exhaust and action == "LONG":
        return True
    return False


def check_confluence_stability(state, conf):
    """Conf must be stable across 2 runs"""
    history = state.get("confluence_history", [])
    history.append(conf)
    if len(history) > 3:
        history = history[-3:]
    state["confluence_history"] = history
    if len(history) < 2:
        return False
    return history[-1] >= 6 and history[-2] >= 6


def check_entry_drift(state, cur):
    """Warn if drift > 15 pips"""
    last_price = state.get("last_signal_price", 0)
    if not last_price:
        return None
    drift = abs(cur - last_price)
    if drift > 15:
        return "ENTRY MISSED - Drift " + str(round(drift, 1)) + " pips"
    return None


def check_drawdown(state):
    """Max 5% drawdown protection"""
    peak = state.get("peak_equity", 1000)
    current = state.get("current_equity", 1000)
    if peak == 0:
        return False
    dd_pct = ((peak - current) / peak) * 100
    return dd_pct > 5


def check_max_positions(state):
    """Max 3 concurrent positions"""
    active = state.get("active_trades", [])
    return len(active) >= 3


def check_cooldown(state):
    last_sl = state.get("last_sl_time", "")
    if not last_sl:
        return False
    try:
        sl_dt = datetime.strptime(last_sl, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - sl_dt).total_seconds() / 60
        if diff < 30:
            return True
    except Exception:
        pass
    return False


# ==================== POSITION MANAGEMENT ====================
def check_position(state, cur, now_str):
    pos = state.get("position")
    if not pos:
        return state, None
    side = pos["side"]
    entry = pos["entry"]
    sl = pos["sl"]
    tp1, tp2, tp3 = pos["tp1"], pos["tp2"], pos["tp3"]
    tp_hits = pos.get("tp_hits", [])
    warn_hits = pos.get("warn_hits", [])
    msg = None
    sl_dist = abs(sl - entry)
    trail = pos.get("trailing_sl")

    if side == "LONG":
        if trail and cur <= trail:
            state["position"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "🎯 TRAILING SL HIT - BUY locked profit at " + str(round(trail, 2))
        if cur <= sl:
            state["position"] = None
            state["last_sl_time"] = now_str
            state["losses"] = state.get("losses", 0) + 1
            state["daily_loss"] = state.get("daily_loss", 0) + sl_dist
            return state, "🔴 STOP LOSS HIT - BUY closed at " + str(round(sl, 2))
        adverse = entry - cur
        if 1 not in warn_hits and adverse >= sl_dist * 0.25:
            warn_hits.append(1)
            msg = "⚠️ WARNING 25%: BUY losing " + str(round(adverse, 1))
        if 2 not in warn_hits and adverse >= sl_dist * 0.5:
            warn_hits.append(2)
            msg = "⚠️ WARNING 50%: BUY losing " + str(round(adverse, 1))
        if 3 not in warn_hits and adverse >= sl_dist * 0.75:
            warn_hits.append(3)
            msg = "🚨 DANGER 75%: BUY losing " + str(round(adverse, 1)) + " - CLOSE NOW"
        if 1 not in tp_hits and cur >= tp1:
            tp_hits.append(1)
            pos["sl"] = entry
            msg = "✅ TARGET 1 HIT - BUY +20 pips. SL to entry. Close 50% now."
        if 2 not in tp_hits and cur >= tp2:
            tp_hits.append(2)
            pos["trailing_sl"] = tp1
            msg = "✅ TARGET 2 HIT - BUY +30 pips. Trailing SL at T1."
        if 3 not in tp_hits and cur >= tp3:
            tp_hits.append(3)
            state["position"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "✅ TARGET 3 HIT - BUY +40 pips. Closed."
    elif side == "SHORT":
        if trail and cur >= trail:
            state["position"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "🎯 TRAILING SL HIT - SELL locked profit at " + str(round(trail, 2))
        if cur >= sl:
            state["position"] = None
            state["last_sl_time"] = now_str
            state["losses"] = state.get("losses", 0) + 1
            state["daily_loss"] = state.get("daily_loss", 0) + sl_dist
            return state, "🔴 STOP LOSS HIT - SELL closed at " + str(round(sl, 2))
        adverse = cur - entry
        if 1 not in warn_hits and adverse >= sl_dist * 0.25:
            warn_hits.append(1)
            msg = "⚠️ WARNING 25%: SELL losing " + str(round(adverse, 1))
        if 2 not in warn_hits and adverse >= sl_dist * 0.5:
            warn_hits.append(2)
            msg = "⚠️ WARNING 50%: SELL losing " + str(round(adverse, 1))
        if 3 not in warn_hits and adverse >= sl_dist * 0.75:
            warn_hits.append(3)
            msg = "🚨 DANGER 75%: SELL losing " + str(round(adverse, 1)) + " - CLOSE NOW"
        if 1 not in tp_hits and cur <= tp1:
            tp_hits.append(1)
            pos["sl"] = entry
            msg = "✅ TARGET 1 HIT - SELL +20 pips. SL to entry. Close 50% now."
        if 2 not in tp_hits and cur <= tp2:
            tp_hits.append(2)
            pos["trailing_sl"] = tp1
            msg = "✅ TARGET 2 HIT - SELL +30 pips. Trailing SL at T1."
        if 3 not in tp_hits and cur <= tp3:
            tp_hits.append(3)
            state["position"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "✅ TARGET 3 HIT - SELL +40 pips. Closed."
    pos["tp_hits"] = tp_hits
    pos["warn_hits"] = warn_hits
    state["position"] = pos
    return state, msg


def check_counter(state, cur):
    ctr = state.get("counter")
    if not ctr:
        return state, None
    side = ctr["side"]
    sl = ctr["sl"]
    tp = ctr["tp"]
    if side == "LONG":
        if cur <= sl:
            state["counter"] = None
            return state, "🔴 EXTRA BUY SL hit"
        if cur >= tp:
            state["counter"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "✅ EXTRA BUY +10 pips"
    elif side == "SHORT":
        if cur >= sl:
            state["counter"] = None
            return state, "🔴 EXTRA SELL SL hit"
        if cur <= tp:
            state["counter"] = None
            state["wins"] = state.get("wins", 0) + 1
            return state, "✅ EXTRA SELL +10 pips"
    return state, None


def detect_counter_signal(pos_side, h1, m15, m5, cur, session):
    ch1 = check_choch(h1)
    ch2 = check_choch(m15)
    disp = check_displacement(m15, atr(h1) * 0.5)
    vwap_s = session_vwap(m5, session)
    s_high, s_low = session_high_low(m5, session)
    div = rsi_divergence(m15)
    psc = prev_session_close(m5)
    vol = volume_spike(m5)
    if pos_side == "SHORT":
        c = sum([ch2 == "BULL", ch1 == "BULL", disp == "BULL",
                 bool(vwap_s and cur > vwap_s), bool(s_high and cur > s_high),
                 div == "BULLISH", bool(psc and cur > psc), vol])
        if c >= 5:
            return "LONG", c
    if pos_side == "LONG":
        c = sum([ch2 == "BEAR", ch1 == "BEAR", disp == "BEAR",
                 bool(vwap_s and cur < vwap_s), bool(s_low and cur < s_low),
                 div == "BEARISH", bool(psc and cur < psc), vol])
        if c >= 5:
            return "SHORT", c
    return None, 0


# ==================== MAIN ====================
def run():
    state = load_state()
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    # MARKET OPEN CHECK
    if not is_market_open():
        print("Market closed (weekend/holiday)")
        return

    # COOLDOWN
    if check_cooldown(state):
        print("Cooldown after SL - skip")
        return

    # DRAWDOWN
    if check_drawdown(state):
        print("Drawdown > 5% - skip")
        return

    # DAILY RESET
    today = now_utc.strftime("%Y-%m-%d")
    if state.get("today_date", "") != today:
        state["today_date"] = today
        state["today_trades"] = 0
        state["daily_loss"] = 0
        state["daily_summary_sent"] = ""

    # WEEKEND CLOSE ALERT (Friday)
    if is_friday_close():
        key = now_utc.strftime("%Y-%m-%d")
        if state.get("weekend_alerted", "") != key:
            state["weekend_alerted"] = key
            save_state(state)
            send_telegram("🔔 WEEKEND CLOSE\nFriday market close aa raha hai\n21:00 UTC (2:30 AM IST) pe close\nPositions manage karo")

    # NY CLOSE
    if is_ny_close():
        key = now_utc.strftime("%Y-%m-%d")
        if state.get("ny_close_alerted", "") != key:
            state["ny_close_alerted"] = key
            save_state(state)
            send_telegram("🔔 NEW YORK CLOSE\nMarket close ho raha hai\nAb neutral zone\nSydney open ka wait karo")

    news = is_news_time()
    if news:
        print("News time - skip")
        return

    pre = is_pre_news()
    news_days = get_news_day()
    session = get_session()

    # TIME GATE — Session 5 min, Normal 10 min (actual cron side)
    if not is_active_session(session):
        last = state.get("last_normal_run", "")
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                if (now_utc - last_dt).total_seconds() / 60 < 9:
                    print("Normal session skip")
                    return
            except Exception:
                pass
        state["last_normal_run"] = now_str
        save_state(state)

    data = {}
    tfs = [("daily", "1day", 200), ("h4", "4h", 200), ("h1", "1h", 250),
           ("m15", "15min", 200), ("m5", "5min", 200)]
    for n, i, s in tfs:
        data[n] = fetch(i, s)
        time.sleep(6)

    if any(v is None for v in data.values()):
        print("Fetch failed")
        return

    daily, h4, h1 = data["daily"], data["h4"], data["h1"]
    m15, m5 = data["m15"], data["m5"]
    cur = m5["close"].iloc[-1]

    # FAST LIVE PRICE
    live = fetch_live_price()
    if live:
        cur = live

    # POSITION CHECKS
    state, pos_msg = check_position(state, cur, now_str)
    if pos_msg:
        send_telegram(pos_msg)
    state, ctr_msg = check_counter(state, cur)
    if ctr_msg:
        send_telegram(ctr_msg)

    # SESSION CHANGE
    old_session = state.get("last_session", "")
    session_changed = is_session_transition(old_session, session)
    if session_changed or not state.get("session_open"):
        state["session_open"] = cur
        state["session_open_time"] = now_str
    state["last_session"] = session
    save_state(state)
    if session_changed:
        send_telegram("🔔 SESSION CHANGE: " + old_session + " -> " + session)

    # 35 INDICATORS
    bull, bear = [], []
    d_hi, d_lo = daily["high"].max(), daily["low"].min()
    d_rng = d_hi - d_lo
    d_mid = (d_hi + d_lo) / 2
    lvl25 = d_lo + d_rng * 0.25
    lvl618 = d_lo + d_rng * 0.618
    lvl786 = d_lo + d_rng * 0.786
    lvl75 = d_lo + d_rng * 0.75
    if cur > d_mid: bull.append("Above Daily 50%")
    else: bear.append("Below Daily 50%")
    if cur < lvl25: bull.append("Deep Discount")
    if cur > lvl75: bear.append("Deep Premium")
    if lvl618 <= cur <= lvl786: bear.append("At Fib 0.618-0.786")

    # DAILY / WEEKLY OPEN
    d_open = get_daily_open(daily)
    w_open = get_weekly_open(daily)
    if d_open:
        if cur > d_open: bull.append("Above Daily Open")
        else: bear.append("Below Daily Open")
    if w_open:
        if cur > w_open: bull.append("Above Weekly Open")
        else: bear.append("Below Weekly Open")

    adr = (daily.tail(30)["high"] - daily.tail(30)["low"]).mean()
    atr_h1 = atr(h1)
    if h4.iloc[-1]["close"] > h4["high"].iloc[-12:-1].max(): bull.append("4H BOS UP")
    if h4.iloc[-1]["close"] < h4["low"].iloc[-12:-1].min(): bear.append("4H BOS DN")
    if h1.iloc[-1]["close"] > h1["high"].iloc[-15:-1].max(): bull.append("1H MSS UP")
    if h1.iloc[-1]["close"] < h1["low"].iloc[-15:-1].min(): bear.append("1H MSS DN")
    if m15.iloc[-1]["close"] > m15["high"].iloc[-10:-1].max(): bull.append("15M MSS UP")
    if m15.iloc[-1]["close"] < m15["low"].iloc[-10:-1].min(): bear.append("15M MSS DN")
    ch1 = check_choch(h1)
    if ch1 == "BULL": bull.append("1H CHoCH Bull")
    if ch1 == "BEAR": bear.append("1H CHoCH Bear")
    ch4 = check_choch(h4)
    if ch4 == "BULL": bull.append("4H CHoCH Bull")
    if ch4 == "BEAR": bear.append("4H CHoCH Bear")
    disp = check_displacement(h1, atr_h1)
    if disp == "BULL": bull.append("Bull Displacement")
    if disp == "BEAR": bear.append("Bear Displacement")
    c1_m5, c2_m5 = m5.iloc[-1], m5.iloc[-2]
    body_m5 = abs(c1_m5["close"] - c1_m5["open"])
    if c1_m5["close"] > c1_m5["open"] and body_m5 > adr * 0.05: bull.append("5M Bull Candle")
    if c1_m5["close"] < c1_m5["open"] and body_m5 > adr * 0.05: bear.append("5M Bear Candle")
    if c2_m5["close"] < c2_m5["open"] and c1_m5["close"] > c1_m5["open"] and c1_m5["close"] > c2_m5["open"]: bull.append("5M Bull Engulf")
    if c2_m5["close"] > c2_m5["open"] and c1_m5["close"] < c1_m5["open"] and c1_m5["close"] < c2_m5["open"]: bear.append("5M Bear Engulf")
    fvgs = find_fvg(m15)[-15:]
    if any(f["t"] == "B" and abs(cur - f["ce"]) < adr * 0.3 for f in fvgs): bull.append("Bull FVG")
    if any(f["t"] == "S" and abs(cur - f["ce"]) < adr * 0.3 for f in fvgs): bear.append("Bear FVG")
    b_ob, s_ob = find_ob(h1)
    if b_ob and b_ob["bot"] - 5 <= cur <= b_ob["top"] + 5: bull.append("At Bull OB")
    if s_ob and s_ob["bot"] - 5 <= cur <= s_ob["top"] + 5: bear.append("At Bear OB")
    H1, L1 = swings(h1)
    bsl = sorted(H1, reverse=True)[:5]
    ssl = sorted(L1)[:5]
    nB = next((p for p in bsl if p > cur), None)
    nS = next((p for p in ssl if p < cur), None)
    if nB and nB - cur < adr * 0.3: bear.append("Near BSL")
    if nS and cur - nS < adr * 0.3: bull.append("Near SSL")
    if check_equal_levels(L1): bull.append("Equal Lows")
    if check_equal_levels(H1): bear.append("Equal Highs")
    if len(H1) > 1 and cur > H1[-2] and cur < H1[-1]: bear.append("Above Inducement")
    if len(L1) > 1 and cur < L1[-2] and cur > L1[-1]: bull.append("Below Inducement")
    closes = h1["close"].tolist()
    e50, e200 = ema(closes, 50), ema(closes, 200)
    if cur > e50 and e50 > e200: bull.append("EMA50>200 UP")
    if cur < e50 and e50 < e200: bear.append("EMA50<200 DN")
    if cur > e200: bull.append("Above EMA200")
    else: bear.append("Below EMA200")
    r = rsi(closes)
    if r < 30: bull.append("RSI Oversold")
    if r > 70: bear.append("RSI Overbought")
    if 50 < r < 70: bull.append("RSI Bullish")
    if 30 < r < 50: bear.append("RSI Bearish")
    m_now = ema(closes[-50:], 12) - ema(closes[-50:], 26)
    m_prev = ema(closes[-51:-1], 12) - ema(closes[-51:-1], 26)
    if m_now > 0 and m_prev <= 0: bull.append("MACD Cross UP")
    if m_now < 0 and m_prev >= 0: bear.append("MACD Cross DN")
    if m_now > 0: bull.append("MACD Positive")
    else: bear.append("MACD Negative")
    ma20 = sma(closes, 20)
    std20 = (sum([(x - ma20) ** 2 for x in closes[-20:]]) / 20) ** 0.5
    if cur <= ma20 - 2 * std20: bull.append("Below BB Lower")
    if cur >= ma20 + 2 * std20: bear.append("Above BB Upper")
    vn = vd = 0
    for i in range(max(0, len(h1) - 50), len(h1)):
        tp = (h1["high"].iloc[i] + h1["low"].iloc[i] + h1["close"].iloc[i]) / 3
        vn += tp
        vd += 1
    vwap = vn / vd if vd else cur
    if cur > vwap: bull.append("Above VWAP")
    else: bear.append("Below VWAP")
    pd_ = daily.iloc[-2]
    P = (pd_["high"] + pd_["low"] + pd_["close"]) / 3
    if cur > P: bull.append("Above Pivot")
    else: bear.append("Below Pivot")
    pdh, pdl = daily["high"].iloc[-2], daily["low"].iloc[-2]
    if abs(cur - pdh) < adr * 0.25: bear.append("Near PDH")
    if abs(cur - pdl) < adr * 0.25: bull.append("Near PDL")
    wk_h = daily["high"].tail(7).max()
    wk_l = daily["low"].tail(7).min()
    if abs(cur - wk_h) < adr * 0.3: bear.append("Near Weekly High")
    if abs(cur - wk_l) < adr * 0.3: bull.append("Near Weekly Low")
    rn = round(cur / 50) * 50
    if abs(cur - rn) < adr * 0.15:
        if cur > rn: bear.append("Above Round")
        else: bull.append("Below Round")
    dow = now_utc.weekday()
    if dow == 0 and len(daily) > 1:
        gap = abs(daily["open"].iloc[-1] - daily["close"].iloc[-2])
        if gap > adr * 0.3:
            if daily["open"].iloc[-1] > daily["close"].iloc[-2]: bull.append("Monday Gap UP")
            else: bear.append("Monday Gap DOWN")
    today_d = m5["dt"].iloc[-1].date()
    for label, h1_, h2_ in [("Asian", 0, 7), ("London", 7, 12), ("NY", 12, 21)]:
        seg = m5[(m5["dt"].dt.date == today_d) & (m5["dt"].dt.hour >= h1_) & (m5["dt"].dt.hour < h2_)]
        if len(seg):
            if cur > seg["high"].max(): bull.append("Above " + label + " High")
            if cur < seg["low"].min(): bear.append("Below " + label + " Low")
    c3, c2 = h1.iloc[-1], h1.iloc[-2]
    body = abs(c3["close"] - c3["open"])
    uw = c3["high"] - max(c3["close"], c3["open"])
    dw = min(c3["close"], c3["open"]) - c3["low"]
    if dw > 2 * body and uw < body: bull.append("1H Bull Pin")
    if uw > 2 * body and dw < body: bear.append("1H Bear Pin")
    if c2["close"] < c2["open"] and c3["close"] > c3["open"] and c3["close"] > c2["open"]: bull.append("1H Bull Engulf")
    if c2["close"] > c2["open"] and c3["close"] < c3["open"] and c3["close"] < c2["open"]: bear.append("1H Bear Engulf")

    # MOMENTUM + PA
    mom_dir, mom_speed = check_momentum(m5)
    if mom_dir == "FAST_BULL": bull.append("Fast Bull")
    if mom_dir == "FAST_BEAR": bear.append("Fast Bear")
    if mom_dir == "MED_BULL": bull.append("Med Bull")
    if mom_dir == "MED_BEAR": bear.append("Med Bear")
    pa_signals = check_price_action(m5)
    for s in pa_signals:
        if "Bull" in s: bull.append(s)
        elif "Bear" in s: bear.append(s)

    # ADX + BB SQUEEZE
    adx_val = check_adx(h1)
    if adx_val > 25:
        if ch1 == "BULL": bull.append("ADX Strong UP")
        if ch1 == "BEAR": bear.append("ADX Strong DN")
    if bollinger_squeeze(m15):
        bull.append("BB Squeeze")
        bear.append("BB Squeeze")

    # JUDAS SWING
    judas = detect_judas_swing(m5, session)
    if judas == "JUDAS_BULL": bull.append("Judas Bull Reversal")
    if judas == "JUDAS_BEAR": bear.append("Judas Bear Reversal")

    liq = session_liquidity_map(h1, m15, cur)

    # EXHAUSTION
    exhaust_type, exhaust_score, exhaust_info = detect_session_exhaustion(m5, m15, h1, session, cur)
    if exhaust_type and exhaust_score >= 4:
        last_alerted = state.get("exhaust_alerted", "")
        alert_key = session + "_" + exhaust_type
        if last_alerted != alert_key:
            state["exhaust_alerted"] = alert_key
            save_state(state)
            alert = "📊 SESSION LEVELS\n\n"
            alert += "Session: " + session + "\n"
            alert += "Range: " + str(exhaust_info["range_used"]) + "%\n"
            alert += "High: " + str(exhaust_info["sess_high"]) + "\n"
            alert += "Mid: " + str(exhaust_info["mid"]) + "\n"
            alert += "Low: " + str(exhaust_info["sess_low"]) + "\n\n"
            if exhaust_type == "BEAR_EXHAUST":
                alert += "RULE:\n🟢 Above " + str(exhaust_info["mid"]) + " = BUY\n🔴 Below " + str(exhaust_info["sess_low"]) + " = SELL"
            else:
                alert += "RULE:\n🟢 Above " + str(exhaust_info["sess_high"]) + " = BUY\n🔴 Below " + str(exhaust_info["mid"]) + " = SELL"
            send_telegram(alert)

    # HEDGE
    existing = state.get("position")
    counter = state.get("counter")
    if existing and not counter and session_changed:
        ctr_side, ctr_score = detect_counter_signal(existing["side"], h1, m15, m5, cur, session)
        if ctr_side:
            if ctr_side == "LONG":
                ctr_sl, ctr_tp = cur - 10, cur + 15
            else:
                ctr_sl, ctr_tp = cur + 10, cur - 15
            state["counter"] = {
                "side": ctr_side, "entry": cur, "sl": ctr_sl, "tp": ctr_tp,
                "opened_at": now_str, "reason": old_session + " -> " + session,
            }
            pos = state["position"]
            if pos["side"] == "SHORT":
                pos["tp1"] += 10; pos["tp2"] += 10; pos["tp3"] += 10
            else:
                pos["tp1"] -= 10; pos["tp2"] -= 10; pos["tp3"] -= 10
            state["position"] = pos
            save_state(state)
            msg = "⚡ EXTRA " + ("BUY" if ctr_side == "LONG" else "SELL")
            msg += "\nScore: " + str(ctr_score) + "/8"
            msg += "\nEntry: " + str(round(cur, 2))
            msg += "\nSL: " + str(round(ctr_sl, 2))
            msg += "\nTarget: " + str(round(ctr_tp, 2))
            msg += "\nReason: " + old_session + " -> " + session
            msg += "\nMain " + existing["side"] + " running"
            send_telegram(msg)
            return

    # GRACE PERIOD
    if is_session_grace_period(state, session):
        print("Grace period")
        return

    # ===== NEUTRAL MODE =====
    bS, sS = len(bull), len(bear)
    conf = max(bS, sS)
    if conf < 6:
        if bS == sS:
            key = now_utc.strftime("%Y-%m-%d") + "_" + session
            if state.get("neutral_alerted", "") != key:
                state["neutral_alerted"] = key
                save_state(state)
                t = "⚪ NEUTRAL - Wait\n\n"
                t += "Bull: " + str(bS) + " | Bear: " + str(sS)
                t += "\n\n" + str(round(cur, 2)) + " (current)"
                if liq["nearest_bsl"]:
                    t += "\n↑ " + str(round(liq["nearest_bsl"], 2)) + " = BUY"
                if liq["nearest_ssl"]:
                    t += "\n↓ " + str(round(liq["nearest_ssl"], 2)) + " = SELL"
                t += "\n\n" + format_ist_time(now_utc)
                send_telegram(t)
        return

    action = "LONG" if bS > sS else "SHORT"

    # CONTRADICTION FILTER
    if check_contradiction(state, action):
        print("Contradiction - skip")
        return

    # LATE SIGNAL SKIP
    if check_late_signal(state, cur, state.get("session_open")):
        print("Late signal - skip")
        return

    # CONFLUENCE STABILITY
    if not check_confluence_stability(state, conf):
        print("Confluence not stable - skip")
        save_state(state)
        return

    # MAX POSITIONS
    if check_max_positions(state):
        print("Max positions")
        return

    # EXISTING POSITION
    if existing:
        if existing["side"] == action:
            last_hold = state.get("last_hold_msg", "")
            send_hold = True
            if last_hold:
                try:
                    lh = datetime.strptime(last_hold, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                    if (now_utc - lh).total_seconds() / 60 < 60:
                        send_hold = False
                except Exception:
                    pass
            if send_hold:
                state["last_hold_msg"] = now_str
                save_state(state)
                ht = "⏸️ HOLD - " + ("BUY" if existing["side"] == "LONG" else "SELL")
                ht += "\n\nEntry: " + str(round(existing["entry"], 2))
                ht += "\nCurrent: " + str(round(cur, 2))
                ht += "\nSL: " + str(round(existing["sl"], 2))
                ht += "\nTarget 1: " + str(round(existing["tp1"], 2))
                ht += "\n\n" + format_ist_time(now_utc)
                send_telegram(ht)
            return
        else:
            if abs(bS - sS) >= 3:
                state["position"] = None
                send_telegram("🔄 FLIP — " + existing["side"] + " closed, opening " + action)
            else:
                return

    # NEW SIGNAL
    entry = cur
    sl, tp1, tp2, tp3 = atr_sl_tp(h1, action, cur)

    # ENTRY DRIFT
    drift_note = ""
    d = check_entry_drift(state, cur)
    if d:
        drift_note = "\n⚠️ " + d

    state["position"] = {
        "side": action, "entry": entry, "sl": round(sl, 2),
        "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2),
        "tp_hits": [], "warn_hits": [],
        "opened_at": now_str,
    }
    state["last_signal_price"] = cur
    state["last_signal_dir"] = action
    state["today_trades"] = state.get("today_trades", 0) + 1
    state["last_hold_msg"] = now_str
    save_state(state)

    # SIGNAL MESSAGE
    if action == "LONG":
        text = "🟢 BUY GOLD"
    else:
        text = "🔴 SELL GOLD"

    text += "\n\nEntry: " + str(round(entry, 2))
    text += "\nStop Loss: " + str(round(sl, 2))
    text += "\n\nTarget 1: " + str(round(tp1, 2))
    text += "\nTarget 2: " + str(round(tp2, 2))
    text += "\nTarget 3: " + str(round(tp3, 2))
    text += "\n\nDate: " + format_ist_date(now_utc)
    text += "\nTime: " + format_ist_time(now_utc)
    text += "\nSession: " + session

    if liq["nearest_bsl"]:
        text += "\n\nLiquidity Above: " + str(round(liq["nearest_bsl"], 2))
    if liq["nearest_ssl"]:
        text += "\nLiquidity Below: " + str(round(liq["nearest_ssl"], 2))

    text += "\n\nBull: " + str(bS) + " | Bear: " + str(sS)
    text += drift_note

    if pre:
        text += "\n\n⚠️ NEWS: " + pre + "\nClose trades now"
    if news_days:
        text += "\n\n📅 " + ", ".join(news_days)

    send_telegram(text)
    print("Sent: " + action + " Conf " + str(conf))


if __name__ == "__main__":
    run()
