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

import json
import os
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

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT"]
INTERVAL = "1h"             # 15m / 1h / 4h
EMA_FAST, EMA_SLOW = 9, 21
RSI_LEN, ATR_LEN = 14, 14
SL_ATR, TP1_ATR, TP2_ATR = 1.5, 1.5, 3.0   # Stop Loss / Target দূরত্ব (ATR এর গুণ)
MAX_TRADE_CANDLES = 48      # এতগুলো ক্যান্ডেলে TP/SL না হলে "Expired"
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


def from_binance(coin, limit=200):
    # api.binance.com আমেরিকার সার্ভার (GitHub) থেকে ব্লক, তাই data-api ব্যবহার করছি
    r = HTTP.get("https://data-api.binance.vision/api/v3/klines",
                 params={"symbol": f"{coin}USDT", "interval": INTERVAL, "limit": limit}, timeout=15)
    r.raise_for_status()
    df = _frame([row[:6] for row in r.json()], "ms")
    return df.iloc[:-1]                     # শেষ ক্যান্ডেল এখনো চলছে → বাদ


def from_okx(coin, limit=200):
    bar = {"15m": "15m", "1h": "1H", "4h": "4H"}[INTERVAL]
    r = HTTP.get("https://www.okx.com/api/v5/market/candles",
                 params={"instId": f"{coin}-USDT", "bar": bar, "limit": min(limit, 300)}, timeout=15)
    r.raise_for_status()
    data = r.json().get("data") or []
    closed = [row[:6] for row in data if row[8] == "1"]   # "1" = ক্যান্ডেল বন্ধ হয়েছে
    if not closed:
        raise ValueError("OKX: no data")
    return _frame(closed, "ms")


def from_kucoin(coin, limit=200):
    typ = {"15m": "15min", "1h": "1hour", "4h": "4hour"}[INTERVAL]
    r = HTTP.get("https://api.kucoin.com/api/v1/market/candles",
                 params={"type": typ, "symbol": f"{coin}-USDT"}, timeout=15)
    r.raise_for_status()
    data = r.json().get("data") or []
    if not data:
        raise ValueError("KuCoin: no data")
    # KuCoin ক্রম: time, open, close, high, low, volume
    rows = [[d[0], d[1], d[3], d[4], d[2], d[5]] for d in data[:limit]]
    return _frame(rows, "s").iloc[:-1]


def from_kraken(coin, limit=200):
    base = {"BTC": "XBT", "DOGE": "XDG"}.get(coin, coin)
    minutes = {"15m": 15, "1h": 60, "4h": 240}[INTERVAL]
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


def get_candles(coin):
    """একটা এক্সচেঞ্জ কাজ না করলে পরেরটা চেষ্টা করে"""
    errors = []
    for name, fn in SOURCES:
        try:
            df = fn(coin)
            if len(df) >= 60:
                return df, name
            errors.append(f"{name}: only {len(df)} candles")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:80]}")
    raise RuntimeError(" | ".join(errors))


def get_fear_greed():
    """ফ্রি Fear & Greed Index (alternative.me) — ০ = খুব ভয়, ১০০ = খুব লোভ"""
    try:
        d = HTTP.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except Exception:
        return None, None


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
    return df


def check_signal(df):
    """শেষ বন্ধ হওয়া ক্যান্ডেলে নতুন সিগনাল আছে কিনা"""
    prev, cur = df.iloc[-2], df.iloc[-1]
    crossed_up = prev.ema_fast <= prev.ema_slow and cur.ema_fast > cur.ema_slow
    crossed_down = prev.ema_fast >= prev.ema_slow and cur.ema_fast < cur.ema_slow
    good_volume = cur.volume > cur.vol_avg

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
        "opened": t.get("opened", ""), "closed": when, "result": result})
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
            hit_sl = c.low <= t["sl"] if buy else c.high >= t["sl"]
            hit_tp1 = c.high >= t["tp1"] if buy else c.low <= t["tp1"]
            hit_tp2 = c.high >= t["tp2"] if buy else c.low <= t["tp2"]
            if hit_sl:   # একই ক্যান্ডেলে দুটোই হলে সাবধানে SL ধরছি
                if t["tp1_hit"]:
                    msgs.append(f"🟡 {coin} {t['side']}: TP1 এর পর দাম Entry তে ফিরে এসেছে — লাভ লক (Breakeven)")
                    _close(t, "TP1", c.time.isoformat(), state)
                else:
                    state["stats"]["loss"] += 1
                    msgs.append(f"❌ {coin} {t['side']}: Stop Loss হিট ({fmt(t['sl'])})")
                    _close(t, "SL", c.time.isoformat(), state)
                closed = True
                break
            if hit_tp2:
                if not t["tp1_hit"]:
                    state["stats"]["win"] += 1
                state["stats"]["tp2"] += 1
                msgs.append(f"🎯🎯 {coin} {t['side']}: TP2 হিট! ({fmt(t['tp2'])})")
                _close(t, "TP2", c.time.isoformat(), state)
                closed = True
                break
            if hit_tp1 and not t["tp1_hit"]:
                t["tp1_hit"] = True
                state["stats"]["win"] += 1
                t["sl"] = t["entry"]          # TP1 এর পর SL কে Entry তে সরানো হলো
                msgs.append(f"✅ {coin} {t['side']}: TP1 হিট! ({fmt(t['tp1'])}) — এখন SL = Entry")
            if t["age"] >= MAX_TRADE_CANDLES:
                if not t["tp1_hit"]:
                    state["stats"]["expired"] += 1
                msgs.append(f"⌛ {coin} {t['side']}: সময় শেষ, সিগনাল বন্ধ")
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
def fmt(x):
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    return f"{x:.6f}"


def signal_message(coin, s, source):
    icon = "🟢" if s["side"] == "BUY" else "🔴"
    return (f"{icon} <b>{s['side']} — {coin}/USDT</b>  ({INTERVAL})\n\n"
            f"Entry: <code>{fmt(s['entry'])}</code>\n"
            f"TP1: <code>{fmt(s['tp1'])}</code>\n"
            f"TP2: <code>{fmt(s['tp2'])}</code>\n"
            f"Stop Loss: <code>{fmt(s['sl'])}</code>\n"
            f"RSI: {s['rsi']}  |  Data: {source}\n\n"
            f"⚠️ Free signal, not financial advice. Use Stop Loss. DYOR.")


def win_rate_text(st):
    done = st["win"] + st["loss"]
    if not done:
        return "এখনো কোনো সিগনাল শেষ হয়নি"
    return (f"Win {st['win']} | Loss {st['loss']} | Expired {st['expired']} | "
            f"Win rate {st['win'] * 100 / done:.0f}%")


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("---- (Telegram সেট করা নেই, তাই শুধু দেখাচ্ছি) ----\n" + text + "\n")
        return True
    try:
        r = HTTP.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": "true"}, timeout=15)
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
    keep = ("coin", "side", "entry", "sl", "tp1", "tp2", "tp1_hit", "opened", "rsi")
    payload = {
        "interval": INTERVAL, "coins": COINS, "stats": state["stats"],
        "open": [{k: t.get(k) for k in keep} for t in state["open"]],
        "history": state.get("history", [])[:200],
        "fear_greed": state.get("fear_greed"),
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
    if fg is not None:
        lines.append(f"\n😨→🤑 Fear & Greed: <b>{fg}</b> ({fg_txt})  <i>source: alternative.me</i>")
    lines.append(f"\n📈 Bot record: {win_rate_text(state['stats'])}")
    lines.append(f"🔓 Open signals: {len(state['open'])}")
    lines.append("\n⚠️ Not financial advice.")
    return "\n".join(lines)


# ----------------------------- ৭. মূল কাজ -----------------------------
def run_once(force_digest=False):
    state = load_state()
    frames, fails, outbox = {}, [], []

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

        # (খ) নতুন সিগনাল
        sig = check_signal(df)
        has_open = any(t["coin"] == coin for t in state["open"])
        if sig and not has_open and state["last_signal"].get(coin) != sig["candle"]:
            if send_telegram(signal_message(coin, sig, source)):
                state["last_signal"][coin] = sig["candle"]
                state["open"].append({"coin": coin, "side": sig["side"], "entry": sig["entry"],
                                      "sl": sig["sl"], "tp1": sig["tp1"], "tp2": sig["tp2"],
                                      "tp1_hit": False, "age": 0, "checked_until": sig["candle"],
                                      "sl0": sig["sl"], "opened": sig["candle"], "rsi": sig["rsi"]})
                print(f"sent {sig['side']} {coin} (data: {source})")
        time.sleep(0.3)

    for m in outbox:
        send_telegram(m)

    # (গ) দিনে একবার সারাংশ
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if force_digest or (now.hour >= DIGEST_HOUR_UTC and state["last_digest"] != today):
        if frames and send_telegram(daily_digest(frames, state)):
            state["last_digest"] = today

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
