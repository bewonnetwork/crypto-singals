"""
FREE Crypto Signal Bot  —  সম্পূর্ণ ফ্রি, শুধু সিগনাল (কোনো ট্রেড করে না, টাকা নেয় না)
==========================================================================================

কী করে:
  1. ৪টা ফ্রি এক্সচেঞ্জ API থেকে দাম আনে (Binance → OKX → KuCoin → Kraken)
     একটা বন্ধ থাকলে পরেরটা থেকে নেয়। কোনো API key লাগে না।
  2. EMA 9/21 ক্রস + RSI + ভলিউম দেখে BUY / SELL সিগনাল বানায়
  3. ATR দিয়ে Stop Loss, TP1, TP2 হিসাব করে
  4. Telegram চ্যানেলে পাঠায়
  5. প্রতিটা সিগনাল পরে TP হিট করল নাকি SL হিট করল — নিজেই চেক করে জানায়
     (তাই আপনি সৎভাবে Win rate দেখাতে পারবেন)
  6. প্রতিদিন সকাল ৮টায় (বাংলাদেশ সময়) মার্কেট সারাংশ + Fear & Greed পাঠায়

কীভাবে চালাবেন:
  python signal_bot.py --test     # Telegram ঠিক আছে কিনা পরীক্ষা (একটা টেস্ট মেসেজ যাবে)
  python signal_bot.py --once     # একবার চেক করে বন্ধ হবে (GitHub Actions এটা চালায়)
  python signal_bot.py --digest   # এখনই দৈনিক সারাংশ পাঠাও
  python signal_bot.py --loop     # নিজের কম্পিউটারে একটানা চালাতে চাইলে

Telegram token না দিলে মেসেজ পাঠাবে না, শুধু স্ক্রিনে দেখাবে (নিরাপদ টেস্ট)।
"""

import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

def _load_settings_file():
    """নিজের কম্পিউটারে চালালে settings.txt থেকে Token আর Chat ID পড়ে নেয়"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.txt")
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if v and "এখানে" not in v and not os.getenv(k):
                        os.environ[k] = v
    except FileNotFoundError:
        pass


_load_settings_file()

# ============================ সেটিংস (এখানে বদলাতে পারেন) ============================
TELEGRAM_BOT_TOKEN = os.getenv("TG_TOKEN", "")      # GitHub Secrets থেকে আসবে
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID", "")      # যেমন @my_free_signals
# নিউজ আলাদা চ্যানেলে পাঠাতে চাইলে GitHub Secret-এ TG_NEWS_CHAT_ID দিন; না দিলে একই চ্যানেলে যাবে
TELEGRAM_NEWS_CHAT_ID = os.getenv("TG_NEWS_CHAT_ID", "") or TELEGRAM_CHAT_ID
NEWS_TO_TELEGRAM = True     # False করলে নিউজ Telegram-এ যাবে না (শুধু ওয়েবসাইটে থাকবে)
NEWS_PER_RUN = 2            # প্রতি ১৫ মিনিটে সর্বোচ্চ কয়টা নতুন খবর Telegram-এ যাবে
SITE_URL = "https://bewonnetwork.github.io/crypto-singals/"

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
         "LTC", "UNI", "AAVE", "NEAR", "SUI", "POL", "ONDO", "PEPE"]      # ১৮টা কয়েনের ওয়াচলিস্ট
INTERVAL = "1h"             # 15m / 1h / 4h
TREND_INTERVAL = "4h"       # বড় ট্রেন্ড দেখার টাইমফ্রেম
MIN_CONFIDENCE = 60         # এর কম Confidence হলে সিগনাল পাঠাবে না

# ---- হঠাৎ ওঠানামার অ্যালার্ট ----
VOL_ALERTS = True           # False করলে বন্ধ
VOL_PCT = 3.0               # কত % নড়লে অ্যালার্ট
VOL_WINDOW_MIN = 30         # কত মিনিটের মধ্যে (৫ মিনিটের ক্যান্ডেল দিয়ে মাপা)
VOL_COOLDOWN_MIN = 60       # একই কয়েনে একই দিকে আবার অ্যালার্টের আগে বিরতি

# ---- Forex ও Gold ----
FOREX_ENABLED = True        # False করলে Forex সিগনাল বন্ধ
# নিজের নাম: (Yahoo Finance-এর চিহ্ন, Twelve Data-র চিহ্ন, দেখানোর নাম)
FX_PAIRS = {
    "EURUSD": ("EURUSD=X", "EUR/USD", "EUR/USD"),
    "GBPUSD": ("GBPUSD=X", "GBP/USD", "GBP/USD"),
    "USDJPY": ("JPY=X", "USD/JPY", "USD/JPY"),
    "XAUUSD": ("GC=F", "XAU/USD", "Gold (XAU/USD)"),
}
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY", "")   # ঐচ্ছিক ব্যাকআপ (GitHub Secret-এ বসাবেন)
EMA_FAST, EMA_SLOW = 9, 21
RSI_LEN, ATR_LEN = 14, 14
SL_ATR, TP1_ATR, TP2_ATR = 1.5, 1.5, 3.0   # Stop Loss / Target দূরত্ব (ATR এর গুণ)
MAX_TRADE_CANDLES = 48      # এতগুলো ক্যান্ডেলে TP/SL না হলে "Expired"
# ---- মার্কেট ইনসাইট + শেখার টিপস ----
INSIGHTS_ENABLED = True     # False করলে বন্ধ
INSIGHT_HOUR_UTC = 8        # 8 UTC = দুপুর ২টা বাংলাদেশ: দিনে একবার ইনসাইট + আজকের টিপ Telegram-এ
INSIGHT_REFRESH_MIN = 60    # ওয়েবসাইটের ইনসাইট ডেটা কত মিনিট পর পর নতুন হবে
LISTINGS_TO_TELEGRAM = True  # নতুন লিস্টিং আর ফ্রি ইনকামের সুযোগ Telegram-এ যাবে
LISTINGS_PER_RUN = 3        # একবারে সর্বোচ্চ কয়টা
WALL_RANGE_PCT = 5.0        # এখনকার দামের কত % এর মধ্যে বড় অর্ডার খোঁজা হবে
DIGEST_HOUR_UTC = 2         # 2 UTC = সকাল ৮টা বাংলাদেশ
LOOP_EVERY_SEC = 300        # --loop মোডে কত সেকেন্ড পর পর
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
# ======================================================================================

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "free-signal-bot/1.0"
COLS = ["time", "open", "high", "low", "close", "volume"]


# ----------------------------- ১. দাম আনা (৪টা ফ্রি এক্সচেঞ্জ) -----------------------------
def _frame(rows, time_unit):
    df = pd.DataFrame(rows, columns=COLS)
    df[COLS[1:]] = df[COLS[1:]].astype(float)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit=time_unit, utc=True)
    return df.sort_values("time").reset_index(drop=True)


def from_binance(coin, interval=None, limit=300):
    # api.binance.com আমেরিকার সার্ভার (GitHub) থেকে ব্লক, তাই data-api ব্যবহার করছি
    r = HTTP.get("https://data-api.binance.vision/api/v3/klines",
                 params={"symbol": f"{coin}USDT", "interval": interval or INTERVAL, "limit": limit}, timeout=15)
    r.raise_for_status()
    df = _frame([row[:6] for row in r.json()], "ms")
    return df.iloc[:-1]                     # শেষ ক্যান্ডেল এখনো চলছে → বাদ


def from_okx(coin, interval=None, limit=300):
    bar = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H"}[interval or INTERVAL]
    r = HTTP.get("https://www.okx.com/api/v5/market/candles",
                 params={"instId": f"{coin}-USDT", "bar": bar, "limit": min(limit, 300)}, timeout=15)
    r.raise_for_status()
    data = r.json().get("data") or []
    closed = [row[:6] for row in data if row[8] == "1"]   # "1" = ক্যান্ডেল বন্ধ হয়েছে
    if not closed:
        raise ValueError("OKX: no data")
    return _frame(closed, "ms")


def from_kucoin(coin, interval=None, limit=300):
    typ = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour"}[interval or INTERVAL]
    r = HTTP.get("https://api.kucoin.com/api/v1/market/candles",
                 params={"type": typ, "symbol": f"{coin}-USDT"}, timeout=15)
    r.raise_for_status()
    data = r.json().get("data") or []
    if not data:
        raise ValueError("KuCoin: no data")
    # KuCoin ক্রম: time, open, close, high, low, volume
    rows = [[d[0], d[1], d[3], d[4], d[2], d[5]] for d in data[:limit]]
    return _frame(rows, "s").iloc[:-1]


def from_kraken(coin, interval=None, limit=300):
    base = {"BTC": "XBT", "DOGE": "XDG"}.get(coin, coin)
    minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}[interval or INTERVAL]
    r = HTTP.get("https://api.kraken.com/0/public/OHLC",
                 params={"pair": f"{base}USD", "interval": minutes}, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise ValueError(f"Kraken: {j['error']}")
    key = next(k for k in j["result"] if k != "last")
    rows = [[d[0], d[1], d[2], d[3], d[4], d[6]] for d in j["result"][key][-limit:]]
    return _frame(rows, "s").iloc[:-1]


SOURCES = [("Binance", from_binance), ("OKX", from_okx),
           ("KuCoin", from_kucoin), ("Kraken", from_kraken)]


def get_candles(coin, interval=None):
    """একটা এক্সচেঞ্জ কাজ না করলে পরেরটা চেষ্টা করে"""
    errors = []
    for name, fn in SOURCES:
        try:
            df = fn(coin, interval)
            if len(df) >= 60:
                return df, name
            errors.append(f"{name}: only {len(df)} candles")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:80]}")
    raise RuntimeError(" | ".join(errors))


def get_recent(coin, interval="5m", limit=12):
    """অ্যালার্টের জন্য অল্প কয়েকটা ছোট ক্যান্ডেল"""
    for name, fn in SOURCES:
        try:
            df = fn(coin, interval, limit)
            if len(df) >= 7:
                return df.tail(limit).reset_index(drop=True)
        except Exception:
            pass
    return None


def grade(conf):
    """Confidence % থেকে সহজ গ্রেড"""
    if conf is None:
        return "—"
    return "A+" if conf >= 85 else "A" if conf >= 78 else "B" if conf >= 70 else "C" if conf >= 60 else "D"


def check_volatility(state):
    """৩০ মিনিটে ৩% বা বেশি নড়লে অ্যালার্ট মেসেজ বানায়"""
    if not VOL_ALERTS:
        return []
    msgs, now = [], datetime.now(timezone.utc)
    last = state.setdefault("vol_last", {})
    n = max(1, VOL_WINDOW_MIN // 5)
    for coin in COINS:
        df = get_recent(coin, "5m", n + 6)
        if df is None or len(df) <= n:
            continue
        ref, cur = float(df["close"].iloc[-1 - n]), float(df["close"].iloc[-1])
        ch = (cur / ref - 1) * 100
        if abs(ch) < VOL_PCT:
            continue
        side = "up" if ch > 0 else "down"
        prev = last.get(coin)
        if prev and prev.get("side") == side and \
                (now - datetime.fromisoformat(prev["time"])).total_seconds() < VOL_COOLDOWN_MIN * 60:
            continue
        last[coin] = {"side": side, "time": now.isoformat(timespec="seconds")}
        state.setdefault("alerts", []).insert(0, {"coin": coin, "ch": round(ch, 2), "price": cur, "ref": ref,
                                                  "mins": VOL_WINDOW_MIN, "time": now.isoformat(timespec="seconds")})
        del state["alerts"][50:]
        arrow = "🚀 ▲" if ch > 0 else "🔻 ▼"
        msgs.append(f"⚡ <b>হঠাৎ ওঠানামা — {coin}/USDT</b>\n\n"
                    f"{arrow} <b>{ch:+.2f}%</b> গত {VOL_WINDOW_MIN} মিনিটে\n"
                    f"দাম: <code>{fmt(cur)}</code>  (আগে <code>{fmt(ref)}</code>)\n\n"
                    f"ℹ️ এটা ট্রেড সিগনাল নয়, শুধু সতর্কতা। দাম দ্রুত নড়ছে, সাবধানে সিদ্ধান্ত নিন।\n"
                    f"📊 <a href=\"{SITE_URL}#/coin/{coin}\">লাইভ চার্ট দেখুন</a>")
        time.sleep(0.2)
    return msgs


def get_fear_greed():
    """ফ্রি Fear & Greed Index (alternative.me) — ০ = খুব ভয়, ১০০ = খুব লোভ"""
    try:
        d = HTTP.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except Exception:
        return None, None


# ----------------------------- ১খ. Forex ও Gold-এর দাম -----------------------------
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _resample_4h(df):
    d = df.set_index("time").resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return d.reset_index().iloc[:-1]


def fx_from_yahoo(sym, interval=None):
    ysym = FX_PAIRS[sym][0]
    r = HTTP.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}",
                 params={"interval": "60m", "range": "60d"}, headers=BROWSER_UA, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"time": res["timestamp"], "open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"], "volume": q.get("volume") or 0}).dropna(subset=["close"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.floor("h")
    df = df.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    df[COLS[1:]] = df[COLS[1:]].astype(float)
    df = df.iloc[:-1]                                  # চলমান ক্যান্ডেল বাদ
    return _resample_4h(df) if (interval or INTERVAL) == "4h" else df


def fx_from_twelve(sym, interval=None):
    if not TWELVE_KEY:
        raise ValueError("Twelve Data key নেই")
    r = HTTP.get("https://api.twelvedata.com/time_series",
                 params={"symbol": FX_PAIRS[sym][1], "interval": {"1h": "1h", "4h": "4h"}[interval or INTERVAL],
                         "outputsize": 300, "apikey": TWELVE_KEY}, timeout=15)
    j = r.json()
    if j.get("status") != "ok":
        raise ValueError(j.get("message", "Twelve Data error")[:80])
    rows = [[v["datetime"], v["open"], v["high"], v["low"], v["close"], v.get("volume", 0)] for v in j["values"]]
    df = pd.DataFrame(rows, columns=COLS)
    df[COLS[1:]] = df[COLS[1:]].astype(float)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True).iloc[:-1]


def get_fx_candles(sym, interval=None):
    """Yahoo → Twelve Data → (শুধু Gold-এর জন্য) PAXG টোকেন"""
    errors = []
    for name, fn in (("Yahoo", fx_from_yahoo), ("TwelveData", fx_from_twelve)):
        try:
            df = fn(sym, interval)
            if len(df) >= 60:
                return df, name
            errors.append(f"{name}: only {len(df)}")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:60]}")
    if sym == "XAUUSD":
        df, src = get_candles("PAXG", interval)
        return df, f"PAXG via {src}"
    raise RuntimeError(" | ".join(errors))


def fx_market_open(now):
    """Forex: রবিবার ২২:০০ UTC থেকে শুক্রবার ২১:০০ UTC পর্যন্ত খোলা"""
    wd, h = now.weekday(), now.hour      # সোম=0 … রবি=6
    if wd == 5:
        return False
    if wd == 4 and h >= 21:
        return False
    if wd == 6 and h < 22:
        return False
    return True


def pip_size(sym):
    return 0.01 if "JPY" in sym else (0.1 if sym.startswith("XAU") else 0.0001)


# ----------------------------- ২. ইন্ডিকেটর ও সিগনাল -----------------------------
def add_indicators(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_LEN, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / ATR_LEN, adjust=False).mean()
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    macd = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
    df["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    up, dn = df["high"].diff(), -df["low"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    atr_w = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w
    mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, float("nan"))
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean().fillna(0)
    return df


def trend_of(df):
    """+1 = ঊর্ধ্বমুখী, -1 = নিম্নমুখী, 0 = পরিষ্কার না"""
    c = df.iloc[-1]
    if c.ema50 > c.ema200 and c.close > c.ema50:
        return 1
    if c.ema50 < c.ema200 and c.close < c.ema50:
        return -1
    return 0


def score_signal(df, side, htf_trend, btc_trend, is_btc, fx=False):
    """বড় প্রোভাইডাররা যেসব ফিল্টার ব্যবহার করে সেগুলো মিলিয়ে Confidence % বানায়"""
    c, prev = df.iloc[-1], df.iloc[-2]
    d = 1 if side == "BUY" else -1
    score, why = (25, ["EMA 9/21 ক্রস + RSI ঠিক সীমায়"]) if fx else (20, ["EMA 9/21 ক্রস + RSI ঠিক সীমায় + ভলিউম বেশি"])
    if htf_trend == d:
        score += 20; why.append(f"{TREND_INTERVAL} বড় ট্রেন্ড একই দিকে")
    elif htf_trend == -d:
        score -= 10; why.append(f"⚠ {TREND_INTERVAL} বড় ট্রেন্ড উল্টো দিকে")
    if (c.close - c.ema200) * d > 0:
        score += 10; why.append("দাম EMA 200-এর " + ("ওপরে" if d > 0 else "নিচে"))
    if c.macd_hist * d > 0 and (c.macd_hist - prev.macd_hist) * d > 0:
        score += 10; why.append("MACD মোমেন্টাম বাড়ছে")
    if c.adx >= 25:
        score += 15; why.append(f"ট্রেন্ড শক্তিশালী (ADX {c.adx:.0f})")
    elif c.adx >= 20:
        score += 8; why.append(f"ট্রেন্ড মাঝারি (ADX {c.adx:.0f})")
    else:
        score -= 5; why.append(f"⚠ ট্রেন্ড দুর্বল (ADX {c.adx:.0f})")
    vr = c.volume / c.vol_avg if c.vol_avg else 1
    if fx:
        pass                                    # Forex-এ নির্ভরযোগ্য ভলিউম নেই
    elif vr >= 1.5:
        score += 10; why.append(f"ভলিউম গড়ের {vr:.1f} গুণ")
    else:
        score += 3
    if (50 <= c.rsi <= 65) if d > 0 else (35 <= c.rsi <= 50):
        score += 5; why.append(f"RSI {c.rsi:.0f} ভালো জায়গায়")
    if not is_btc and btc_trend:
        if btc_trend == d:
            score += 10; why.append("BTC-ও একই দিকে যাচ্ছে")
        else:
            score -= 10; why.append("⚠ BTC উল্টো দিকে")
    return max(5, min(95, score)), why


def check_signal(df, need_volume=True):
    """শেষ বন্ধ হওয়া ক্যান্ডেলে নতুন সিগনাল আছে কিনা"""
    prev, cur = df.iloc[-2], df.iloc[-1]
    crossed_up = prev.ema_fast <= prev.ema_slow and cur.ema_fast > cur.ema_slow
    crossed_down = prev.ema_fast >= prev.ema_slow and cur.ema_fast < cur.ema_slow
    good_volume = (cur.volume > cur.vol_avg) if need_volume else True

    if crossed_up and 45 < cur.rsi < 70 and good_volume:
        side = "BUY"
    elif crossed_down and 30 < cur.rsi < 55 and good_volume:
        side = "SELL"
    else:
        return None

    p, atr, sign = cur.close, cur.atr, (1 if side == "BUY" else -1)
    return {"side": side, "entry": p, "rsi": round(float(cur.rsi), 1),
            "sl": p - sign * SL_ATR * atr,
            "tp1": p + sign * TP1_ATR * atr,
            "tp2": p + sign * TP2_ATR * atr,
            "candle": cur.time.isoformat()}


# ----------------------------- ৩. সিগনালের ফলাফল ট্র্যাক করা -----------------------------
def _close(t, result, when, state):
    """বন্ধ হওয়া সিগনাল ইতিহাসে রাখে (ওয়েবসাইটে দেখানোর জন্য)"""
    state.setdefault("history", []).insert(0, {
        "coin": t["coin"], "side": t["side"], "entry": t["entry"],
        "sl": t.get("sl0", t["sl"]), "tp1": t["tp1"], "tp2": t["tp2"],
        "opened": t.get("opened", ""), "closed": when, "result": result,
        "conf": t.get("conf"), "why": t.get("why", []),
        "market": t.get("market", "crypto"), "name": t.get("name", t["coin"]),
        "exit": t.get("exit") or {"SL": t.get("sl0", t["sl"]), "TP2": t["tp2"], "TP1": t["tp1"]}.get(result),
        "mdd": round(t["mdd"], 2) if t.get("mdd") is not None else None, "h24": t.get("h24"),
        **{k: t[k] for k in ("src", "chk", "note", "from") if t.get(k) not in (None, "")}})
    del state["history"][300:]


def update_open_trades(coin, df, state):
    """খোলা সিগনালগুলো TP1 / TP2 / SL হিট করল কিনা দেখে; মেসেজ লিস্ট ফেরত দেয়"""
    msgs, still_open = [], []
    for t in state["open"]:
        if t["coin"] != coin:
            still_open.append(t)
            continue
        after = df[df["time"] > pd.Timestamp(t["checked_until"])]
        buy = t["side"] == "BUY"
        closed = False
        for _, c in after.iterrows():
            t["age"] += 1
            adverse = ((t["entry"] - c.low) if buy else (c.high - t["entry"])) / t["entry"] * 100
            t["mdd"] = max(t.get("mdd") or 0.0, float(adverse))          # দাম সিগনালের বিপক্ষে সর্বোচ্চ কতটা গেছে
            if t["age"] == 24 and t.get("h24") is None:                    # ২৪ ঘণ্টা পরে বন্ধ করলে কী হতো
                t["h24"] = round(float((c.close / t["entry"] - 1) * 100 * (1 if buy else -1)), 2)
            hit_sl = c.low <= t["sl"] if buy else c.high >= t["sl"]
            hit_tp1 = c.high >= t["tp1"] if buy else c.low <= t["tp1"]
            hit_tp2 = c.high >= t["tp2"] if buy else c.low <= t["tp2"]
            if hit_sl:   # একই ক্যান্ডেলে দুটোই হলে সাবধানে SL ধরছি
                if t["tp1_hit"]:
                    msgs.append(f"🟡 {label(coin)} {t['side']}: TP1 এর পর দাম Entry তে ফিরে এসেছে — লাভ লক (Breakeven)")
                    _close(t, "TP1", c.time.isoformat(), state)
                else:
                    state["stats"]["loss"] += 1
                    msgs.append(f"❌ {label(coin)} {t['side']}: Stop Loss হিট ({fmt(t['sl'], coin)})")
                    _close(t, "SL", c.time.isoformat(), state)
                closed = True
                break
            if hit_tp2:
                if not t["tp1_hit"]:
                    state["stats"]["win"] += 1
                state["stats"]["tp2"] += 1
                msgs.append(f"🎯🎯 {label(coin)} {t['side']}: TP2 হিট! ({fmt(t['tp2'], coin)})")
                _close(t, "TP2", c.time.isoformat(), state)
                closed = True
                break
            if hit_tp1 and not t["tp1_hit"]:
                t["tp1_hit"] = True
                state["stats"]["win"] += 1
                t["sl"] = t["entry"]          # TP1 এর পর SL কে Entry তে সরানো হলো
                msgs.append(f"✅ {label(coin)} {t['side']}: TP1 হিট! ({fmt(t['tp1'], coin)}) — এখন SL = Entry")
            if t["age"] >= MAX_TRADE_CANDLES:
                if not t["tp1_hit"]:
                    state["stats"]["expired"] += 1
                msgs.append(f"⌛ {label(coin)} {t['side']}: সময় শেষ, সিগনাল বন্ধ")
                t["exit"] = float(c.close)
                _close(t, "TP1" if t["tp1_hit"] else "EXPIRED", c.time.isoformat(), state)
                closed = True
                break
        if len(after):
            t["checked_until"] = after["time"].iloc[-1].isoformat()
        if not closed:
            still_open.append(t)
    state["open"] = still_open
    return msgs


# ----------------------------- ৪. মেসেজ ও Telegram -----------------------------
def label(sym):
    return FX_PAIRS[sym][2] if sym in FX_PAIRS else sym


def fmt(x, sym=None):
    if sym in FX_PAIRS:
        return f"{x:,.{2 if sym.startswith('XAU') else 3 if 'JPY' in sym else 5}f}"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    if x < 0.01:
        return f"{x:.8f}"
    return f"{x:.6f}"


def signal_message(coin, s, source):
    icon = "🟢" if s["side"] == "BUY" else "🔴"
    fx = coin in FX_PAIRS
    if fx:
        ps = pip_size(coin)
        pips = lambda v: f"  ({abs(v - s['entry']) / ps:,.0f} pips)"
        head = f"💱 <b>FOREX</b> · {icon} <b>{s['side']} — {label(coin)}</b>  ({INTERVAL})\n\n"
        link = f"{SITE_URL}#/forex"
    else:
        pips = lambda v: ""
        head = f"{icon} <b>{s['side']} — {coin}/USDT</b>  ({INTERVAL})\n\n"
        link = f"{SITE_URL}#/coin/{coin}"
    return (head +
            f"Entry: <code>{fmt(s['entry'], coin)}</code>\n"
            f"TP1: <code>{fmt(s['tp1'], coin)}</code>{pips(s['tp1'])}\n"
            f"TP2: <code>{fmt(s['tp2'], coin)}</code>{pips(s['tp2'])}\n"
            f"Stop Loss: <code>{fmt(s['sl'], coin)}</code>{pips(s['sl'])}\n"
            f"RSI: {s['rsi']}  |  Data: {source}\n\n"
            + (s["deep"] + "\n" if s.get("deep") else f"🎯 <b>Confidence: {s['conf']}% · Grade {grade(s['conf'])}</b>\n")
            + "".join(f"• {w}\n" for w in s["why"]) + "\n"
            f"📊 <a href=\"{link}\">চার্ট ও সব সিগনাল দেখুন</a>\n\n"
            f"⚠️ Free signal, not financial advice. Use Stop Loss. DYOR.")


def win_rate_text(st):
    done = st["win"] + st["loss"]
    if not done:
        return "এখনো কোনো সিগনাল শেষ হয়নি"
    return (f"Win {st['win']} | Loss {st['loss']} | Expired {st['expired']} | "
            f"Win rate {st['win'] * 100 / done:.0f}%")


def send_telegram(text, chat_id=None, preview=False):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("---- (Telegram সেট করা নেই, তাই শুধু দেখাচ্ছি) ----\n" + text + "\n")
        return True
    try:
        r = HTTP.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": "false" if preview else "true"}, timeout=15)
        if r.ok:
            return True
        print("Telegram error:", r.text)
    except Exception as e:
        print("Telegram error:", e)
    return False


# ----------------------------- ৫. state (মনে রাখা) -----------------------------
def load_state():
    base = {"last_signal": {}, "open": [], "last_digest": "",
            "stats": {"win": 0, "loss": 0, "tp2": 0, "expired": 0}}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            base.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return base


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    export_site(state)


SITE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "signals.json")


def export_site(state):
    """ওয়েবসাইটের জন্য docs/data/signals.json বানায় (কিছু বদলালে তবেই)"""
    keep = ("coin", "side", "entry", "sl", "tp1", "tp2", "tp1_hit", "opened", "rsi", "conf", "why", "market", "name", "src", "chk", "note", "from")
    payload = {
        "interval": INTERVAL, "coins": COINS, "stats": state["stats"], "min_conf": MIN_CONFIDENCE,
        "open": [{k: t.get(k) for k in keep} for t in state["open"]],
        "history": state.get("history", [])[:200],
        "alerts": state.get("alerts", [])[:20],
        "watch": state.get("watch_notes", [])[:10],
        "fear_greed": state.get("fear_greed"),
        "forex": {"enabled": FOREX_ENABLED, "pairs": [{"sym": k, "name": v[2]} for k, v in FX_PAIRS.items()],
                  "quotes": state.get("fx_quotes", {})},
    }
    try:
        with open(SITE_FILE, encoding="utf-8") as f:
            old = json.load(f)
        old.pop("updated", None)
        if old == json.loads(json.dumps(payload)):
            return
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    payload["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(SITE_FILE), exist_ok=True)
    with open(SITE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


# ----------------------------- ৬. দৈনিক সারাংশ -----------------------------
def daily_digest(frames, state):
    fg, fg_txt = get_fear_greed()
    if fg is not None:
        state["fear_greed"] = {"value": fg, "label": fg_txt}
    lines = [f"📊 <b>Daily Market Digest</b> — {datetime.now(timezone.utc):%d %b %Y}\n"]
    for coin, df in frames.items():
        if len(df) > 24:
            now, before = df["close"].iloc[-1], df["close"].iloc[-25]
            ch = (now - before) * 100 / before
            lines.append(f"{'🟢' if ch >= 0 else '🔴'} {coin}: {fmt(now)} ({ch:+.2f}%)")
    fxq = state.get("fx_quotes", {})
    if fxq:
        lines.append("\n💱 <b>Forex ও Gold</b>")
        for k, q in fxq.items():
            lines.append(f"{'🟢' if q['ch'] >= 0 else '🔴'} {label(k)}: {fmt(q['price'], k)} ({q['ch']:+.2f}%)")
    if fg is not None:
        lines.append(f"\n😨→🤑 Fear & Greed: <b>{fg}</b> ({fg_txt})  <i>source: alternative.me</i>")
    lines.append(f"\n📈 Bot record: {win_rate_text(state['stats'])}")
    lines.append(f"🔓 Open signals: {len(state['open'])}")
    lines.append(f"\n🌐 <a href=\"{SITE_URL}\">ওয়েবসাইট</a> · <a href=\"{SITE_URL}#/signals\">সব ফলাফল</a> · <a href=\"{SITE_URL}#/news\">নিউজ</a>")
    lines.append("\n⚠️ Not financial advice.")
    return "\n".join(lines)


# ----------------------------- ৭. ক্রিপ্টো নিউজ (ওয়েবসাইটের জন্য) -----------------------------
NEWS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
]
NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "news.json")
NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}


def _clean_text(raw, limit=240):
    txt = re.sub(r"<[^>]+>", " ", html.unescape(raw or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt if len(txt) <= limit else txt[:limit].rsplit(" ", 1)[0] + "…"


def _image(item):
    for tag in ("media:content", "media:thumbnail"):
        for el in item.findall(tag, NS):
            u = el.get("url", "")
            if u.startswith("https://") and el.get("medium", "image") == "image":
                return u
    enc = item.find("enclosure")
    if enc is not None and enc.get("url", "").startswith("https://") and "image" in enc.get("type", "image"):
        return enc.get("url")
    body = (item.findtext("content:encoded", "", NS) or "") + (item.findtext("description") or "")
    m = re.search(r'<img[^>]+src="(https://[^"]+)"', body)
    return m.group(1) if m else ""


def fetch_news():
    """৫টা বড় ক্রিপ্টো নিউজ সাইটের ফ্রি RSS থেকে খবর আনে"""
    items, seen = [], set()
    for source, url in NEWS_FEEDS:
        try:
            r = HTTP.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; SignalBot/1.0)"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for it in root.iter("item"):
                title = _clean_text(it.findtext("title"), 200)
                link = (it.findtext("link") or "").strip()
                if not title or not link.startswith("https://"):
                    continue
                key = re.sub(r"\W+", "", title.lower())[:80]
                if link in seen or key in seen:
                    continue
                seen.update([link, key])
                try:
                    pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat()
                except Exception:
                    pub = ""
                items.append({"id": hashlib.md5(link.encode()).hexdigest()[:10],
                              "title": title, "link": link, "source": source, "published": pub,
                              "summary": _clean_text(it.findtext("description")), "image": _image(it)})
        except Exception as e:
            print(f"news {source}: {str(e)[:80]}")
    items.sort(key=lambda x: x["published"], reverse=True)
    return items[:80]


def news_message(n):
    e = html.escape
    return (f"📰 <b>{e(n['title'])}</b>\n\n"
            + (f"{e(n['summary'])}\n\n" if n.get("summary") else "")
            + f"🔗 {SITE_URL}#/news/{n.get('id') or ''}\n\n<i>Source: {e(n['source'])}</i>  #CryptoNews")


def post_news_to_telegram(items, state):
    """নতুন খবর Telegram-এ পাঠায়। প্রথমবার শুধু মনে রাখে, পাঠায় না (যাতে ৮০টা খবর একসাথে না যায়)"""
    posted = state.setdefault("news_posted", [])
    links = [x["link"] for x in items]
    if not state.get("news_seeded"):
        state["news_seeded"] = True
        state["news_posted"] = links[:500]
        return
    seen = set(posted)
    new = [x for x in items if x["link"] not in seen]
    for n in reversed(new[:NEWS_PER_RUN]):          # পুরোনোটা আগে, নতুনটা পরে
        send_telegram(news_message(n), chat_id=TELEGRAM_NEWS_CHAT_ID, preview=True)
        time.sleep(1)
    state["news_posted"] = ([x["link"] for x in new] + posted)[:500]


def update_news(state=None):
    items = fetch_news()
    if not items:
        return
    if state is not None and NEWS_TO_TELEGRAM:
        post_news_to_telegram(items, state)
    try:
        with open(NEWS_FILE, encoding="utf-8") as f:
            old = json.load(f)
        if [x["link"] for x in old.get("items", [])] == [x["link"] for x in items]:
            return
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    os.makedirs(os.path.dirname(NEWS_FILE), exist_ok=True)
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "sources": [s for s, _ in NEWS_FEEDS], "items": items}, f, ensure_ascii=False, indent=1)
    print(f"news: {len(items)} items")


# ----------------------------- ৭.৫ মার্কেট ইনসাইট -----------------------------
INSIGHTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "insights.json")
LESSONS = [
    "কেনার আগে FDV দেখুন। Market cap-এর চেয়ে FDV অনেক বেশি হলে সামনে প্রচুর নতুন টোকেন বাজারে আসবে।",
    "সামনে বড় টোকেন আনলক আছে কিনা দেখে নিন। সরবরাহ বাড়লে দামে চাপ পড়তে পারে।",
    "Stop Loss ছাড়া কোনো ট্রেড নয়। আগে ঠিক করুন কোথায় ভুল প্রমাণ হবেন, তারপর Entry।",
    "এক ট্রেডে মোট টাকার ১–২%-এর বেশি ঝুঁকি নেবেন না।",
    "লাভের লক্ষ্য ক্ষতির অন্তত ১.৫–২ গুণ না হলে ট্রেডটা বাদ দিন।",
    "৪ ঘণ্টা আর দৈনিক চার্টের ট্রেন্ডের উল্টো দিকে ট্রেড করবেন না।",
    "BTC Dominance বাড়লে অল্টকয়েন সাধারণত দুর্বল থাকে; কমলে টাকা অল্টকয়েনে যায়।",
    "যে দামে আগে ২–৩ বার দাম ফিরে গেছে, সেটাই শক্ত সাপোর্ট বা রেজিস্ট্যান্স।",
    "Order book-এর বড় অর্ডার নকলও হতে পারে (spoofing)। শুধু ওটা দেখে সিদ্ধান্ত নয়।",
    "কেউ seed phrase বা private key চাইলে সেটা শতভাগ প্রতারণা — এয়ারড্রপ হোক বা সাপোর্ট।",
    "'আগে টাকা পাঠান, তারপর এয়ারড্রপ পাবেন' — এটা সবসময় প্রতারণা।",
    "এয়ারড্রপের জন্য আলাদা খালি ওয়ালেট ব্যবহার করুন, মূল টাকার ওয়ালেট নয়।",
    "দৈনিক ভলিউম কম এমন কয়েনে ঢোকা সহজ, বের হওয়া কঠিন।",
    "নতুনদের জন্য লিভারেজ নয়। বেশি লিভারেজে ছোট নড়াচড়াতেই টাকা শেষ।",
    "হারের পর রাগে বা FOMO-তে ট্রেড করবেন না। একটু বিরতি নিন।",
    "প্রতিটা ট্রেড লিখে রাখুন। খাতা না রাখলে নিজের ভুল ধরা যায় না।",
    "কন্ট্রাক্ট ঠিকানা সবসময় প্রজেক্টের অফিসিয়াল সাইট থেকে মিলিয়ে নিন। নকল টোকেন অনেক।",
    "টোকেনের বেশিরভাগ টিম বা বিনিয়োগকারীদের হাতে থাকলে ঝুঁকি বেশি।",
    "বড় খবর বা বড় আনলকের ঠিক আগে নতুন ট্রেডে সাবধান।",
    "আসল টাকার আগে ডেমোতে প্র্যাকটিস করুন। ওয়েবসাইটের ডেমো পেজ ফ্রি।",
    "Confidence বা গ্রেড মানে জেতার সম্ভাবনা নয় — শুধু কতগুলো শর্ত মিলেছে।",
]
TOPICS = {"airdrop": r"airdrop", "unlock": r"\bunlock|vesting", "listing": r"\blist(s|ed|ing)?\b|launchpool|launchpad"}


def get_dominance():
    """CoinGecko থেকে BTC/ETH dominance আর মোট মার্কেট ক্যাপ"""
    r = HTTP.get("https://api.coingecko.com/api/v3/global", timeout=15)
    r.raise_for_status()
    d = r.json()["data"]
    return {"btc": round(d["market_cap_percentage"]["btc"], 2), "eth": round(d["market_cap_percentage"].get("eth", 0), 2),
            "mcap": round(d["total_market_cap"]["usd"]), "mcap_ch": round(d.get("market_cap_change_percentage_24h_usd", 0), 2)}


def get_walls(coin):
    """Order book থেকে দামের কাছাকাছি সবচেয়ে বড় কেনা/বেচার দেয়াল (সাপোর্ট/রেজিস্ট্যান্স)"""
    r = HTTP.get("https://data-api.binance.vision/api/v3/depth", params={"symbol": f"{coin}USDT", "limit": 1000}, timeout=15)
    r.raise_for_status()
    j = r.json()
    bids = [(float(p), float(q)) for p, q in j["bids"]]
    asks = [(float(p), float(q)) for p, q in j["asks"]]
    if not bids or not asks:
        return None
    mid = (bids[0][0] + asks[0][0]) / 2
    step = mid * 0.0025                     # 0.25% চওড়া ঘর

    def biggest(rows, lo, hi):
        buckets = {}
        for p, q in rows:
            if lo <= p <= hi:
                k = round(p / step)
                buckets[k] = buckets.get(k, 0) + p * q
        if not buckets:
            return None
        k = max(buckets, key=buckets.get)
        return {"price": k * step, "usd": round(buckets[k])}

    sup = biggest(bids, mid * (1 - WALL_RANGE_PCT / 100), mid)
    res = biggest(asks, mid, mid * (1 + WALL_RANGE_PCT / 100))
    if not sup or not res:
        return None
    tb = sum(p * q for p, q in bids if p >= mid * 0.98)
    ta = sum(p * q for p, q in asks if p <= mid * 1.02)
    return {"coin": coin, "price": mid, "support": sup, "resistance": res,
            "buy_pct": round(tb * 100 / (tb + ta)) if tb + ta else 50}


def topic_news():
    """নিউজ থেকে এয়ারড্রপ / আনলক / লিস্টিং-এর খবর আলাদা করে"""
    try:
        with open(NEWS_FILE, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    out = {}
    for name, pat in TOPICS.items():
        out[name] = [{k: n.get(k) for k in ("title", "link", "source", "published")}
                     for n in items if re.search(pat, n.get("title", "") + " " + (n.get("summary") or ""), re.I)][:8]
    return out


FEED_STATUS = {}   # কোন উৎস থেকে কয়টা ঘোষণা এলো (-1 = আনা যায়নি)
AIRDROP_FEEDS = [
    ("Airdrops.io", "https://airdrops.io/feed/"),
    ("AirdropAlert", "https://airdropalert.com/feed/"),
    ("Bitcoin.com", "https://news.bitcoin.com/feed/"),
    ("CryptoPotato", "https://cryptopotato.com/feed/"),
    ("BeInCrypto", "https://beincrypto.com/feed/"),
    ("U.Today", "https://u.today/rss"),
    ("NewsBTC", "https://www.newsbtc.com/feed/"),
    ("AMBCrypto", "https://ambcrypto.com/feed/"),
    ("CryptoNews", "https://cryptonews.com/news/feed/"),
    ("Blockworks", "https://blockworks.co/feed"),
    ("DailyHodl", "https://dailyhodl.com/feed/"),
    ("Bitcoinist", "https://bitcoinist.com/feed/"),
    ("CoinJournal", "https://coinjournal.net/feed/"),
]
UNLOCK_DAYS = 45            # সামনের কত দিনের টোকেন আনলক দেখাবে
UNLOCK_MIN_PCT = 0.05       # মোট সরবরাহের এত শতাংশের কম আনলক বাদ
UNLOCK_SLUGS = ["arbitrum", "optimism", "aptos", "sui", "celestia", "starknet", "sei", "dydx", "apecoin", "worldcoin",
                "pyth-network", "jito", "ethena", "ondo-finance", "immutable", "the-sandbox", "axie-infinity", "blur",
                "layerzero", "zksync", "eigenlayer", "wormhole", "jupiter", "altlayer", "manta", "pendle", "aevo",
                "avalanche", "hyperliquid", "aster", "ether.fi", "kamino", "berachain", "movement", "linea", "polyhedra"]


def fetch_unlocks():
    """DefiLlama-র খোলা ডেটা থেকে সামনের টোকেন আনলকের তালিকা (কোন কয়েন, কবে, কত)"""
    r = HTTP.get("https://defillama-datasets.llama.fi/emissionsBreakdown", timeout=20)
    r.raise_for_status()
    brk = r.json()

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    top = sorted(brk, key=lambda k: num(brk[k].get("emission30d")), reverse=True)[:30]
    slugs = list(dict.fromkeys([x for x in UNLOCK_SLUGS if x in brk] + top))[:55]
    now, out = time.time(), []

    def one(slug):
        try:
            d = HTTP.get(f"https://defillama-datasets.llama.fi/emissions/{slug}", timeout=20).json()
            meta = d.get("metadata") or {}
            total = num(meta.get("total"))
            rows = []
            for ev in meta.get("events") or []:
                ts = num(ev.get("timestamp"))
                tokens = sum(num(x) for x in (ev.get("noOfTokens") or []))
                if not (now < ts < now + UNLOCK_DAYS * 86400) or tokens <= 0 or ev.get("unlockType") != "cliff":
                    continue
                pct = tokens / total * 100 if total else 0
                if total and pct < UNLOCK_MIN_PCT:
                    continue
                rows.append({"name": d.get("name") or brk[slug].get("name") or slug, "slug": slug,
                             "t": datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds"),
                             "tokens": round(tokens), "pct": round(pct, 3), "cat": str(ev.get("category") or "")[:30]})
            return rows
        except Exception as e:
            print(f"unlock {slug}: {str(e)[:60]}")
            return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        for rows in ex.map(one, slugs):
            out += rows
    merged = {}
    for x in out:                       # একই কয়েনের একই দিনের একাধিক ভাগ এক করে
        k = (x["slug"], x["t"][:10])
        if k in merged:
            merged[k]["tokens"] += x["tokens"]
            merged[k]["pct"] = round(merged[k]["pct"] + x["pct"], 3)
        else:
            merged[k] = dict(x)
    FEED_STATUS["DefiLlama unlocks"] = len(merged)
    return sorted(merged.values(), key=lambda x: x["t"])[:60]


def fetch_newcoins():
    """CoinMarketCap-এ সদ্য যোগ হওয়া কয়েন"""
    r = HTTP.get("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/spotlight",
                 params={"dataType": 8, "limit": 30}, timeout=15,
                 headers={"User-Agent": "Mozilla/5.0 (compatible; SignalBot/1.0)"})
    r.raise_for_status()
    out = []
    for c in ((r.json().get("data") or {}).get("recentlyAddedList") or []):
        pc = c.get("priceChange") or {}
        chain = ((c.get("platforms") or [{}])[0] or {}).get("name", "")
        if not c.get("slug") or not c.get("symbol"):
            continue
        out.append({"name": str(c.get("name", ""))[:40], "sym": str(c["symbol"])[:12], "added": c.get("addedDate", ""),
                    "price": pc.get("price"), "ch24": pc.get("priceChange24h"), "vol": pc.get("volume24h"),
                    "mcap": c.get("marketCap"), "chain": str(chain)[:20],
                    "url": "https://coinmarketcap.com/currencies/" + str(c["slug"]) + "/"})
    FEED_STATUS["CoinMarketCap new"] = len(out)
    return out[:30]


def airdrop_news():
    """এয়ারড্রপের খবরের বাড়তি উৎস (RSS)। কোনোটা না চললে বাদ পড়ে, বাকিগুলো চলে।"""
    out, seen = [], set()
    for source, url in AIRDROP_FEEDS:
        try:
            r = HTTP.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (compatible; SignalBot/1.0)"})
            r.raise_for_status()
            n = 0
            for it in ET.fromstring(r.content).iter("item"):
                title = _clean_text(it.findtext("title"), 200)
                link = (it.findtext("link") or "").strip()
                text = title + " " + (_clean_text(it.findtext("description")) or "")
                always = source == "Airdrops.io"
                if not title or not link.startswith("https://") or link in seen:
                    continue
                if not always and not re.search(r"airdrop|retrodrop|points (farming|program)|claim (is )?live", text, re.I):
                    continue
                try:
                    pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat()
                except Exception:
                    pub = ""
                seen.add(link)
                out.append({"title": title, "link": link, "source": source, "published": pub})
                n += 1
            FEED_STATUS[source] = n
        except Exception as e:
            FEED_STATUS[source] = -1
            print(f"airdrop {source}: {str(e)[:80]}")
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:25]


EARN_RE = r"airdrop|gempool|launchpool|learn (and|&) earn|earn |reward|giveaway|prize pool|campaign|bonus|share \$?[\d,]+|candy|free "
SKIP_RE = r"futures|perpetual|delist|margin|leverag|maintenance|convert|trading bot|options|suspend"
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                           "september", "october", "november", "december"])}


def _ticker(title):
    m = re.search(r"\(([A-Z0-9]{2,10})\)", title) or re.search(r"\b([A-Z0-9]{2,10})/(?:USDT|USD|USDC)\b", title)
    return m.group(1) if m else ""


def _trade_time(desc):
    """'Trading: 13:00 on September 28, 2026 (UTC)' → ISO সময়"""
    m = re.search(r"(\d{1,2}):(\d{2}) on (\w+) (\d{1,2}), (\d{4})", desc or "")
    if not m or m.group(3).lower() not in MONTHS:
        return ""
    return datetime(int(m.group(5)), MONTHS[m.group(3).lower()], int(m.group(4)), int(m.group(1)), int(m.group(2)),
                    tzinfo=timezone.utc).isoformat()


def fetch_exchange_feed():
    """এক্সচেঞ্জের অফিসিয়াল ঘোষণা থেকে নতুন লিস্টিং আর ফ্রি ইনকামের সুযোগ"""
    listings, earn = [], []
    iso = lambda ms: datetime.fromtimestamp(int(ms) / 1000, timezone.utc).isoformat(timespec="seconds")
    try:
        r = HTTP.get("https://www.okx.com/api/v5/support/announcements",
                     params={"annType": "announcements-new-listings"}, timeout=15)
        r.raise_for_status()
        for blk in r.json().get("data", []):
            for a in blk.get("details", [blk]) if isinstance(blk, dict) else []:
                title, url = a.get("title", ""), a.get("url", "")
                if not title or not url.startswith("https://") or re.search(SKIP_RE, title, re.I):
                    continue
                listings.append({"ex": "OKX", "title": title, "url": url, "token": _ticker(title),
                                 "announced": iso(a.get("pTime", 0)), "trade": ""})
    except Exception as e:
        print("okx feed:", str(e)[:80])
    for ann_type, size in (("new-listings", 30), ("latest-announcements", 50)):
        try:
            r = HTTP.get("https://api.kucoin.com/api/v3/announcements",
                         params={"annType": ann_type, "lang": "en_US", "pageSize": size}, timeout=15)
            r.raise_for_status()
            for a in (r.json().get("data") or {}).get("items", []):
                title, url = a.get("annTitle", ""), a.get("annUrl", "")
                if not title or not url.startswith("https://"):
                    continue
                item = {"ex": "KuCoin", "title": title, "url": url, "token": _ticker(title),
                        "announced": iso(a.get("cTime", 0)), "trade": _trade_time(a.get("annDesc"))}
                types = a.get("annType") or []
                if re.search(EARN_RE, title, re.I) and not re.search(r"delist|maintenance|suspend", title, re.I):
                    earn.append(item)
                elif "new-listings" in types and not re.search(SKIP_RE, title, re.I):
                    listings.append(item)
        except Exception as e:
            print("kucoin feed:", str(e)[:80])

    FEED_STATUS["OKX"] = sum(1 for x in listings if x["ex"] == "OKX")
    FEED_STATUS["KuCoin"] = sum(1 for x in listings + earn if x["ex"] == "KuCoin")

    def add(ex, title, url, ms, kind="auto"):
        """একটা ঘোষণা ঠিক তালিকায় বসায় (লিস্টিং নাকি ফ্রি ইনকাম)"""
        if not title or not str(url).startswith("https://"):
            return 0
        item = {"ex": ex, "title": title, "url": url, "token": _ticker(title), "announced": iso(ms or 0), "trade": ""}
        if re.search(EARN_RE, title, re.I) and not re.search(r"delist|maintenance|suspend", title, re.I):
            earn.append(item)
        elif kind == "listing" and not re.search(SKIP_RE, title, re.I):
            listings.append(item)
        else:
            return 0
        return 1

    def source(ex, fn):
        try:
            FEED_STATUS[ex] = fn()
        except Exception as e:
            FEED_STATUS[ex] = -1
            print(f"{ex} feed:", str(e)[:80])

    LIST_RE = r"\b(will list|lists?|listing|listed|new listing|initial listing|open trading|available for trading|launch(es|ed)? (spot|trading))\b"
    isoms = lambda iso_s: int(datetime.fromisoformat(iso_s.replace("Z", "+00:00")).timestamp() * 1000) if iso_s else 0

    def bitget():
        r = HTTP.get("https://api.bitget.com/api/v2/public/annoucements",
                     params={"annType": "coin_listings", "language": "en_US"}, timeout=15)
        r.raise_for_status()
        return sum(add("Bitget", a.get("annTitle", ""), a.get("annUrl", ""), a.get("cTime"), "listing")
                   for a in (r.json().get("data") or []) if a.get("annSubType") != "futures")

    def htx():
        r = HTTP.get("https://www.htx.com/-/x/support/public/getList/v2", timeout=15,
                     params={"language": "en-us", "page": 1, "limit": 20, "oneLevelId": 360000031902, "twoLevelId": 360000039942})
        r.raise_for_status()
        n = 0
        for a in ((r.json().get("data") or {}).get("list") or []):
            title = a.get("title", "")
            if add("HTX", title, "https://www.htx.com/support/" + str(a.get("id", "")), a.get("showTime"), "listing"):
                n += 1
                if listings and listings[-1]["ex"] == "HTX":
                    pair = re.search(r"_([A-Z0-9]{2,10})/", str(a.get("dealPair") or ""))
                    listings[-1]["token"] = pair.group(1) if pair else ""
                m = re.search(r"at (\d{1,2}):(\d{2}) \(UTC\)\s+on (\w+) (\d{1,2}), (\d{4})", title)
                if m and m.group(3).lower() in MONTHS and listings and listings[-1]["ex"] == "HTX":
                    listings[-1]["trade"] = datetime(int(m.group(5)), MONTHS[m.group(3).lower()], int(m.group(4)),
                                                     int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc).isoformat()
        return n

    def kraken():
        r = HTTP.get("https://blog.kraken.com/category/product/asset-listings/feed", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; SignalBot/1.0)"})
        r.raise_for_status()
        n = 0
        for it in ET.fromstring(r.content).iter("item"):
            try:
                ms = int(parsedate_to_datetime(it.findtext("pubDate")).timestamp() * 1000)
            except Exception:
                ms = 0
            n += add("Kraken", _clean_text(it.findtext("title"), 200), (it.findtext("link") or "").strip(), ms, "listing")
        return n

    def zendesk(ex, host):
        def run():
            r = HTTP.get(f"https://{host}/api/v2/help_center/en-us/articles.json", timeout=15,
                         params={"per_page": 40, "sort_by": "created_at", "sort_order": "desc"})
            r.raise_for_status()
            n = 0
            for a in (r.json().get("articles") or []):
                title = a.get("name") or a.get("title") or ""
                if re.search(LIST_RE, title, re.I) or re.search(EARN_RE, title, re.I):
                    n += add(ex, title, a.get("html_url", ""), isoms(a.get("created_at", "")), "listing")
            return n
        return run

    def bitfinex():
        r = HTTP.get("https://api-pub.bitfinex.com/v2/posts/hist", params={"limit": 20, "type": 1}, timeout=15)
        r.raise_for_status()
        n = 0
        for a in r.json():
            if isinstance(a, list) and len(a) > 3 and isinstance(a[3], str) and re.search(LIST_RE, a[3], re.I):
                n += add("Bitfinex", a[3], "https://www.bitfinex.com/posts/" + str(a[0]), a[1] if isinstance(a[1], (int, float)) else 0, "listing")
        return n

    def binance():
        n = 0
        for cat, kind in ((48, "listing"), (93, "auto")):
            r = HTTP.get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                         params={"type": 1, "catalogId": cat, "pageNo": 1, "pageSize": 20}, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; SignalBot/1.0)"})
            r.raise_for_status()
            for c in ((r.json().get("data") or {}).get("catalogs") or []):
                for a in c.get("articles", []):
                    n += add("Binance", a.get("title", ""),
                             "https://www.binance.com/en/support/announcement/" + str(a.get("code", "")),
                             a.get("releaseDate"), kind)
        return n

    for ex, fn in (("Binance", binance), ("Bitget", bitget), ("HTX", htx), ("Kraken", kraken), ("Bitfinex", bitfinex),
                   ("BitMart", zendesk("BitMart", "bitmart.zendesk.com")), ("XT", zendesk("XT", "xtsupport.zendesk.com")),
                   ("DigiFinex", zendesk("DigiFinex", "digifinex.zendesk.com"))):
        source(ex, fn)

    def uniq(rows):
        seen, out = set(), []
        for x in sorted(rows, key=lambda x: x["announced"], reverse=True):
            if x["url"] not in seen:
                seen.add(x["url"])
                out.append(x)
        return out
    return uniq(listings)[:60], uniq(earn)[:40]


def feed_message(x, kind):
    e = html.escape
    if kind == "listing":
        head = f"🆕 <b>নতুন লিস্টিং — {e(x['ex'])}</b>" + (f"  <code>{e(x['token'])}</code>" if x["token"] else "")
        when = f"\n⏰ ট্রেডিং শুরু: {x['trade'][:16].replace('T', ' ')} UTC" if x.get("trade") else ""
        tail = "ℹ️ নতুন লিস্টিংয়ে দাম খুব দ্রুত ওঠানামা করে। এটা কেনার সুপারিশ নয়।"
    else:
        head, when = f"🎁 <b>ফ্রি ইনকামের সুযোগ — {e(x['ex'])}</b>", ""
        tail = "ℹ️ শর্ত আর যোগ্যতা অফিসিয়াল পেজে পড়ে নিন। কেউ আগে টাকা বা seed phrase চাইলে সেটা প্রতারণা।"
    return (f"{head}\n\n{e(x['title'])}{when}\n\n"
            f"🔗 <a href=\"{e(x['url'])}\">অফিসিয়াল ঘোষণা পড়ুন</a>\n"
            f"📚 <a href=\"{SITE_URL}#/learn\">সব লিস্টিং ও সুযোগ ওয়েবসাইটে</a>\n\n{tail}")


def post_feed(listings, earn, state):
    """নতুন আইটেম Telegram-এ পাঠায়। প্রথমবার শুধু মনে রাখে।"""
    posted = state.setdefault("feed_posted", [])
    allx = [(x, "listing") for x in listings] + [(x, "earn") for x in earn]
    if not state.get("feed_seeded"):
        state["feed_seeded"] = True
        state["feed_posted"] = [x["url"] for x, _ in allx][:400]
        return
    seen = set(posted)
    new = sorted([(x, k) for x, k in allx if x["url"] not in seen], key=lambda p: p[0]["announced"])
    if LISTINGS_TO_TELEGRAM:
        for x, k in new[-LISTINGS_PER_RUN:]:
            send_telegram(feed_message(x, k))
            time.sleep(1)
    state["feed_posted"] = ([x["url"] for x, _ in new] + posted)[:400]


def update_insights(state):
    if not INSIGHTS_ENABLED:
        return
    now = datetime.now(timezone.utc)
    last = state.get("insights_time")
    fresh = last and (now - datetime.fromisoformat(last)).total_seconds() < INSIGHT_REFRESH_MIN * 60
    today = now.strftime("%Y-%m-%d")
    due_post = now.hour >= INSIGHT_HOUR_UTC and state.get("last_insight") != today
    if fresh and not due_post:
        return
    ins = state.get("insights", {})
    try:
        dom = get_dominance()
        hist = state.setdefault("dom_hist", {})
        hist[today] = dom["btc"]
        for k in sorted(hist)[:-30]:
            hist.pop(k)
        prev = [hist[k] for k in sorted(hist) if k < today]
        dom["ch_1d"] = round(dom["btc"] - prev[-1], 2) if prev else None
        dom["ch_7d"] = round(dom["btc"] - prev[-7], 2) if len(prev) >= 7 else None
        dom["history"] = [{"d": k, "v": hist[k]} for k in sorted(hist)]
        ins["dominance"] = dom
    except Exception as e:
        print("dominance error:", str(e)[:80])
    walls = []
    for coin in COINS:
        try:
            w = get_walls(coin)
            if w:
                walls.append(w)
        except Exception as e:
            print(f"walls {coin}:", str(e)[:60])
        time.sleep(0.2)
    if walls:
        ins["walls"] = walls
    ins["topics"] = topic_news()
    try:
        extra = airdrop_news()
        if extra:
            have = {x.get("link") for x in ins["topics"].get("airdrop", [])}
            ins["topics"]["airdrop"] = (ins["topics"].get("airdrop", []) + [x for x in extra if x["link"] not in have])
            ins["topics"]["airdrop"].sort(key=lambda x: x.get("published") or "", reverse=True)
            ins["topics"]["airdrop"] = ins["topics"]["airdrop"][:25]
    except Exception as e:
        print("airdrop feeds:", str(e)[:80])
    try:
        listings, earn = fetch_exchange_feed()
        if listings or earn:
            ins["listings"], ins["earn"] = listings, earn
            post_feed(listings, earn, state)
    except Exception as e:
        print("feed error:", str(e)[:80])
    day = int(now.timestamp() // 86400)
    ins["tip"] = LESSONS[day % len(LESSONS)]
    hr = int(now.timestamp() // 21600)                    # আনলক আর নতুন কয়েন: ৬ ঘণ্টায় একবার
    if state.get("slow_hr") != hr:
        for key, fn in (("unlocks", fetch_unlocks), ("newcoins", fetch_newcoins)):
            try:
                rows = fn()
                if rows:
                    ins[key] = rows
            except Exception as e:
                FEED_STATUS[key] = -1
                print(f"{key} error:", str(e)[:80])
        state["slow_hr"] = hr
    ins["sources"] = dict(FEED_STATUS) if len(FEED_STATUS) > 6 else dict(state.get("src_seen", {}), **FEED_STATUS)
    state["src_seen"] = ins["sources"]
    ins["updated"] = now.isoformat(timespec="seconds")
    state["insights"] = ins
    state["insights_time"] = ins["updated"]
    os.makedirs(os.path.dirname(INSIGHTS_FILE), exist_ok=True)
    with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(ins, f, ensure_ascii=False, indent=1)
    if due_post and send_telegram(insight_message(ins)):
        state["last_insight"] = today


def insight_message(ins):
    e = html.escape
    lines = ["🧭 <b>আজকের মার্কেট ইনসাইট</b>\n"]
    d = ins.get("dominance")
    if d:
        ch = f" ({d['ch_1d']:+.2f} গতকাল থেকে)" if d.get("ch_1d") is not None else ""
        mood = "অল্টকয়েন দুর্বল থাকতে পারে" if d["btc"] >= 55 else "টাকা অল্টকয়েনে যাচ্ছে" if d["btc"] < 50 else "মাঝামাঝি অবস্থা"
        lines.append(f"👑 <b>BTC Dominance: {d['btc']}%</b>{ch}\n   ETH: {d['eth']}% · মোট মার্কেট: ${d['mcap'] / 1e12:.2f}T ({d['mcap_ch']:+.2f}%)\n   ➜ {mood}\n")
    walls = ins.get("walls") or []
    if walls:
        lines.append("🧱 <b>বড় অর্ডারের দেয়াল (Order book)</b>")
        for w in walls[:5]:
            lines.append(f"• {w['coin']}: সাপোর্ট <code>{fmt(w['support']['price'])}</code> (${w['support']['usd'] / 1e6:.1f}M) · "
                         f"রেজিস্ট্যান্স <code>{fmt(w['resistance']['price'])}</code> (${w['resistance']['usd'] / 1e6:.1f}M)")
        lines.append("")
    tp = ins.get("topics") or {}
    for key, label in (("airdrop", "🎁 এয়ারড্রপের খবর"), ("unlock", "🔓 টোকেন আনলকের খবর")):
        if tp.get(key):
            lines.append(f"<b>{label}</b>")
            for n in tp[key][:2]:
                lines.append(f"• <a href=\"{e(n['link'])}\">{e(n['title'][:90])}</a>")
            lines.append("")
    soon = [u for u in (ins.get("unlocks") or []) if u.get("pct", 0) >= 0.3][:4]
    if soon:
        lines.append("🔓 <b>সামনের বড় টোকেন আনলক</b>")
        for u in soon:
            lines.append(f"• {e(u['name'])}: {u['t'][:10]} · {u['tokens'] / 1e6:.1f}M টোকেন ({u['pct']:.2f}% সরবরাহ)")
        lines.append("")
    lines.append(f"🎓 <b>আজকের টিপ:</b> {ins.get('tip', '')}\n")
    lines.append(f"📚 <a href=\"{SITE_URL}#/learn\">লাইভ ইনসাইট ও পুরো গাইড ওয়েবসাইটে</a>")
    lines.append("\n⚠️ শুধু তথ্য, আর্থিক পরামর্শ নয়। বড় অর্ডার যেকোনো সময় সরে যেতে পারে।")
    return "\n".join(lines)


# ----------------------------- ৮. মূল কাজ -----------------------------
# ----------------------------- নিজের (Manual) সিগনাল: Telegram থেকে -----------------------------
# চ্যানেলের অ্যাডমিন বটকে প্রাইভেট মেসেজ দিলে সেটা সিগনাল হয়ে চ্যানেল + ওয়েবসাইটে যায়।
MANUAL_ENABLED = True
OWNER_ID = os.getenv("TG_OWNER_ID", "")     # ঐচ্ছিক: নির্দিষ্ট একজনের Telegram ID (না দিলে চ্যানেলের অ্যাডমিনরা)
MANUAL_MAX_OPEN = 8          # একসাথে সর্বোচ্চ কয়টা নিজের সিগনাল খোলা থাকবে
MANUAL_ENTRY_PCT = 2.0       # Entry এখনকার দাম থেকে এত % এর বেশি দূরে হলে নেবে না
_SIDES = {"buy": "BUY", "long": "BUY", "sell": "SELL", "short": "SELL"}
_LBL = {"entry": "entry", "price": "entry", "at": "entry", "zone": "entry", "cmp": "entry",
        "tp": "tp", "target": "tp", "targets": "tp", "take": "tp", "profit": "tp", "tgt": "tp",
        "sl": "sl", "stop": "sl", "stoploss": "sl", "loss": "sl"}
_STOP = set("BUY SELL LONG SHORT TP SL ENTRY PRICE AT ZONE CMP TARGET TARGETS TAKE PROFIT TGT STOP STOPLOSS LOSS "
            "SIGNAL S NOTE NOW MARKET USDT USD PERP SPOT FUTURES LEVERAGE CROSS ISOLATED X THE AND TO".split())
MANUAL_HELP = ("🧑‍💼 <b>নিজের সিগনাল দেওয়ার নিয়ম</b>\n\n"
               "১) সহজ (বট নিজে TP/SL হিসাব করবে):\n<code>/signal BTC BUY</code>\n\n"
               "২) নিজের দাম দিয়ে:\n<code>/signal BTC BUY entry 65000 tp 66000 67000 sl 64000</code>\n\n"
               "৩) সাথে নোট:\n<code>/signal ETH SELL tp 2400 2300 sl 2600 note সাপোর্ট ভেঙেছে</code>\n\n"
               "৪) পার্টনারের সিগনাল: তাদের পোস্টটা এই বটে <b>Forward</b> করুন (TP আর SL থাকতে হবে)।\n\n"
               "অন্য কমান্ড:\n<code>/list</code> — খোলা সিগনাল\n<code>/close BTC</code> — নিজে হাতে বন্ধ\n"
               "<code>/partner @channel</code> — পার্টনার চ্যানেল থেকে নিজে নিজে সিগনাল নেওয়া\n"
               "<code>/video https://youtu.be/XXXX শিরোনাম</code> — সাইটের ভিডিও সেকশনে ভিডিও যোগ\n<code>/video @channel</code> — পুরো YouTube চ্যানেল যোগ\n\n"
               f"কয়েন: {', '.join(COINS)} (অন্য কয়েনও চলবে, যেমন <code>/signal PEPE BUY</code>)\nForex: {', '.join(FX_PAIRS)}\n\n"
               "⏱ মেসেজ দেওয়ার পর সর্বোচ্চ ১৫–২০ মিনিটের মধ্যে চ্যানেল ও সাইটে যাবে।")


def parse_signal(text, first_is_coin=False):
    """যেকোনো সাধারণ ফরম্যাটের সিগনাল লেখা থেকে coin/side/entry/tp/sl বের করে"""
    note = ""
    m = re.search(r"\bnote\b[:\-\s]*(.+)", text, re.I | re.S)
    if m:
        note, text = _clean_text(m.group(1), 160), text[:m.start()]
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)              # 65,000 -> 65000
    text = re.sub(r"\b\d+\s*/\s*\d+\b|\b\d+\s*(m|min|h|hr|d|w)\b", " ", text, flags=re.I)   # 71/100, 1h, 15m বাদ
    any_coin = None                                              # তালিকার বাইরের কয়েন: BTC/USDT, #PEPE, $SUI
    m = re.search(r"\b([A-Za-z]{2,10})\s*[/\-_]?\s*USDT\b", text, re.I) or re.search(r"[#$]([A-Za-z]{2,10})\b", text)
    pair_coin = m.group(1).upper() if m and m.group(1).upper() not in _STOP else None
    text = re.sub(r"\b\d+(\.\d+)?\s*(x\b|%)", " ", text, flags=re.I)  # 10x, 2% বাদ
    toks = re.findall(r"[A-Za-z]+[1-4]?(?![\d.])|\d+(?:\.\d+)?", text)      # TP1, TP2 এক টুকরা
    side, coin, cur = None, None, "pos"
    nums = {"pos": [], "entry": [], "tp": [], "sl": []}
    for tk in toks:
        if tk[0].isdigit():
            v = float(tk)
            if v > 0:
                nums[cur].append(v)
            continue
        lw = tk.lower().rstrip("1234")
        tk = tk.rstrip("1234")
        if lw in _SIDES and not side:
            side = _SIDES[lw]
            continue
        if lw in _LBL:
            cur = _LBL[lw]
            continue
        up = tk.upper()
        if not coin and up not in _STOP:
            base = up if up in FX_PAIRS else re.sub(r"(USDT|USD|PERP)$", "", up) or up
            if up in FX_PAIRS or base in COINS:
                coin = up if up in FX_PAIRS else base
            elif first_is_coin and not any_coin and 2 <= len(base) <= 10:
                any_coin = base
            first_is_coin = False
    if cur == "pos" and len(nums["pos"]) == 4:                    # entry tp1 tp2 sl
        e, a, b, c = nums["pos"]
        nums = {"pos": [], "entry": [e], "tp": [a, b], "sl": [c]}
    elif nums["pos"] and not nums["entry"]:
        nums["entry"] = nums["pos"]
    en = nums["entry"][:2]
    if len(en) == 2 and abs(en[1] / en[0] - 1) > 0.05:           # দ্বিতীয়টা Entry রেঞ্জ নয়
        en = en[:1]
    entry = sum(en) / len(en) if en else None
    return {"coin": pair_coin or coin or any_coin, "side": side, "entry": entry, "tps": nums["tp"][:2],
            "sl": nums["sl"][0] if nums["sl"] else None, "note": note}


def manual_check(df, side, htf, btc_trend, is_btc, fx):
    """অ্যাডমিনের সিগনালকে ইঞ্জিন দিয়ে মিলিয়ে দেখে: কয়টা নিশ্চয়তা মিলছে"""
    c, d = df.iloc[-1], (1 if side == "BUY" else -1)
    rows = [(htf == d, f"{TREND_INTERVAL} বড় ট্রেন্ড " + ("একই দিকে" if htf == d else "একই দিকে নয়")),
            ((c.ema_fast - c.ema_slow) * d > 0, f"{INTERVAL} EMA 9/21 " + ("পক্ষে" if (c.ema_fast - c.ema_slow) * d > 0 else "বিপক্ষে")),
            (c.macd_hist * d > 0, "MACD মোমেন্টাম " + ("পক্ষে" if c.macd_hist * d > 0 else "বিপক্ষে")),
            (c.adx >= 20, f"ট্রেন্ডের শক্তি ADX {c.adx:.0f}"),
            ((c.rsi < 70) if d > 0 else (c.rsi > 30), f"RSI {c.rsi:.0f}")]
    if not is_btc and not fx and btc_trend:
        rows.append((btc_trend == d, "BTC " + ("একই দিকে" if btc_trend == d else "উল্টো দিকে")))
    ok = sum(1 for good, _ in rows if good)
    return ok, len(rows), [(("" if good else "⚠ ") + txt) for good, txt in rows]


def manual_message(coin, t):
    icon = "🟢" if t["side"] == "BUY" else "🔴"
    fx = coin in FX_PAIRS
    link = f"{SITE_URL}#/forex" if fx else f"{SITE_URL}#/coin/{coin}" if coin in COINS else f"{SITE_URL}#/signals"
    rr = abs(t["tp1"] - t["entry"]) / max(abs(t["entry"] - t["sl0"]), 1e-12)
    head = (f"🤝 <b>PARTNER SIGNAL</b> — সোর্স: {html.escape(t.get('from') or 'Partner')}" if t.get("src") == "partner"
            else "🧑‍💼 <b>ADMIN SIGNAL</b> (হাতে দেওয়া)")
    tail = ("এটা পার্টনার চ্যানেলের সিগনাল (অনুমতি নিয়ে শেয়ার করা)" if t.get("src") == "partner" else "এটা অ্যাডমিনের নিজের মতামত")
    return (f"{head}\n{icon} <b>{t['side']} — {label(coin) if fx else coin + '/USDT'}</b>\n\n"
            f"Entry: <code>{fmt(t['entry'], coin)}</code>\n"
            f"TP1: <code>{fmt(t['tp1'], coin)}</code>\n"
            f"TP2: <code>{fmt(t['tp2'], coin)}</code>\n"
            f"Stop Loss: <code>{fmt(t['sl0'], coin)}</code>\n"
            f"Risk : Reward (TP1) = 1 : {rr:.1f}\n\n"
            f"🔎 <b>ইঞ্জিন মিলিয়ে দেখেছে: {t['chk']} নিশ্চয়তা মিলেছে</b>\n"
            + "".join(f"• {w}\n" for w in t["why"])
            + (f"\n📝 {html.escape(t['note'])}\n" if t.get("note") else "")
            + f"\n📊 <a href=\"{link}\">চার্ট ও সব সিগনাল দেখুন</a>\n\n"
            f"⚠️ {tail}, লাভের নিশ্চয়তা নয়। Not financial advice. Use Stop Loss. DYOR.")


def _candles_for(sym, interval=None):
    return get_fx_candles(sym, interval) if sym in FX_PAIRS else get_candles(sym, interval)


def add_manual_signal(p, state, frames, btc_trend, src="manual", who=""):
    """ঠিক থাকলে সিগনাল খোলে আর (চ্যানেলের মেসেজ, অ্যাডমিনকে উত্তর) ফেরত দেয়"""
    coin, side = p["coin"], p["side"]
    if not coin or not side:
        return None, "❌ কয়েন বা BUY/SELL বুঝিনি।\n\n" + MANUAL_HELP
    if any(t["coin"] == coin for t in state["open"]):
        return None, f"❌ {coin}-এ আগে থেকেই একটা সিগনাল খোলা আছে। আগে <code>/close {coin}</code> দিন।"
    if sum(1 for t in state["open"] if t.get("src")) >= MANUAL_MAX_OPEN:
        return None, f"❌ একসাথে সর্বোচ্চ {MANUAL_MAX_OPEN}টা নিজের/পার্টনার সিগনাল খোলা রাখা যায়।"
    if src == "partner" and (not p["tps"] or p["sl"] is None):
        return None, "❌ এই পোস্টে TP আর SL নেই (এটা ট্রেড সিগনাল নয়), তাই নেওয়া হয়নি।"
    fx = coin in FX_PAIRS
    if fx and not fx_market_open(datetime.now(timezone.utc)):
        return None, "❌ Forex মার্কেট এখন বন্ধ (শনি-রবি)। খুললে আবার দিন।"
    try:
        df = frames.get(coin)
        if df is None:
            df = add_indicators(_candles_for(coin)[0])
        htf = trend_of(add_indicators(_candles_for(coin, TREND_INTERVAL)[0]))
    except Exception as e:
        return None, f"❌ {coin}-এর দাম আনা যায়নি ({str(e)[:60]})। একটু পরে আবার দিন।"
    cur, sign = df.iloc[-1], (1 if side == "BUY" else -1)
    price, atr = float(cur.close), float(cur.atr)
    entry = p["entry"] or price
    if abs(entry - price) / price * 100 > MANUAL_ENTRY_PCT:
        return None, (f"❌ Entry {fmt(entry, coin)} এখনকার দাম {fmt(price, coin)} থেকে {MANUAL_ENTRY_PCT:.0f}% এর বেশি দূরে। "
                      f"এখনকার দামে দিতে entry না লিখে পাঠান।")
    if p["tps"] and p["sl"] is None:
        return None, "❌ Stop Loss দেননি। SL ছাড়া সিগনাল পাঠানো হয় না। যেমন: <code>sl 64000</code>"
    sl = p["sl"] if p["sl"] is not None else entry - sign * SL_ATR * atr
    tp1 = p["tps"][0] if p["tps"] else entry + sign * TP1_ATR * atr
    tp2 = p["tps"][1] if len(p["tps"]) > 1 else (tp1 + (tp1 - entry) if p["tps"] else entry + sign * TP2_ATR * atr)
    if not ((sl - entry) * sign < 0 < (tp1 - entry) * sign <= (tp2 - entry) * sign):
        need = "SL < Entry < TP1 ≤ TP2" if side == "BUY" else "TP2 ≤ TP1 < Entry < SL"
        return None, f"❌ দামগুলো উল্টাপাল্টা। {side}-এ হতে হবে: {need}\nEntry {fmt(entry, coin)} · TP {fmt(tp1, coin)} / {fmt(tp2, coin)} · SL {fmt(sl, coin)}"
    ok, total, why = manual_check(df, side, htf, btc_trend, coin == "BTC", fx)
    t = {"coin": coin, "side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, "age": 0,
         "checked_until": cur.time.isoformat(), "sl0": sl, "opened": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "rsi": round(float(cur.rsi), 1), "conf": None, "why": why, "chk": f"{ok}/{total}", "src": src, "from": who,
         "note": p["note"], "market": "forex" if fx else "crypto", "name": label(coin)}
    warn = f"\n\n⚠ ইঞ্জিনের মাত্র {ok}/{total} নিশ্চয়তা মিলেছে — ঝুঁকি বেশি।" if ok * 2 < total else ""
    return t, f"✅ {coin} {side} সিগনাল চ্যানেল ও সাইটে গেছে।{warn}"


def close_manual(coin, state, frames):
    for t in state["open"]:
        if t["coin"] == coin:
            try:
                df = frames.get(coin)
                price = float((df if df is not None else _candles_for(coin)[0])["close"].iloc[-1])
            except Exception:
                return None, f"❌ {coin}-এর দাম আনা যায়নি, একটু পরে আবার দিন।"
            pct = (price / t["entry"] - 1) * 100 * (1 if t["side"] == "BUY" else -1)
            t["exit"] = price
            _close(t, "CLOSED", datetime.now(timezone.utc).isoformat(timespec="seconds"), state)
            state["open"].remove(t)
            return (f"🔒 {label(coin)} {t['side']}: অ্যাডমিন হাতে বন্ধ করেছেন ({fmt(price, coin)}, {pct:+.2f}%)",
                    f"✅ {coin} বন্ধ করা হলো ({pct:+.2f}%).")
    return None, f"❌ {coin}-এ কোনো খোলা সিগনাল নেই।"


def read_owner_commands(state, frames, btc_trend):
    """বটের ইনবক্স পড়ে; অ্যাডমিনের কমান্ড কাজ করে। চ্যানেলে পাঠানোর মেসেজ ফেরত দেয়"""
    if not MANUAL_ENABLED or not TELEGRAM_BOT_TOKEN:
        return []
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    try:
        r = HTTP.get(api + "getUpdates", params={"offset": state.get("tg_offset", 0), "timeout": 0,
                                                 "allowed_updates": json.dumps(["message", "channel_post"])}, timeout=20).json()
    except Exception as e:
        print("inbox error:", str(e)[:60])
        return []
    if not r.get("ok"):
        print("inbox error:", str(r.get("description"))[:80])
        return []
    admins, out = None, []
    for u in r.get("result", []):
        state["tg_offset"] = u["update_id"] + 1
        post = u.get("channel_post")
        if post:                                   # পার্টনার চ্যানেলের পোস্ট (বট সেখানে অ্যাডমিন থাকলে আসে)
            pc = post.get("chat", {})
            keys = {str(pc.get("id")), "@" + str(pc.get("username", "")).lower()}
            ptext = (post.get("text") or post.get("caption") or "").strip()
            if keys & set(state.get("partners", [])) and ptext and time.time() - post.get("date", 0) < 2 * 3600:
                t, why_not = add_manual_signal(parse_signal(ptext), state, frames, btc_trend, "partner", pc.get("title", "Partner"))
                if t and send_telegram(manual_message(t["coin"], t)):
                    state["open"].append(t)
                    print(f"partner {t['side']} {t['coin']} from {pc.get('title')}")
                elif not t:
                    print("partner post skipped:", re.sub(r"<[^>]+>", "", why_not)[:70])
            continue
        msg = u.get("message") or {}
        text = (msg.get("text") or msg.get("caption") or "").strip()
        chat, uid = msg.get("chat", {}), str(msg.get("from", {}).get("id", ""))
        fo = msg.get("forward_origin") or {}
        fwd = (fo.get("chat") or fo.get("sender_user") or msg.get("forward_from_chat") or {})
        fwd = fwd.get("title") or fwd.get("first_name") or fo.get("sender_user_name") or ""
        if chat.get("type") != "private" or not text or not uid:
            continue
        if admins is None:
            admins = {OWNER_ID} if OWNER_ID else set()
            if not OWNER_ID:
                try:
                    a = HTTP.get(api + "getChatAdministrators", params={"chat_id": TELEGRAM_CHAT_ID}, timeout=15).json()
                    admins = {str(x["user"]["id"]) for x in a.get("result", [])}
                except Exception as e:
                    print("admin list error:", str(e)[:60])
        if uid not in admins:
            send_telegram(f"👋 এই বট শুধু চ্যানেলে সিগনাল পাঠায়।\n📢 চ্যানেল ও সাইট: {SITE_URL}", chat["id"])
            continue
        if time.time() - msg.get("date", 0) > 6 * 3600:
            send_telegram("⌛ এই মেসেজটা ৬ ঘণ্টার বেশি পুরোনো, তাই নেওয়া হয়নি। আবার পাঠান।", chat["id"])
            continue
        low = text.lower()
        cmd = low.split()[0].split("@")[0]
        if cmd in ("/start", "/help"):
            send_telegram(MANUAL_HELP, chat["id"])
        elif cmd == "/list":
            rows = [f"• {label(t['coin'])} {t['side']} @ {fmt(t['entry'], t['coin'])}" + {"manual": " (নিজের)", "partner": " (পার্টনার)"}.get(t.get("src"), " (ইঞ্জিন)")
                    for t in state["open"]]
            send_telegram("📋 খোলা সিগনাল:\n" + ("\n".join(rows) or "কিছু নেই"), chat["id"])
        elif cmd == "/partner":
            ps, arg = state.setdefault("partners", []), low.split()[1:]
            names = [("@" + a.lstrip("@")) if not a.lstrip("-").isdigit() else a for a in arg if a != "off"]
            for nm in names:
                if "off" in arg:
                    if nm in ps:
                        ps.remove(nm)
                elif nm not in ps and len(ps) < 10:
                    ps.append(nm)
            send_telegram("🤝 পার্টনার চ্যানেল: " + (", ".join(ps) or "কোনোটা নেই") +
                          "\n\nযোগ: <code>/partner @channelname</code>\nবাদ: <code>/partner off @channelname</code>\n\n"
                          "ℹ️ ওই চ্যানেলের মালিককে আপনার বটকে সেখানে <b>অ্যাডমিন</b> করতে হবে, নইলে বট পোস্ট দেখতে পাবে না।", chat["id"])
        elif cmd == "/video":
            try:
                import extras
                send_telegram(extras.video_command(state, HTTP, text), chat["id"])
            except Exception as e:
                send_telegram("❌ ভিডিও যোগ করা গেল না: " + html.escape(str(e)[:80]), chat["id"])
        elif cmd == "/close":
            p = parse_signal(text[6:] + " buy")
            pub, reply = close_manual(p["coin"], state, frames) if p["coin"] else (None, "❌ কোন কয়েন? যেমন: <code>/close BTC</code>")
            if pub:
                out.append(pub)
            send_telegram(reply, chat["id"])
        elif cmd in ("/signal", "/s") or (re.search(r"\b(buy|sell|long|short)\b", low) and re.search(r"\b(sl|stop)", low)):
            t, reply = add_manual_signal(parse_signal(re.sub(r"^/\w+(@\w+)?", "", text), first_is_coin=cmd in ("/signal", "/s")),
                                         state, frames, btc_trend, "partner" if fwd else "manual", fwd)
            if t and send_telegram(manual_message(t["coin"], t)):
                state["open"].append(t)
                print(f"manual {t['side']} {t['coin']}")
            elif t:
                reply = "❌ চ্যানেলে পাঠানো যায়নি। বট চ্যানেলের অ্যাডমিন আছে কিনা দেখুন।"
            send_telegram(reply, chat["id"])
        else:
            send_telegram(MANUAL_HELP, chat["id"])
    return out


# ----------------------------- ব্লগ পোস্ট: Telegram-এ ছোট লেখা + সাইটের লিংক -----------------------------
BLOG_ENABLED = True
LESSON_HOUR_UTC = 6         # 6 UTC = দুপুর ১২টা বাংলাদেশ: রোজ একটা শেখার পোস্ট


def blog_message(p):
    e = html.escape
    title = e(p["title"]) + (f"\n{e(p['title_bn'])}" if p.get("title_bn") else "")
    return f"📰 <b>{title}</b>\n\n{e(p['sum_bn'])}\n\n🔗 {SITE_URL}#/blog/{p['slug']}"


def blog_digest(frames, state):
    import blog
    fg, fg_txt = get_fear_greed()
    if fg is not None:
        state["fear_greed"] = {"value": fg, "label": fg_txt}
    majors = [{"sym": c, "name": c, "price": float(df["close"].iloc[-1]),
               "ch": round(float((df["close"].iloc[-1] / df["close"].iloc[-25] - 1) * 100), 2)}
              for c, df in frames.items() if len(df) > 24]
    fx = [{"sym": k, "name": label(k), "price": q["price"], "ch": q["ch"]} for k, q in state.get("fx_quotes", {}).items()]
    return blog.digest(HTTP, BROWSER_UA, majors, {"fear_greed": state.get("fear_greed"), "fx": fx,
                                                  "stats": state["stats"], "open": len(state["open"])})


# ----------------------------- Trending কয়েন (দিনে একবার) -----------------------------
TRENDING_ENABLED = True
TRENDING_HOUR_UTC = 14      # 14 UTC = রাত ৮টা বাংলাদেশ


def trending_message():
    r = HTTP.get("https://api.coingecko.com/api/v3/search/trending", headers=BROWSER_UA, timeout=20).json()
    lines = ["🔥 <b>আজ যেসব কয়েন সবচেয়ে বেশি খোঁজা হচ্ছে</b> (Trending)\n"]
    for i, c in enumerate((r.get("coins") or [])[:7], 1):
        it = c.get("item", {})
        d = it.get("data") or {}
        ch = (d.get("price_change_percentage_24h") or {}).get("usd")
        try:
            price = f" · ${fmt(float(d.get('price')))}"
        except (TypeError, ValueError):
            price = ""
        rank = f" · #{it['market_cap_rank']}" if it.get("market_cap_rank") else ""
        chs = f" ({'🟢' if ch >= 0 else '🔴'} {ch:+.1f}%)" if isinstance(ch, (int, float)) else ""
        lines.append(f"{i}. <b>{html.escape(str(it.get('symbol', '')).upper())}</b> — {html.escape(str(it.get('name', '')))}{rank}{price}{chs}")
    if len(lines) < 4:
        return None
    lines.append("\nℹ️ Trending মানে মানুষ বেশি খুঁজছে — কেনার পরামর্শ নয়। বেশি খোঁজা কয়েনে দাম দ্রুত ওঠে, দ্রুত পড়েও।")
    lines.append(f"🌐 <a href=\"{SITE_URL}#/market\">মার্কেট দেখুন</a>  ·  <i>source: CoinGecko</i>\n⚠️ Not financial advice. DYOR.")
    return "\n".join(lines)


# ----------------------------- Market Watch নোট (দুর্বল সেটআপ: Entry/TP/SL ছাড়া) -----------------------------
WATCH_NOTES = True     # False করলে বন্ধ
WATCH_MIN = 40         # এর কম স্কোর হলে নোটও যাবে না
WATCH_PER_DAY = 4      # দিনে সর্বোচ্চ কয়টা নোট


ENGINE_NAME = "BEWON Engine v2.0"
NEED_CONFIRM = 3       # ৪টা নিশ্চয়তার মধ্যে কমপক্ষে এতগুলো মিললে তবেই পূর্ণ Trade Signal


def deep_check(sym, sig, df, htf, btc_trend, is_btc):
    """স্কোরের ভেতরের হিসাব: ট্রেন্ড, মোমেন্টাম, কয়েকটা টাইমফ্রেম, BTC, আর ৪টা নিশ্চয়তা"""
    c, d = df.iloc[-1], (1 if sig["side"] == "BUY" else -1)
    fx = sym in FX_PAIRS
    trend = 5 * ((c.ema_fast - c.ema_slow) * d > 0) + 5 * ((c.close - c.ema200) * d > 0) + (5 if c.adx >= 20 else 2 if c.adx >= 15 else 0)
    mom = 4 * (c.macd_hist * d > 0) + 4 * ((c.macd_hist - df.iloc[-2].macd_hist) * d > 0) + 4 * ((c.rsi - 50) * d > 0)
    tfs = [(TREND_INTERVAL.upper(), htf == d)]
    for tf in ("15m", "5m"):
        try:
            tfs.append((tf.upper(), trend_of(add_indicators(_candles_for(sym, tf)[0])) == d))
        except Exception:
            pass
    mtf = round(100 * sum(ok for _, ok in tfs) / len(tfs))
    back = df.iloc[-4]
    hi, lo = df["high"].iloc[-50:].max(), df["low"].iloc[-50:].min()
    room = (hi - c.close) if d > 0 else (c.close - lo)
    checks = [("run-up", bool((c.close - back.close) * d >= 0.5 * c.atr)),     # দাম সত্যিই ওই দিকে চলা শুরু করেছে
              ("RSI", bool(((c.rsi - 50) * d > 0) and ((c.rsi - df.iloc[-2].rsi) * d > 0))),
              ("extension", bool(abs(c.close - c.ema_slow) <= 1.5 * c.atr)),   # দাম গড় থেকে বেশি দূরে চলে যায়নি
              ("range", bool(room >= 1.0 * c.atr or room <= 0))]               # সামনে চলার জায়গা আছে / নতুন হাই-লো ভেঙেছে
    btc_day = None
    if not fx:
        try:
            bd = get_candles("BTC", "1d")[0]
            btc_day = bool(bd["close"].iloc[-1] > bd["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        except Exception:
            pass
    return {"h1": int(sig["conf"]), "mtf": mtf, "score": int(round(0.75 * sig["conf"] + 0.25 * mtf)),
            "trend": int(trend), "mom": int(mom), "tfs": tfs, "checks": checks, "ok": sum(1 for _, v in checks if v),
            "btc": 0 if (is_btc or fx) else btc_trend * d, "btc_dir": btc_trend, "btc_day": btc_day}


def _grade_word(score):
    return "Strong" if score >= 78 else "Moderate" if score >= 60 else "Weak"


def deep_lines(sym, sig, dc):
    d = 1 if sig["side"] == "BUY" else -1
    side = "Bullish" if d > 0 else "Bearish"
    yn = lambda v: "✅" if v else "❌"
    tw = side if dc["trend"] >= 10 else "Mixed"
    mw = ("Strong " + side) if dc["mom"] == 12 else side if dc["mom"] >= 8 else "Weak"
    out = (f"Signal Grade: {grade(dc['score'])} / {_grade_word(dc['score'])}\n"
           f"<b>Signal Score: {dc['score']}/100 (1H: {dc['h1']}, MTF: {dc['mtf']})</b>\n\n"
           f"📊 Market\n"
           f"Trend: {tw} ({dc['trend']}/15)\n"
           f"Momentum: {mw} ({dc['mom']}/12)\n"
           f"Timeframes: " + " ".join(f"{n} {yn(v)}" for n, v in dc["tfs"]) + "\n")
    if sym not in FX_PAIRS:
        if sym != "BTC" and dc["btc_dir"]:
            out += f"BTC Regime: {'Bullish' if dc['btc_dir'] > 0 else 'Bearish'} {'✅' if dc['btc'] > 0 else '⚠️'}\n"
        if dc["btc_day"] is not None:
            out += f"BTC Daily: {'above' if dc['btc_day'] else 'below'} its 50-day EMA {yn(dc['btc_day'] == (d > 0))}\n"
    out += f"Confirmations: {dc['ok']}/{len(dc['checks'])} (" + " ".join(f"{n} {yn(v)}" for n, v in dc["checks"]) + ")\n"
    return out


def watch_message(sym, sig, dc, source):
    fx = sym in FX_PAIRS
    name = label(sym) if fx else sym + "/USDT"
    link = f"{SITE_URL}#/forex" if fx else f"{SITE_URL}#/coin/{sym}"
    miss = ", ".join(n for n, v in dc["checks"] if not v)
    if dc["score"] >= MIN_CONFIDENCE:
        why = (f"The score cleared our bar ({dc['score']}/100), but only {dc['ok']} of {len(dc['checks'])} confirmation checks are in — "
               f"the move isn't confirmed yet ({miss}). Entering before a move is underway usually ends worse, "
               f"so this is a watch note, not a Trade Signal — no entry, target or stop-loss is given.")
    else:
        why = (f"A {'bullish' if sig['side'] == 'BUY' else 'bearish'} setup is forming, but the score ({dc['score']}/100) is below our bar "
               f"({MIN_CONFIDENCE}). This is a watch note, not a Trade Signal — no entry, target or stop-loss is given.")
    now = datetime.now(timezone.utc) + timedelta(hours=6)
    return (f"👀 <b>{name} — Market Watch ({grade(dc['score'])})</b>\n\n"
            + deep_lines(sym, sig, dc) + "\n"
            + why + "\n\n"
            f"This is a rule-based technical-analysis score, not a win probability — informational only, "
            f"not financial advice, and no profit is guaranteed.\n\n"
            f"🕐 Generated: {now:%d %b %Y, %H:%M} UTC+6\n\n"
            f"🔗 View {name} chart: <a href=\"{link}\">{link.replace('https://', '')}</a>\n\n"
            f"{ENGINE_NAME} · Data: {source}\nRule-based Technical Analysis\n\n— BEWON Signal Assistant")


def try_new_signal(sym, df, source, state, htf_fn, btc_trend=0, is_btc=True, market="crypto"):
    """একটা কয়েন বা Forex পেয়ারে নতুন সিগনাল আছে কিনা দেখে, থাকলে পাঠায়"""
    sig = check_signal(df, need_volume=(market == "crypto"))
    has_open = any(t["coin"] == sym for t in state["open"])
    if not sig or has_open or state["last_signal"].get(sym) == sig["candle"]:
        return
    try:
        htf = trend_of(add_indicators(htf_fn()))
    except Exception:
        htf = 0
    sig["conf"], sig["why"] = score_signal(df, sig["side"], htf, btc_trend, is_btc, fx=(market == "forex"))
    if sig["conf"] < WATCH_MIN:
        print(f"skip {sig['side']} {sym}: score {sig['conf']} < {WATCH_MIN}")
        state["last_signal"][sym] = sig["candle"]
        return
    dc = deep_check(sym, sig, df, htf, btc_trend, is_btc)
    sig["conf"] = dc["score"]
    sig["chk"] = f"{dc['ok']}/{len(dc['checks'])}"
    sig["deep"] = deep_lines(sym, sig, dc)
    if dc["score"] < MIN_CONFIDENCE or dc["ok"] < NEED_CONFIRM:
        print(f"watch {sig['side']} {sym}: score {dc['score']}, confirmations {sig['chk']}")
        state["last_signal"][sym] = sig["candle"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        w = state.get("watch", {})
        if w.get("day") != today:
            w = {"day": today, "n": 0}
        if WATCH_NOTES and w["n"] < WATCH_PER_DAY:
            if send_telegram(watch_message(sym, sig, dc, source)):
                w["n"] += 1
                state.setdefault("watch_notes", []).insert(0, {
                    "coin": sym, "name": label(sym), "market": market, "side": sig["side"], "price": float(sig["entry"]),
                    "score": dc["score"], "chk": sig["chk"],
                    "why": [("" if v else "⚠ ") + n for n, v in dc["tfs"] + dc["checks"]],
                    "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                del state["watch_notes"][20:]
        state["watch"] = w
        return
    if send_telegram(signal_message(sym, sig, source)):
        state["last_signal"][sym] = sig["candle"]
        state["open"].append({"coin": sym, "side": sig["side"], "entry": sig["entry"],
                              "sl": sig["sl"], "tp1": sig["tp1"], "tp2": sig["tp2"],
                              "tp1_hit": False, "age": 0, "checked_until": sig["candle"],
                              "sl0": sig["sl"], "opened": sig["candle"], "rsi": sig["rsi"],
                              "conf": sig["conf"], "why": sig["why"], "market": market, "name": label(sym)})
        print(f"sent {sig['side']} {sym} (data: {source})")


def run_forex(state, outbox, fails):
    now = datetime.now(timezone.utc)
    if not FOREX_ENABLED or not fx_market_open(now):
        print("forex: market closed")
        return
    quotes = {}
    for sym in FX_PAIRS:
        try:
            raw, source = get_fx_candles(sym)
            df = add_indicators(raw)
        except Exception as e:
            fails.append(f"{sym}: {e}")
            continue
        outbox += update_open_trades(sym, df, state)
        if len(df) > 24:
            quotes[sym] = {"price": round(float(df["close"].iloc[-1]), 5),
                           "ch": round(float((df["close"].iloc[-1] / df["close"].iloc[-25] - 1) * 100), 2),
                           "time": df["time"].iloc[-1].isoformat()}
        try_new_signal(sym, df, source, state, lambda s=sym: get_fx_candles(s, TREND_INTERVAL)[0], market="forex")
        time.sleep(0.5)
    if quotes:
        state["fx_quotes"] = quotes


def run_once(force_digest=False):
    state = load_state()
    frames, fails, outbox = {}, [], []

    btc_trend = 0
    for coin in COINS:
        try:
            raw, source = get_candles(coin)
            df = add_indicators(raw)
            frames[coin] = df
        except Exception as e:
            fails.append(f"{coin}: {e}")
            continue

        # (ক) আগের সিগনালের ফলাফল
        outbox += update_open_trades(coin, df, state)

        if coin == "BTC":
            btc_trend = 1 if df.iloc[-1].ema_fast > df.iloc[-1].ema_slow else -1

        # (খ) নতুন সিগনাল
        try_new_signal(coin, df, source, state, lambda c=coin: get_candles(c, TREND_INTERVAL)[0],
                       btc_trend, coin == "BTC", "crypto")
        time.sleep(0.3)

    # (খ২) Forex ও Gold
    try:
        run_forex(state, outbox, fails)
    except Exception as e:
        print("forex error:", e)

    # (খ২.৪) তালিকার বাইরের কয়েনে খোলা নিজের/পার্টনার সিগনাল
    for coin in sorted({t["coin"] for t in state["open"]} - set(COINS) - set(FX_PAIRS)):
        try:
            df = add_indicators(get_candles(coin)[0])
            frames_extra = update_open_trades(coin, df, state)
            outbox += frames_extra
        except Exception as e:
            fails.append(f"{coin}: {str(e)[:60]}")

    # (খ২.৫) অ্যাডমিনের নিজের সিগনাল (Telegram ইনবক্স থেকে)
    try:
        outbox += read_owner_commands(state, frames, btc_trend)
    except Exception as e:
        print("manual error:", str(e)[:80])

    # (খ৩) হঠাৎ ওঠানামার অ্যালার্ট
    try:
        outbox_vol = check_volatility(state)
    except Exception as e:
        print("volatility error:", e)
        outbox_vol = []
    for m in outbox_vol:
        send_telegram(m)

    for m in outbox:
        send_telegram(m + f"\n🌐 <a href=\"{SITE_URL}#/signals\">সব ফলাফল ওয়েবসাইটে</a>")

    # (গ) দিনে একবার সারাংশ
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if force_digest or (now.hour >= DIGEST_HOUR_UTC and state["last_digest"] != today):
        msg, post = None, None
        if BLOG_ENABLED and frames:
            try:
                post = blog_digest(frames, state)
                msg = blog_message(post) if post else None
            except Exception as e:
                print("blog digest error:", str(e)[:80])
        full = None
        try:                       # পুরো তালিকা: দাম, ২৪ঘ পরিবর্তন, রেঞ্জ, ভলিউম (ছবির মতো ফরম্যাট)
            import posts
            full = posts.market_digest(HTTP, COINS, SITE_URL, state.get("fear_greed"),
                                       f"{SITE_URL}#/blog/{post['slug']}" if post else None)
        except Exception as e:
            print("market digest error:", str(e)[:80])
        if frames and send_telegram(full or msg or daily_digest(frames, state), preview=False):
            state["last_digest"] = today

    if now.weekday() == 0 and now.hour >= 3 and state.get("last_week") != today:   # সোমবার: সাপ্তাহিক ফলাফল
        try:
            import posts
            if send_telegram(posts.weekly_recap(state, SITE_URL)):
                state["last_week"] = today
        except Exception as e:
            print("weekly recap error:", str(e)[:80])
    try:                                   # লিকুইডেশন কার্ড (ছবি) প্রতি ৪ ঘণ্টায় + বড় লিকুইডেশনে অ্যালার্ট
        import posts
        posts.run_liquidations(state, HTTP, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SITE_URL)
        posts.run_promo(state, HTTP, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SITE_URL)
    except Exception as e:
        print("liquidations error:", str(e)[:80])

    if TRENDING_ENABLED and now.hour >= TRENDING_HOUR_UTC and state.get("last_trending") != today:
        try:
            tm = None
            if BLOG_ENABLED:
                try:
                    import blog
                    post = blog.trending(HTTP, BROWSER_UA)
                    tm = blog_message(post) if post else None
                except Exception as e:
                    print("blog trending error:", str(e)[:80])
            tm = tm or trending_message()
            if tm and send_telegram(tm, preview=True):
                state["last_trending"] = today
        except Exception as e:
            print("trending error:", str(e)[:80])

    if BLOG_ENABLED and now.hour >= LESSON_HOUR_UTC and state.get("last_lesson") != today:
        try:
            import blog
            post = blog.lesson(state.get("lesson_n", 0))
            if send_telegram(blog_message(post), preview=True):
                state["last_lesson"] = today
                state["lesson_n"] = state.get("lesson_n", 0) + 1
        except Exception as e:
            print("lesson error:", str(e)[:80])

    try:
        update_news(state)
    except Exception as e:
        print("news error:", e)
    try:
        update_insights(state)
    except Exception as e:
        print("insights error:", e)
    # টপ-২০ কয়েনের বহু-উৎসের মত (consensus), রিমোট জবের তালিকা, ভিডিও — সব docs/data-তে
    try:
        import extras
        extras.run(state, HTTP, frames, lambda c: add_indicators(get_candles(c)[0]), state.get("fear_greed"))
    except Exception as e:
        print("extras error:", str(e)[:80])
    # উৎস পরীক্ষা: নতুন সংস্করণ এলে একবার নিজে থেকে চলে, ফল docs/data/probe.json-এ থাকে
    try:
        import probe
        if state.get("probe_v") != probe.PROBE_VERSION:
            probe.run()
            state["probe_v"] = probe.PROBE_VERSION
    except Exception as e:
        print("probe error:", str(e)[:80])
    try:                                   # সিগনাল ল্যাব: নতুন সংস্করণ এলে একবার নিজে থেকে চলে
        import lab
        if state.get("lab_v") != lab.LAB_VERSION:
            state["lab_v"] = lab.LAB_VERSION
            lab.run()
    except BaseException as e:
        print("lab error:", str(e)[:80])
    save_state(state)   # কিছু বদলালে তবেই GitHub এ নতুন commit হবে
    print(f"done: {len(frames)}/{len(COINS)} coins ok, open={len(state['open'])}")
    for f in fails:
        print("FAIL", f)
    if not frames:
        sys.exit("কোনো এক্সচেঞ্জ থেকেই ডেটা আসেনি")


def run_test():
    lines = ["🤖 <b>Test message</b> — bot কাজ করছে!\n"]
    for name, fn in SOURCES:
        try:
            df = fn("BTC")
            lines.append(f"✅ {name}: BTC = {fmt(df['close'].iloc[-1])}")
        except Exception as e:
            lines.append(f"❌ {name}: {str(e)[:60]}")
    fg, fg_txt = get_fear_greed()
    lines.append(f"{'✅' if fg is not None else '❌'} Fear & Greed: {fg} {fg_txt or ''}")
    lines.append(f"\n🌐 ওয়েবসাইট: {SITE_URL}")
    ok = send_telegram("\n".join(lines))
    print("Telegram:", "OK" if ok else "FAILED")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    mode = (sys.argv[1] if len(sys.argv) > 1 else "--once").lstrip("-")
    if mode == "test":
        run_test()
    elif mode == "digest":
        run_once(force_digest=True)
    elif mode == "backtest":
        import backtest
        backtest.run()
    elif mode == "lab":
        import lab
        lab.run()
    elif mode == "probe":
        import probe
        probe.run()
    elif mode == "loop":
        print("Bot চালু... বন্ধ করতে Ctrl+C")
        while True:
            try:
                run_once()
            except SystemExit as e:
                print(e)
            time.sleep(LOOP_EVERY_SEC)
    else:
        run_once()
