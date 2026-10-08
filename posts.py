# -*- coding: utf-8 -*-
"""BEWON channel posts in the style the owner asked for:
  1) Daily Market Digest — every coin with price, 24h change, 24h range and volume
  2) Liquidations card — a picture with 1h / 4h / 12h / 24h long & short liquidations (+ alert on big hours)
  3) Weekly recap — honest win/loss record of the week
All English (global channel). Data sources are public and named in every post."""
import io, json, os, time
from datetime import datetime, timezone, timedelta

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data")
LIQ_EVERY_H = 4            # liquidation card every 4 hours
LIQ_ALERT_X = 3.0          # alert when the last hour is 3x the 24h hourly average ...
LIQ_ALERT_MIN = 3_000_000  # ... and at least $3M
LIQ_COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "SUI", "LTC", "DOT", "NEAR", "AAVE", "UNI", "PEPE", "ONDO", "POL"]
SIGN = "— BEWON Signal Assistant"
DISC = "This is an automated summary of public market data for informational purposes only — not financial advice, and no profit is guaranteed."


def _m(v):
    v = float(v)
    return f"${v/1e9:.2f}B" if v >= 1e9 else f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.1f}K" if v >= 1e3 else f"${v:.0f}"


def _p(v):
    v = float(v)
    if v >= 1000:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:.2f}"
    if v >= 0.01:
        return f"${v:.6f}"
    return f"${v:.8f}".rstrip("0")


# ------------------------------------------------------------------ 1. daily market digest
def market_digest(http, coins, site_url, fear_greed=None, blog_link=None):
    syms = json.dumps([c + "USDT" for c in coins], separators=(",", ":"))
    r = http.get("https://data-api.binance.vision/api/v3/ticker/24hr", params={"symbols": syms}, timeout=20)
    r.raise_for_status()
    rows = {x["symbol"][:-4]: x for x in r.json()}
    lines, up, down = [], 0, 0
    for c in coins:
        x = rows.get(c)
        if not x:
            continue
        ch = float(x["priceChangePercent"])
        up, down = (up + 1, down) if ch >= 0 else (up, down + 1)
        lines.append(f"{c}/USDT: {_p(x['lastPrice'])} {'▲' if ch >= 0 else '▼'} {ch:+.2f}% "
                     f"(24h range {_p(x['lowPrice'])}–{_p(x['highPrice'])}, vol {_m(x['quoteVolume'])})")
    if not lines:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mood = "mostly green" if up > down else "mostly red" if down > up else "evenly split"
    out = [f"📊 <b>Daily Market Digest — {day}</b>", "",
           f"Daily market digest — {day}. The watchlist is {mood} over the last 24 hours ({up} up, {down} down).", ""]
    out += lines
    if fear_greed and fear_greed.get("value") is not None:
        out += ["", f"Fear &amp; Greed: {fear_greed['value']} ({fear_greed.get('label', '')})"]
    out += ["", DISC, "", f"🔗 {'Full digest' if blog_link else 'All markets'}: {blog_link or site_url + '#/market'}", "", SIGN]
    return "\n".join(out)


# ------------------------------------------------------------------ 2. liquidations
def _gate_liq(http, coin):
    r = http.get("https://api.gateio.ws/api/v4/futures/usdt/contract_stats",
                 params={"contract": f"{coin}_USDT", "interval": "1h", "limit": 25}, timeout=15)
    r.raise_for_status()
    rows = sorted(r.json(), key=lambda x: x.get("time", 0))
    out = []
    for x in rows:
        if "long_liq_usd" not in x and "short_liq_usd" not in x:
            raise ValueError("no liquidation fields: " + ",".join(list(x)[:12]))
        out.append((int(x.get("time", 0)), float(x.get("long_liq_usd") or 0), float(x.get("short_liq_usd") or 0)))
    return out


def liquidations(http):
    """Sums Gate.io USDT-futures liquidations for the watched coins over 1h/4h/12h/24h."""
    hours, ok = {}, []
    for c in LIQ_COINS:
        try:
            for t, lg, sh in _gate_liq(http, c):
                a = hours.setdefault(t, [0.0, 0.0])
                a[0] += lg
                a[1] += sh
            ok.append(c)
        except Exception as e:
            print("liq", c, str(e)[:70])
        time.sleep(0.15)
    if not hours:
        return None
    ts = sorted(hours)
    # the newest bucket is the hour still running; use completed hours
    done = ts[:-1] if len(ts) > 1 else ts
    def win(n):
        sel = done[-n:]
        lg = sum(hours[t][0] for t in sel)
        sh = sum(hours[t][1] for t in sel)
        return {"total": lg + sh, "long": lg, "short": sh}
    res = {"h1": win(1), "h4": win(4), "h12": win(12), "h24": win(24), "coins": ok,
           "hour": datetime.fromtimestamp(done[-1], timezone.utc).isoformat(), "source": "Gate.io USDT futures"}
    return res


def liq_card(L):
    """PNG card in the classic 2x2 'Total Liquidations' layout (own design, BEWON colours)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1080, 760
    im = Image.new("RGB", (W, H), "#0B0E11")
    d = ImageDraw.Draw(im)
    def font(sz, bold=False):
        for p in (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else []) + ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
        return ImageFont.load_default()
    d.text((48, 40), "Total Liquidations", font=font(46, True), fill="#EAECEF")
    d.text((48, 100), f"{len(L['coins'])} coins · {L['source']} · {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC", font=font(22), fill="#848E9C")
    d.rounded_rectangle((W - 230, 44, W - 48, 96), 14, fill="#F0B90B")
    d.text((W - 210, 54), "BEWON", font=font(30, True), fill="#0B0E11")
    boxes = [("1h Rekt", L["h1"]), ("4h Rekt", L["h4"]), ("12h Rekt", L["h12"]), ("24h Rekt", L["h24"])]
    for i, (name, v) in enumerate(boxes):
        x0 = 48 + (i % 2) * 504
        y0 = 160 + (i // 2) * 280
        d.rounded_rectangle((x0, y0, x0 + 480, y0 + 256), 22, fill="#181A20", outline="#2B3139", width=2)
        d.text((x0 + 30, y0 + 28), name, font=font(30, True), fill="#EAECEF")
        d.text((x0 + 450, y0 + 28), _m(v["total"]), font=font(30, True), fill="#F0B90B", anchor="ra")
        d.text((x0 + 30, y0 + 110), "Long", font=font(28), fill="#848E9C")
        d.text((x0 + 450, y0 + 110), _m(v["long"]), font=font(30, True), fill="#0ECB81", anchor="ra")
        d.text((x0 + 30, y0 + 180), "Short", font=font(28), fill="#848E9C")
        d.text((x0 + 450, y0 + 180), _m(v["short"]), font=font(30, True), fill="#F6465D", anchor="ra")
    d.text((48, H - 40), "Informational only — not financial advice.", font=font(20), fill="#848E9C")
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def liq_caption(L, alert, site_url):
    h1 = L["h1"]
    side = "LONG" if h1["long"] >= h1["short"] else "SHORT"
    head = (f"💥 <b>1h {_m(h1['total'])} {side} liquidated</b>" if alert else
            f"📉 <b>Liquidations update</b> — 1h {_m(h1['total'])}, 24h {_m(L['h24']['total'])}")
    return (f"{head}\n\n"
            f"1h: long {_m(h1['long'])} · short {_m(h1['short'])}\n"
            f"24h: long {_m(L['h24']['long'])} · short {_m(L['h24']['short'])}\n\n"
            f"Source: {L['source']}, {len(L['coins'])} major coins (one exchange, not the whole market).\n"
            f"Large long liquidations mean leveraged buyers were forced out; large short liquidations mean sellers were.\n\n"
            f"🔗 {site_url}#/learn/insights\n\n{SIGN}")


def send_photo(http, token, chat_id, png, caption):
    if not token or not chat_id:
        print("---- photo (Telegram not set) ----\n" + caption)
        return True
    try:
        r = http.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                      data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
                      files={"photo": ("liquidations.png", png, "image/png")}, timeout=30)
        if r.ok:
            return True
        print("Telegram photo error:", r.text[:200])
    except Exception as e:
        print("Telegram photo error:", e)
    return False


def run_liquidations(state, http, token, chat_id, site_url):
    now = datetime.now(timezone.utc)
    last = state.get("liq_time")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < 50 * 60:
        return                      # check at most once an hour
    state["liq_time"] = now.isoformat(timespec="seconds")
    L = liquidations(http)
    if not L:
        return
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "liquidations.json"), "w", encoding="utf-8") as f:
        json.dump(dict(L, updated=now.isoformat(timespec="seconds")), f, indent=1)
    avg = L["h24"]["total"] / 24 if L["h24"]["total"] else 0
    alert = L["h1"]["total"] >= LIQ_ALERT_MIN and avg and L["h1"]["total"] >= LIQ_ALERT_X * avg and state.get("liq_alert_hour") != L["hour"]
    due = now.hour % LIQ_EVERY_H == 0 and state.get("liq_post_hour") != now.strftime("%Y-%m-%d %H")
    if not (alert or due):
        return
    try:
        png = liq_card(L)
    except Exception as e:
        print("liq card error:", str(e)[:80])
        return
    if send_photo(http, token, chat_id, png, liq_caption(L, alert, site_url)):
        if alert:
            state["liq_alert_hour"] = L["hour"]
        state["liq_post_hour"] = now.strftime("%Y-%m-%d %H")


# ------------------------------------------------------------------ 3. weekly recap
def weekly_recap(state, site_url):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    closed = [t for t in state.get("history", []) if t.get("closed") and datetime.fromisoformat(t["closed"]) >= week_ago]
    tp = sum(1 for t in closed if str(t.get("result", "")).startswith("TP"))
    sl = sum(1 for t in closed if t.get("result") == "SL")
    ex = sum(1 for t in closed if t.get("result") == "EXPIRED")
    other = len(closed) - tp - sl - ex
    wr = f"{tp * 100 / (tp + sl):.0f}%" if tp + sl else "—"
    rows = [f"{'✅' if str(t.get('result','')).startswith('TP') else '❌' if t.get('result') == 'SL' else '⏳'} {t['coin']} {t['side']} — {t.get('result')}"
            for t in closed[:12]]
    return "\n".join([f"🗓 <b>Weekly recap — {week_ago:%d %b} to {now:%d %b %Y}</b>", "",
                      f"Closed signals: {len(closed)}", f"Target hit: {tp} · Stop hit: {sl} · Expired: {ex}" + (f" · Closed by hand: {other}" if other else ""),
                      f"Win rate this week: {wr}", ""] + (rows or ["No signal closed this week."]) +
                     ["", "Every result is counted — wins and losses. Past results do not promise future results.",
                      f"🔗 Full record: {site_url}#/signals", "", SIGN])


# ------------------------------------------------------------------ 4. promo video (posted once per version)
PROMO_V = "2026-10-09"
PROMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "promo.mp4")


def run_promo(state, http, token, chat_id, site_url):
    if state.get("promo_v") == PROMO_V or not os.path.exists(PROMO_FILE):
        return
    cap = ("🎬 <b>How BEWON works — in 46 seconds</b>\n\n"
           "1️⃣ Join this channel for free signals\n2️⃣ Open the website — no login needed\n3️⃣ Read every signal and its result\n"
           "4️⃣ Practise with play money\n5️⃣ Let the auto bot trade (practice)\n6️⃣ Learn to earn online\n\n"
           f"🌐 {site_url}\n\nNo fees · No deposits · Not financial advice.\n\n{SIGN}")
    if not token or not chat_id:
        print("---- promo video (Telegram not set) ----")
        state["promo_v"] = PROMO_V
        return
    try:
        with open(PROMO_FILE, "rb") as f:
            r = http.post(f"https://api.telegram.org/bot{token}/sendVideo",
                          data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML", "supports_streaming": "true", "width": 1080, "height": 1920},
                          files={"video": ("BEWON_Promo.mp4", f, "video/mp4")}, timeout=120)
        if r.ok:
            state["promo_v"] = PROMO_V
        else:
            print("promo video error:", r.text[:200])
    except Exception as e:
        print("promo video error:", e)
