# -*- coding: utf-8 -*-
"""BEWON Daily Global Picks — once a day the bot asks several outside sources about every coin
and forex pair it watches, combines their answers, and publishes the few markets where the
sources agree most. Each pick gets Entry / TP / SL and its result is tracked in the open.

Sources: TradingView technical ratings (1h, 4h, 1D), BEWON engine (1h chart), price momentum
(24h and 7d), Gate.io trader positioning (contrarian), CoinGecko community votes (when cached).
Output: docs/data/daily.json and one Telegram post per day.
"""
import os, json, time, html
from datetime import datetime, timezone, timedelta

import extras

HOUR_UTC = 6                 # 6 UTC = দুপুর ১২টা ঢাকা, সকাল ৭টা লন্ডন
MAX_BUY, MAX_SELL, MAX_FX = 3, 2, 2
MIN_AGREE = 3                # কমপক্ষে কয়টা উৎস একই দিকে
BUY_SCORE, SELL_SCORE = 62, 38
SL_ATR, TP1_ATR, TP2_ATR = 1.5, 1.5, 3.0
EXPIRE_H = 48
TV_FX = {"EURUSD": "FX_IDC:EURUSD", "GBPUSD": "FX_IDC:GBPUSD", "USDJPY": "FX_IDC:USDJPY", "AUDUSD": "FX_IDC:AUDUSD",
         "USDCAD": "FX_IDC:USDCAD", "USDCHF": "FX_IDC:USDCHF", "NZDUSD": "FX_IDC:NZDUSD", "EURJPY": "FX_IDC:EURJPY",
         "GBPJPY": "FX_IDC:GBPJPY", "XAUUSD": "OANDA:XAUUSD", "XAGUSD": "OANDA:XAGUSD"}
WEIGHTS = {"tv1h": 1.0, "tv4h": 1.2, "tv1d": 1.0, "engine": 1.2, "mom": 0.8, "sent": 0.5, "crowd": 0.4}
SRC_NAMES = {"tv1h": "TradingView 1h", "tv4h": "TradingView 4h", "tv1d": "TradingView 1D", "engine": "BEWON engine",
             "mom": "Price momentum", "sent": "CoinGecko community", "crowd": "Gate.io traders"}


def _now():
    return datetime.now(timezone.utc)


def tv_ratings(http, tickers):
    """{ticker: {tv1h, tv4h, tv1d}} from TradingView's public scanner (any market)."""
    body = {"symbols": {"tickers": tickers, "query": {"types": []}},
            "columns": ["Recommend.All|60", "Recommend.All|240", "Recommend.All"]}
    r = http.post("https://scanner.tradingview.com/global/scan", json=body, headers=extras.UA, timeout=25)
    r.raise_for_status()
    out = {}
    for row in r.json().get("data", []):
        v = [x for x in row.get("d", []) if isinstance(x, (int, float))]
        if len(v) == 3:
            out[row["s"]] = {"tv1h": round(v[0], 3), "tv4h": round(v[1], 3), "tv1d": round(v[2], 3)}
    return out


def momentum(df):
    c = df["close"]
    ch24 = (c.iloc[-1] / c.iloc[-25] - 1) * 100 if len(c) > 25 else 0
    ch7 = (c.iloc[-1] / c.iloc[-169] - 1) * 100 if len(c) > 169 else ch24
    return round(extras._clamp(ch24 / 6.0 * 0.5 + ch7 / 15.0 * 0.5), 3), round(ch24, 2)


def score_of(s):
    parts = [(k, s[k]) for k in WEIGHTS if isinstance(s.get(k), (int, float))]
    if not parts:
        return None
    v = sum(WEIGHTS[k] * x for k, x in parts) / sum(WEIGHTS[k] for k, _ in parts)
    return {"score": round(50 + 50 * v), "agree_buy": sum(1 for _, x in parts if x > 0.1),
            "agree_sell": sum(1 for _, x in parts if x < -0.1), "n": len(parts)}


def make_pick(sym, market, side, df, s, sc):
    c = df.iloc[-1]
    price, atr = float(c.close), float(c.atr)
    d = 1 if side == "BUY" else -1
    agree = sc["agree_buy"] if side == "BUY" else sc["agree_sell"]
    return {"coin": sym, "market": market, "side": side, "entry": price,
            "sl": price - d * SL_ATR * atr, "tp1": price + d * TP1_ATR * atr, "tp2": price + d * TP2_ATR * atr,
            "score": sc["score"], "agree": agree, "n": sc["n"], "src": s, "opened": _now().isoformat(timespec="seconds"),
            "status": "open"}


def build(state, http, frames, coins, fx_pairs, get_fx_df):
    rows = []
    tv = {}
    try:
        tv = tv_ratings(http, [f"BINANCE:{c}USDT" for c in coins] + [TV_FX[p] for p in fx_pairs if p in TV_FX])
    except Exception as e:
        print("daily: tradingview error", str(e)[:80])
    sent_cache = state.get("sent_cache", {})
    for c in coins:
        df = frames.get(c)
        if df is None or len(df) < 60:
            continue
        s = dict(tv.get(f"BINANCE:{c}USDT", {}))
        s.update(extras.src_engine(df))
        s["mom"], ch = momentum(df)
        if c in sent_cache:
            s.update(sent_cache[c])
        try:
            x = extras.src_gate_crowd(http, c)
            if x:
                s.update(x)
        except Exception:
            pass
        sc = score_of(s)
        if sc:
            rows.append(("crypto", c, df, s, sc, ch))
        time.sleep(0.15)
    for p in fx_pairs:
        try:
            df = get_fx_df(p)
        except Exception as e:
            print("daily: fx", p, str(e)[:50])
            continue
        s = dict(tv.get(TV_FX.get(p, ""), {}))
        s.update(extras.src_engine(df))
        s["mom"], ch = momentum(df)
        sc = score_of(s)
        if sc:
            rows.append(("forex", p, df, s, sc, ch))
        time.sleep(0.3)
    open_now = {t["coin"] for t in state.get("open", [])}
    buys = sorted([r for r in rows if r[0] == "crypto" and r[4]["score"] >= BUY_SCORE and r[4]["agree_buy"] >= MIN_AGREE and r[4]["agree_sell"] <= 1],
                  key=lambda r: -r[4]["score"])[:MAX_BUY]
    sells = sorted([r for r in rows if r[0] == "crypto" and r[4]["score"] <= SELL_SCORE and r[4]["agree_sell"] >= MIN_AGREE and r[4]["agree_buy"] <= 1],
                   key=lambda r: r[4]["score"])[:MAX_SELL]
    fx = sorted([r for r in rows if r[0] == "forex" and (r[4]["score"] >= BUY_SCORE and r[4]["agree_buy"] >= MIN_AGREE or r[4]["score"] <= SELL_SCORE and r[4]["agree_sell"] >= MIN_AGREE)],
                key=lambda r: -abs(r[4]["score"] - 50))[:MAX_FX]
    picks = []
    for r in buys + sells + fx:
        side = "BUY" if r[4]["score"] >= 50 else "SELL"
        p = make_pick(r[1], r[0], side, r[2], r[3], r[4])
        p["also_bot"] = r[1] in open_now
        picks.append(p)
    board = sorted([{"c": r[1], "m": r[0], "score": r[4]["score"], "buy": r[4]["agree_buy"], "sell": r[4]["agree_sell"], "n": r[4]["n"], "ch24": r[5]} for r in rows],
                   key=lambda x: -x["score"])
    return picks, board


def track(state, frames, get_fx_df):
    """TP / SL / expiry for earlier picks, using 1-hour candles since each pick opened."""
    dp = state.setdefault("daily_picks", {"open": [], "history": [], "stats": {"tp1": 0, "tp2": 0, "sl": 0, "expired": 0}})
    still = []
    for t in dp["open"]:
        try:
            df = frames.get(t["coin"]) if t["market"] == "crypto" else get_fx_df(t["coin"])
        except Exception:
            df = None
        if df is None:
            still.append(t)
            continue
        opened = datetime.fromisoformat(t["opened"])
        seg = df[df["time"] > opened]
        buy = t["side"] == "BUY"
        res = None
        for _, c in seg.iterrows():
            hi, lo = float(c.high), float(c.low)
            if (lo <= t["sl"]) if buy else (hi >= t["sl"]):
                res = "TP1" if t.get("tp1_hit") else "SL"
                break
            if not t.get("tp1_hit") and ((hi >= t["tp1"]) if buy else (lo <= t["tp1"])):
                t["tp1_hit"] = True
                t["sl"] = t["entry"]            # TP1-এর পর স্টপ এন্ট্রিতে
            if (hi >= t["tp2"]) if buy else (lo <= t["tp2"]):
                res = "TP2"
                break
        if not res and _now() - opened > timedelta(hours=EXPIRE_H):
            res = "TP1" if t.get("tp1_hit") else "EXPIRED"
        if res:
            t["status"], t["closed"] = res, _now().isoformat(timespec="seconds")
            t["exit"] = float(seg["close"].iloc[-1]) if len(seg) else t["entry"]
            t.pop("src", None)
            dp["history"].insert(0, t)
            dp["stats"][{"TP1": "tp1", "TP2": "tp2", "SL": "sl", "EXPIRED": "expired"}[res]] += 1
        else:
            still.append(t)
    dp["open"] = still
    dp["history"] = dp["history"][:120]
    return dp


def fmt(x, sym):
    if sym.startswith("XAU"):
        return f"{x:,.2f}"
    if "JPY" in sym or sym.startswith("XAG"):
        return f"{x:,.3f}"
    if len(sym) == 6 and sym.isalpha() and sym in TV_FX:
        return f"{x:,.5f}"
    return f"{x:,.2f}" if x >= 100 else f"{x:,.4f}" if x >= 1 else f"{x:.8f}" if x < 0.01 else f"{x:.6f}"


def message(picks, dp, site_url, fear_greed, n_markets):
    st = dp["stats"]
    won, lost = st["tp1"] + st["tp2"], st["sl"]
    rec = f"{won} target · {lost} stop · {st['expired']} expired" if won + lost + st["expired"] else "first day — no results yet"
    lines = [f"🌍 <b>BEWON Daily Global Picks</b> — {_now():%d %b %Y}",
             f"{n_markets} markets checked with several global sources (TradingView 1h/4h/1D, BEWON engine, momentum, Gate.io traders, CoinGecko community)."]
    if fear_greed:
        lines.append(f"😶 Fear &amp; Greed: {fear_greed.get('value')} ({html.escape(str(fear_greed.get('label')))})")
    lines.append("")
    if not picks:
        lines.append("Today the sources do not agree strongly on any market. <b>No pick is the pick</b> — waiting is also a trade.")
    for p in picks:
        nm = p["coin"] + ("/USDT" if p["market"] == "crypto" else "")
        icon = "🟢" if p["side"] == "BUY" else "🔴"
        lines += [f"{icon} <b>{nm} {p['side']}</b> · score {p['score']}/100 · {p['agree']}/{p['n']} sources agree",
                  f"   Entry {fmt(p['entry'], p['coin'])} · TP1 {fmt(p['tp1'], p['coin'])} · TP2 {fmt(p['tp2'], p['coin'])} · SL {fmt(p['sl'], p['coin'])}"]
        if p["market"] == "crypto" and p["side"] == "SELL":
            lines.append("   (SELL = futures short, or avoid buying)")
    last = dp["history"][:5]
    if last:
        lines += ["", "📊 <b>Recent results</b>"] + [f"{'✅' if t['status'] in ('TP1', 'TP2') else '❌' if t['status'] == 'SL' else '⏳'} {t['coin']} {t['side']} → {t['status']}" for t in last]
    lines += ["", f"📒 Daily picks record: {rec}", f"🌐 {site_url}#/daily", "",
              "Not financial advice. Sources can all be wrong at the same time. Use a stop loss and small size."]
    return "\n".join(lines)


def run(state, http, frames, coins, fx_pairs, get_fx_df, send, site_url, fear_greed=None, force=False):
    dp = track(state, frames, get_fx_df)
    now = _now()
    today = now.strftime("%Y-%m-%d")
    if (state.get("daily_picks_day") == today or now.hour < HOUR_UTC) and not force:
        _publish(dp, state)
        return
    state["daily_picks_day"] = today
    picks, board = build(state, http, frames, coins, fx_pairs, get_fx_df)
    have = {(t["coin"], t["side"]) for t in dp["open"]}
    new = [p for p in picks if (p["coin"], p["side"]) not in have]
    dp["open"] = dp["open"] + json.loads(json.dumps(new))
    dp["today"] = {"date": today, "picks": json.loads(json.dumps(picks)), "board": board[:60], "n": len(board)}
    _publish(dp, state)
    try:
        send(message(picks, dp, site_url, fear_greed, len(board)))
    except Exception as e:
        print("daily: send error", str(e)[:80])
    print(f"daily picks: {len(picks)} picks from {len(board)} markets")


def _publish(dp, state):
    extras._write("daily.json", {"today": dp.get("today"), "open": dp["open"], "history": dp["history"][:60], "stats": dp["stats"],
                                 "sources": list(SRC_NAMES.values()),
                                 "rules": {"buy_score": BUY_SCORE, "sell_score": SELL_SCORE, "min_agree": MIN_AGREE,
                                           "sl_atr": SL_ATR, "tp1_atr": TP1_ATR, "tp2_atr": TP2_ATR, "expire_h": EXPIRE_H, "hour_utc": HOUR_UTC}})
