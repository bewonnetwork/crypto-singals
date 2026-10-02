"""BEWON ব্যাকটেস্ট: গত ২ বছরের দামে বটের একই নিয়ম চালিয়ে ফলাফল বের করে।
চালানো:  python signal_bot.py --backtest     (GitHub Actions → Run workflow → backtest)
ফলাফল:   docs/data/backtest.json  (ওয়েবসাইটের সিগনাল পেজে দেখায়) + Telegram-এ সারাংশ
"""
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd

import signal_bot as b

YEARS = 2
FEE = 0.001                      # প্রতি দিকে ০.১% ফি
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "backtest.json")


def history(coin, hours):
    """Binance থেকে ১ ঘণ্টার পুরোনো ক্যান্ডেল, ১০০০টা করে পেছনে গিয়ে"""
    rows, end = [], None
    while len(rows) < hours:
        params = {"symbol": f"{coin}USDT", "interval": "1h", "limit": 1000}
        if end:
            params["endTime"] = end
        r = b.HTTP.get("https://data-api.binance.vision/api/v3/klines", params=params, timeout=20)
        r.raise_for_status()
        chunk = r.json()
        if not chunk:
            break
        rows = [x[:6] for x in chunk] + rows
        end = chunk[0][0] - 1
        if len(chunk) < 1000:
            break
        time.sleep(0.15)
    df = b._frame(rows, "ms").drop_duplicates("time").reset_index(drop=True)
    return df.iloc[:-1].tail(hours).reset_index(drop=True)


def htf_trend_series(df):
    """প্রতিটা ১ ঘণ্টার ক্যান্ডেলের জন্য শেষ বন্ধ হওয়া ৪ ঘণ্টার ট্রেন্ড (+1/-1/0)"""
    h4 = df.set_index("time").resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                                 "close": "last", "volume": "sum"}).dropna()
    e50 = h4["close"].ewm(span=50, adjust=False).mean()
    e200 = h4["close"].ewm(span=200, adjust=False).mean()
    tr = pd.Series(0, index=h4.index)
    tr[(e50 > e200) & (h4["close"] > e50)] = 1
    tr[(e50 < e200) & (h4["close"] < e50)] = -1
    tr.index = tr.index + pd.Timedelta(hours=4)           # ক্যান্ডেল বন্ধ হওয়ার পর থেকে জানা যায়
    return tr.reindex(df["time"], method="ffill").fillna(0).astype(int).values


def simulate(coin, df, btc_dir):
    """একটা কয়েনে সব সিগনাল বের করে ফলাফল হিসাব করে। ফল R-এ (1R = Stop Loss-এর দূরত্ব)।"""
    df = b.add_indicators(df)
    htf = htf_trend_series(df)
    up = (df.ema_fast.shift() <= df.ema_slow.shift()) & (df.ema_fast > df.ema_slow) & (df.rsi > 45) & (df.rsi < 70)
    dn = (df.ema_fast.shift() >= df.ema_slow.shift()) & (df.ema_fast < df.ema_slow) & (df.rsi > 30) & (df.rsi < 55)
    cand = df.index[(up | dn) & (df.volume > df.vol_avg)]
    trades, busy_until = [], -1
    H, L, C = df.high.values, df.low.values, df.close.values
    for i in cand:
        if i < 250 or i <= busy_until or i + 1 >= len(df):
            continue
        win = df.iloc[i - 1:i + 1]
        sig = b.check_signal(win)
        if not sig:
            continue
        ts = df.time.iloc[i]
        bt = 0 if coin == "BTC" else int(btc_dir.get(ts, 0))
        conf, _ = b.score_signal(win, sig["side"], int(htf[i]), bt, coin == "BTC")
        buy = sig["side"] == "BUY"
        entry, sl, tp1, tp2 = sig["entry"], sig["sl"], sig["tp1"], sig["tp2"]
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        d = 1 if buy else -1
        tp1_hit, result, r, j = False, "EXPIRED", 0.0, i
        for j in range(i + 1, min(i + 1 + b.MAX_TRADE_CANDLES, len(df))):
            hit_sl = L[j] <= sl if buy else H[j] >= sl
            hit_tp1 = H[j] >= tp1 if buy else L[j] <= tp1
            hit_tp2 = H[j] >= tp2 if buy else L[j] <= tp2
            if hit_sl:                                   # একই ক্যান্ডেলে দুটোই হলে সাবধানে SL ধরা হয় (লাইভ বটের মতো)
                result, r = ("TP1", 0.5 * b.TP1_ATR / b.SL_ATR) if tp1_hit else ("SL", -1.0)
                break
            if hit_tp2:
                result = "TP2"
                r = 0.5 * b.TP1_ATR / b.SL_ATR + 0.5 * b.TP2_ATR / b.SL_ATR
                break
            if hit_tp1 and not tp1_hit:
                tp1_hit, sl = True, entry
        else:
            rest = (C[j] - entry) * d / risk
            result, r = ("TP1", 0.5 * b.TP1_ATR / b.SL_ATR + 0.5 * rest) if tp1_hit else ("EXPIRED", rest)
        r -= 2 * FEE * entry / risk                       # ঢোকা + বের হওয়ার ফি
        busy_until = j
        trades.append({"coin": coin, "side": sig["side"], "time": ts.isoformat(), "conf": conf,
                       "result": result, "r": round(r, 3)})
    return trades


def summary(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    rs = [t["r"] for t in rows]
    wins = sum(1 for t in rows if t["result"] in ("TP1", "TP2"))
    loss = sum(1 for t in rows if t["result"] == "SL")
    eq = peak = dd = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gp, gl = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return {"n": n, "win_rate": round(wins * 100 / (wins + loss), 1) if wins + loss else None,
            "tp2": sum(1 for t in rows if t["result"] == "TP2"), "sl": loss,
            "expired": sum(1 for t in rows if t["result"] == "EXPIRED"),
            "total_r": round(sum(rs), 1), "avg_r": round(sum(rs) / n, 3),
            "profit_factor": round(gp / gl, 2) if gl else None, "max_dd_r": round(dd, 1)}


def bucket(c):
    return "85+" if c >= 85 else "78-84" if c >= 78 else "70-77" if c >= 70 else "60-69" if c >= 60 else "<60"


def run():
    hours = YEARS * 365 * 24
    data, fails = {}, []
    for coin in b.COINS:
        try:
            data[coin] = history(coin, hours + 300)
            print(f"{coin}: {len(data[coin])} candles, {data[coin].time.iloc[0].date()} → {data[coin].time.iloc[-1].date()}")
        except Exception as e:
            fails.append(f"{coin}: {str(e)[:80]}")
            print("FAIL", fails[-1])
    if "BTC" not in data:
        raise SystemExit("BTC ডেটা আসেনি, ব্যাকটেস্ট করা গেল না")
    btc = b.add_indicators(data["BTC"])
    btc_dir = dict(zip(btc.time, (btc.ema_fast > btc.ema_slow).map({True: 1, False: -1})))
    trades = []
    for coin, df in data.items():
        trades += simulate(coin, df, btc_dir)
    trades.sort(key=lambda t: t["time"])
    sent = [t for t in trades if t["conf"] >= b.MIN_CONFIDENCE]       # বট যেগুলো আসলে পাঠাত
    monthly, eq = {}, 0.0
    for t in sent:
        monthly[t["time"][:7]] = monthly.get(t["time"][:7], 0) + t["r"]
    curve = []
    for m in sorted(monthly):
        eq += monthly[m]
        curve.append({"m": m, "r": round(monthly[m], 1), "eq": round(eq, 1)})
    order = ["85+", "78-84", "70-77", "60-69", "<60"]
    out = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "from": min(d.time.iloc[250] for d in data.values()).isoformat(), "to": max(d.time.iloc[-1] for d in data.values()).isoformat(),
        "years": YEARS, "coins": list(data), "min_conf": b.MIN_CONFIDENCE, "fee_pct": FEE * 100,
        "rules": {"sl_atr": b.SL_ATR, "tp1_atr": b.TP1_ATR, "tp2_atr": b.TP2_ATR, "max_candles": b.MAX_TRADE_CANDLES},
        "all": summary(sent), "buy": summary([t for t in sent if t["side"] == "BUY"]),
        "sell": summary([t for t in sent if t["side"] == "SELL"]),
        "unfiltered": summary(trades),
        "by_conf": [{"bucket": k, **summary([t for t in trades if bucket(t["conf"]) == k])} for k in order],
        "by_conf_buy": [{"bucket": k, **summary([t for t in trades if bucket(t["conf"]) == k and t["side"] == "BUY"])} for k in order],
        "by_conf_sell": [{"bucket": k, **summary([t for t in trades if bucket(t["conf"]) == k and t["side"] == "SELL"])} for k in order],
        "by_coin": [{"coin": c, **summary([t for t in sent if t["coin"] == c])} for c in data],
        "monthly": curve, "fails": fails,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    def line(name, s):
        if not s.get("n"):
            return f"{name}: কোনো ট্রেড নেই"
        return (f"{name}: {s['n']} ট্রেড · Win {s['win_rate']}% · মোট {s['total_r']:+}R · গড় {s['avg_r']:+}R · "
                f"PF {s['profit_factor']} · সর্বোচ্চ পতন {s['max_dd_r']}R")
    print("\n===== BACKTEST RESULT =====")
    print(f"সময়: {out['from'][:10]} → {out['to'][:10]} · ফি {FEE * 100}%/দিক · Confidence ≥ {b.MIN_CONFIDENCE}%")
    for name, key in (("সব", "all"), ("BUY", "buy"), ("SELL", "sell"), ("ফিল্টার ছাড়া", "unfiltered")):
        print(line(name, out[key]))
    for label, key in (("Confidence অনুযায়ী (সব)", "by_conf"), ("Confidence অনুযায়ী (BUY)", "by_conf_buy"), ("Confidence অনুযায়ী (SELL)", "by_conf_sell")):
        print(f"-- {label} --")
        for x in out[key]:
            print("  " + line(x["bucket"], x))
    print("-- কয়েন অনুযায়ী --")
    for x in out["by_coin"]:
        print("  " + line(x["coin"], x))
    print("\nফলাফল সেভ হয়েছে: docs/data/backtest.json (ওয়েবসাইটের সিগনাল পেজে দেখাবে)")

if __name__ == "__main__":
    run()
