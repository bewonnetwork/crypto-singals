# -*- coding: utf-8 -*-
"""
BEWON সিগনাল ল্যাব
-------------------
অনেকগুলো আলাদা নিয়ম (কৌশল) গত ২ বছরের দামে পরীক্ষা করে দেখে কোনটা সত্যিই কাজ করে।
নিজেকে ঠকানো এড়াতে সময়টা দুই ভাগে ভাগ করা হয়:
  - শেখার অংশ (প্রথম ~১৬ মাস)
  - যাচাইয়ের অংশ (শেষ ~৮ মাস) — এখানে ভালো না করলে সেই নিয়ম বাদ
ফলাফল: docs/data/lab.json   চালানো: python signal_bot.py --lab
কোনো Telegram মেসেজ যায় না, লাইভ সিগনালের নিয়মও এটা বদলায় না।
"""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import backtest as bt
import signal_bot as b

LAB_VERSION = 1
FEE = 0.001
TEST_FRACTION = 1 / 3            # শেষ এক-তৃতীয়াংশ সময় যাচাইয়ের জন্য আলাদা রাখা
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "lab.json")


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def indicators(df):
    d = df.copy()
    c, h, l = d.close, d.high, d.low
    d["e20"], d["e50"], d["e200"] = ema(c, 20), ema(c, 50), ema(c, 200)
    d["e9"], d["e21"] = ema(c, 9), ema(c, 21)
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdm = (h.diff()).where((h.diff() > -l.diff()) & (h.diff() > 0), 0.0)
    mdm = (-l.diff()).where((-l.diff() > h.diff()) & (-l.diff() > 0), 0.0)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    d["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    d["hh20"], d["ll20"] = h.rolling(20).max().shift(), l.rolling(20).min().shift()
    d["vavg"] = d.volume.rolling(20).mean()
    return d


def to_tf(df, tf):
    if tf == "1h":
        return df
    g = df.set_index("time").resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return g.reset_index().iloc[:-1]


def daily_trend(df):
    """প্রতিটা ক্যান্ডেলের জন্য শেষ বন্ধ হওয়া দৈনিক ট্রেন্ড (+1/-1/0)"""
    dd = df.set_index("time").resample("1D").agg({"close": "last"}).dropna()
    e20, e50 = ema(dd.close, 20), ema(dd.close, 50)
    t = pd.Series(0, index=dd.index)
    t[(dd.close > e20) & (e20 > e50)] = 1
    t[(dd.close < e20) & (e20 < e50)] = -1
    t.index = t.index + pd.Timedelta(days=1)
    return t.reindex(df["time"], method="ffill").fillna(0).astype(int).values


def entries(d, kind):
    """ঢোকার সংকেত: +1 = BUY, -1 = SELL, 0 = কিছু না"""
    s = pd.Series(0, index=d.index)
    if kind == "cross":                      # এখনকার লাইভ নিয়মের কাছাকাছি: EMA 9/21 ক্রস
        s[(d.e9.shift() <= d.e21.shift()) & (d.e9 > d.e21) & (d.rsi.between(45, 70)) & (d.volume > d.vavg)] = 1
        s[(d.e9.shift() >= d.e21.shift()) & (d.e9 < d.e21) & (d.rsi.between(30, 55)) & (d.volume > d.vavg)] = -1
    elif kind == "pullback":                 # ট্রেন্ডের দিকে, দাম একটু নেমে আবার ঘুরলে
        upt, dnt = (d.e50 > d.e200) & (d.close > d.e200), (d.e50 < d.e200) & (d.close < d.e200)
        s[upt & (d.rsi.shift() < 42) & (d.rsi >= 42) & (d.close > d.open)] = 1
        s[dnt & (d.rsi.shift() > 58) & (d.rsi <= 58) & (d.close < d.open)] = -1
    elif kind == "breakout":                 # ২০ ক্যান্ডেলের সর্বোচ্চ/সর্বনিম্ন ভাঙলে, ট্রেন্ড শক্তিশালী থাকলে
        s[(d.close > d.hh20) & (d.adx > 22) & (d.close > d.e50) & (d.volume > d.vavg)] = 1
        s[(d.close < d.ll20) & (d.adx > 22) & (d.close < d.e50) & (d.volume > d.vavg)] = -1
    elif kind == "ema20":                    # ট্রেন্ডে EMA 20 ছুঁয়ে ফিরে আসা
        upt, dnt = (d.e20 > d.e50) & (d.e50 > d.e200), (d.e20 < d.e50) & (d.e50 < d.e200)
        s[upt & (d.low <= d.e20) & (d.close > d.e20) & (d.close > d.open)] = 1
        s[dnt & (d.high >= d.e20) & (d.close < d.e20) & (d.close < d.open)] = -1
    return s.values


EXITS = {  # নাম: (SL কত ATR, লক্ষ্য কত R, ১R-এ SL Entry-তে আনা হবে?, সর্বোচ্চ কত ক্যান্ডেল)
    "tp2R": (1.5, 2.0, False, 72),
    "tp3R": (2.0, 3.0, False, 96),
    "tp2R-be": (1.5, 2.0, True, 72),
    "tp1.5R": (2.0, 1.5, False, 48),
}


def simulate(d, sig, trend, side_mode, use_trend, ex):
    sl_atr, tp_r, be, max_bars = EXITS[ex]
    H, L, C, O, A = d.high.values, d.low.values, d.close.values, d.open.values, d.atr.values
    T = d.time.values
    out, busy = [], -1
    n = len(d)
    for i in np.nonzero(sig)[0]:
        if i < 210 or i <= busy or i + 2 >= n:
            continue
        side = int(sig[i])
        if side_mode == "buy" and side < 0:
            continue
        if use_trend and trend[i] != side:
            continue
        entry = O[i + 1]                         # পরের ক্যান্ডেলের শুরুতে ঢোকা (আগে থেকে জানা যায় না এমন কিছু ব্যবহার হয় না)
        risk = sl_atr * A[i]
        if not risk > 0 or not entry > 0:
            continue
        sl, tp = entry - side * risk, entry + side * tp_r * risk
        r, j, moved = None, i + 1, False
        for j in range(i + 1, min(i + 1 + max_bars, n)):
            hit_sl = L[j] <= sl if side > 0 else H[j] >= sl
            hit_tp = H[j] >= tp if side > 0 else L[j] <= tp
            if hit_sl:                           # একই ক্যান্ডেলে দুটোই হলে খারাপটা ধরা হয়
                r = 0.0 if moved else -1.0
                break
            if hit_tp:
                r = tp_r
                break
            if be and not moved and ((H[j] - entry) if side > 0 else (entry - L[j])) >= risk:
                moved, sl = True, entry
        if r is None:
            r = (C[j] - entry) * side / risk
        r -= 2 * FEE * entry / risk
        busy = j
        out.append((T[i], side, round(float(r), 3)))
    return out


def stats(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "avg_r": 0, "total_r": 0, "win": 0, "pf": 0, "dd": 0}
    eq = peak = dd = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gp, gl = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return {"n": n, "avg_r": round(sum(rs) / n, 3), "total_r": round(sum(rs), 1),
            "win": round(sum(1 for x in rs if x > 0) * 100 / n, 1), "pf": round(gp / gl, 2) if gl else 0, "dd": round(dd, 1)}


def run(data=None):
    hours = bt.YEARS * 365 * 24
    if data is None:
        data = {}
        for coin in b.COINS:
            try:
                data[coin] = bt.history(coin, hours + 300)
            except Exception as e:
                print("FAIL", coin, str(e)[:80])
    if not data:
        raise SystemExit("ডেটা আসেনি")
    t0 = min(d.time.iloc[0] for d in data.values())
    t1 = max(d.time.iloc[-1] for d in data.values())
    split = np.datetime64((t0 + (t1 - t0) * (1 - TEST_FRACTION)).to_datetime64())
    frames = {}
    for tf in ("1h", "4h"):
        for coin, df in data.items():
            d = indicators(to_tf(df, tf)).reset_index(drop=True)
            frames[(tf, coin)] = (d, daily_trend(d))
    rows = []
    for tf in ("1h", "4h"):
        for kind in ("cross", "pullback", "breakout", "ema20"):
            sigs = {coin: entries(frames[(tf, coin)][0], kind) for coin in data}
            for side_mode in ("both", "buy"):
                for use_trend in (False, True):
                    for ex in EXITS:
                        tr_all = []
                        per_coin = {}
                        for coin in data:
                            d, trend = frames[(tf, coin)]
                            res = simulate(d, sigs[coin], trend, side_mode, use_trend, ex)
                            tr_all += res
                            per_coin[coin] = round(sum(x[2] for x in res), 1)
                        tr_all.sort(key=lambda x: x[0])
                        train = [x[2] for x in tr_all if x[0] < split]
                        test = [x[2] for x in tr_all if x[0] >= split]
                        rows.append({"tf": tf, "entry": kind, "side": side_mode, "trend": use_trend, "exit": ex,
                                     "train": stats(train), "test": stats(test), "all": stats(train + test),
                                     "coins_plus": sum(1 for v in per_coin.values() if v > 0), "per_coin": per_coin})
    # ভালো মানে: দুই অংশেই লাভ, যথেষ্ট সংখ্যক ট্রেড, আর বেশিরভাগ কয়েনে লাভ
    for r in rows:
        r["ok"] = bool(r["train"]["avg_r"] >= 0.08 and r["test"]["avg_r"] >= 0.08 and r["train"]["n"] >= 150
                       and r["test"]["n"] >= 80 and r["train"]["pf"] >= 1.15 and r["test"]["pf"] >= 1.15
                       and r["coins_plus"] >= max(1, int(len(data) * 0.7)))
    rows.sort(key=lambda r: (r["ok"], min(r["train"]["avg_r"], r["test"]["avg_r"])), reverse=True)
    out = {"version": LAB_VERSION, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "from": str(t0)[:10], "to": str(t1)[:10], "split": str(split)[:10], "coins": list(data), "fee_pct": FEE * 100,
           "tested": len(rows), "passed": sum(1 for r in rows if r["ok"]), "results": rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("===== SIGNAL LAB =====")
    print(f"{out['from']} → {out['to']} · যাচাই শুরু {out['split']} · {len(rows)} নিয়ম পরীক্ষা · পাস {out['passed']}")
    for r in rows[:15]:
        print(f"{'PASS' if r['ok'] else '    '} {r['tf']:<3} {r['entry']:<9} {r['side']:<4} trend={int(r['trend'])} {r['exit']:<8} "
              f"train n={r['train']['n']:<4} avg={r['train']['avg_r']:+.3f} | test n={r['test']['n']:<4} avg={r['test']['avg_r']:+.3f} PF={r['test']['pf']} | coins+ {r['coins_plus']}")
    return out


if __name__ == "__main__":
    run()
