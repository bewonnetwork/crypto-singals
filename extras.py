# -*- coding: utf-8 -*-
"""BEWON extras: (1) multi-source consensus for the top-20 coins, (2) remote-job feed for the
Earn-online tools, (3) video feed from YouTube channels. Everything writes small public JSON
files in docs/data/ that the website reads. Every source is optional: if one fails, the rest still work."""
import json, os, re, time, html
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data")
CONSENSUS_EVERY_MIN = 60
JOBS_EVERY_MIN = 360
VIDEOS_EVERY_MIN = 360

STABLE = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDS", "PYUSD", "BUSD", "USD1", "USDD", "USDP", "GUSD", "FRAX", "USDTB", "BSC-USD", "USDX", "EURC", "RLUSD"}
WRAPPED = {"WBTC", "WETH", "STETH", "WSTETH", "WEETH", "CBBTC", "WBETH", "RETH", "METH", "EZETH", "SOLVBTC", "LBTC", "JITOSOL", "MSOL", "BNSOL", "WBNB", "BTCB", "XAUT", "PAXG", "LEO", "FIGR_HELOC"}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _now():
    return datetime.now(timezone.utc)


def _due(state, key, minutes):
    last = state.get(key)
    try:
        return not last or (_now() - datetime.fromisoformat(last)).total_seconds() >= minutes * 60
    except Exception:
        return True


def _write(name, payload):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        old.pop("updated", None)
        if old == json.loads(json.dumps(payload)):
            return False
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    payload = dict(payload, updated=_now().isoformat(timespec="seconds"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return True


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


# =============================== 1. consensus for the top-20 coins ===============================
def top20(http):
    """All-time top coins by market cap (stablecoins and wrapped tokens removed) that trade against USDT."""
    r = http.get("https://api.coingecko.com/api/v3/coins/markets", params={
        "vs_currency": "usd", "order": "market_cap_desc", "per_page": 80, "page": 1,
        "price_change_percentage": "24h,7d"}, headers=UA, timeout=20)
    r.raise_for_status()
    pairs = set()
    try:
        t = http.get("https://data-api.binance.vision/api/v3/ticker/price", timeout=20).json()
        pairs = {x["symbol"][:-4] for x in t if x["symbol"].endswith("USDT")}
    except Exception as e:
        print("consensus: pair list error", str(e)[:60])
    out = []
    for c in r.json():
        s = str(c.get("symbol", "")).upper()
        if s in STABLE or s in WRAPPED or (pairs and s not in pairs):
            continue
        out.append({"c": s, "id": c["id"], "name": c.get("name", s), "rank": c.get("market_cap_rank"),
                    "ch24": c.get("price_change_percentage_24h_in_currency") or 0,
                    "ch7": c.get("price_change_percentage_7d_in_currency") or 0})
        if len(out) == 20:
            break
    return out


def src_tradingview(http, coins):
    """TradingView technical ratings (-1..1) on 1h, 4h and 1 day."""
    body = {"symbols": {"tickers": [f"BINANCE:{c}USDT" for c in coins], "query": {"types": []}},
            "columns": ["Recommend.All|60", "Recommend.All|240", "Recommend.All"]}
    r = http.post("https://scanner.tradingview.com/crypto/scan", json=body, headers=UA, timeout=20)
    r.raise_for_status()
    out = {}
    for row in r.json().get("data", []):
        c = row["s"].split(":")[1][:-4]
        v = [x for x in row.get("d", []) if isinstance(x, (int, float))]
        if len(v) == 3:
            out[c] = {"tv1h": round(v[0], 3), "tv4h": round(v[1], 3), "tv1d": round(v[2], 3)}
    return out


def src_gate_crowd(http, coin):
    """Gate.io futures long/short account ratio. Used contrarian and lightly: a very crowded side is a warning."""
    r = http.get("https://api.gateio.ws/api/v4/futures/usdt/contract_stats",
                 params={"contract": f"{coin}_USDT", "interval": "1h", "limit": 1}, headers=UA, timeout=10)
    r.raise_for_status()
    j = r.json()
    if not j:
        return None
    lsr = float(j[-1].get("lsr_account") or 0)
    if lsr <= 0:
        return None
    return {"lsr": round(lsr, 2), "crowd": round(_clamp((1.0 - lsr) / 2.0, -0.5, 0.5), 3)}


def src_sentiment(http, cid):
    r = http.get(f"https://api.coingecko.com/api/v3/coins/{cid}", params={
        "localization": "false", "tickers": "false", "market_data": "false",
        "community_data": "false", "developer_data": "false"}, headers=UA, timeout=15)
    r.raise_for_status()
    up = r.json().get("sentiment_votes_up_percentage")
    return None if up is None else {"votes_up": round(up, 1), "sent": round((up - 50) / 50, 3)}


def src_engine(df):
    """BEWON's own reading of the 1-hour chart."""
    c = df.iloc[-1]
    s = 0.0
    s += 0.35 if c.ema_fast > c.ema_slow else -0.35
    s += 0.35 if c.close > c.ema200 else -0.35
    s += 0.3 * _clamp((c.rsi - 50) / 20)
    return {"engine": round(_clamp(s), 3), "rsi": round(float(c.rsi), 1)}


WEIGHTS = {"tv1h": 1.0, "tv4h": 1.2, "tv1d": 1.0, "engine": 1.2, "mom": 0.8, "sent": 0.5, "crowd": 0.4}
NAMES = {"tv1h": "TradingView 1h", "tv4h": "TradingView 4h", "tv1d": "TradingView 1D", "engine": "BEWON engine",
         "mom": "CoinGecko momentum", "sent": "CoinGecko community", "crowd": "Gate.io traders (contrarian)"}


def label_of(score):
    return "Strong buy" if score >= 70 else "Buy" if score >= 57 else "Sell" if score <= 43 and score > 30 else "Strong sell" if score <= 30 else "Neutral"


def consensus(state, http, frames, get_df, fear_greed=None):
    if not _due(state, "consensus_time", CONSENSUS_EVERY_MIN):
        return
    state["consensus_time"] = _now().isoformat(timespec="seconds")
    try:
        coins = top20(http)
    except Exception as e:
        print("consensus: top-20 error", str(e)[:80])
        return
    syms = [c["c"] for c in coins]
    tv = {}
    try:
        tv = src_tradingview(http, syms)
    except Exception as e:
        print("consensus: tradingview error", str(e)[:60])
    sent_cache = state.setdefault("sent_cache", {})
    refresh_sent = _due(state, "sent_time", 360)
    if refresh_sent:
        state["sent_time"] = _now().isoformat(timespec="seconds")
    used, rows = set(), []
    for c in coins:
        s = dict(tv.get(c["c"], {}))
        s["mom"] = round(_clamp(c["ch24"] / 6.0 * 0.5 + c["ch7"] / 15.0 * 0.5), 3)
        try:
            df = frames.get(c["c"])
            if df is None:
                df = get_df(c["c"])
            s.update(src_engine(df))
        except Exception as e:
            print("consensus: engine", c["c"], str(e)[:50])
        if refresh_sent:
            try:
                x = src_sentiment(http, c["id"])
                if x:
                    sent_cache[c["c"]] = x
                time.sleep(2.5)
            except Exception as e:
                print("consensus: sentiment", c["c"], str(e)[:50])
        if c["c"] in sent_cache:
            s.update(sent_cache[c["c"]])
        try:
            x = src_gate_crowd(http, c["c"])
            if x:
                s.update(x)
        except Exception:
            pass
        parts = [(k, s[k]) for k in WEIGHTS if isinstance(s.get(k), (int, float))]
        if not parts:
            continue
        used |= {k for k, _ in parts}
        v = sum(WEIGHTS[k] * x for k, x in parts) / sum(WEIGHTS[k] for k, _ in parts)
        score = round(50 + 50 * v)
        agree = sum(1 for k, x in parts if x > 0.1)
        against = sum(1 for k, x in parts if x < -0.1)
        rows.append({"c": c["c"], "name": c["name"], "rank": c["rank"], "score": score, "label": label_of(score),
                     "agree": agree, "against": against, "n": len(parts), "src": s})
        time.sleep(0.2)
    rows.sort(key=lambda r: -r["score"])
    if rows:
        _write("consensus.json", {"coins": rows, "sources": [NAMES[k] for k in WEIGHTS if k in used],
                                  "fear_greed": fear_greed, "method": "Weighted average of every source that answered, from -1 (sell) to +1 (buy), shown as 0-100."})
        print(f"consensus: {len(rows)} coins, {len(used)} source types")


# =============================== 2. remote jobs for Earn online ===============================
SECTORS = [("writing", r"writ|content|copy|editor|blog|journalis"), ("design", r"design|ui|ux|graphic|illustrat|figma"),
           ("video", r"video|motion|youtube|animator|editor"), ("dev", r"develop|engineer|program|software|front|back|full.?stack|web|devops|data|python|react"),
           ("marketing", r"market|seo|social|growth|ads|ppc|community"), ("support", r"support|assistant|customer|admin|data entry|success"),
           ("translation", r"translat|transcri|locali|bilingual"), ("tutoring", r"tutor|teach|instructor|trainer|educat")]


def _sector(text):
    t = text.lower()
    for k, rx in SECTORS:
        if re.search(rx, t):
            return k
    return "other"


def _clean(s, n=140):
    s = re.sub(r"<[^>]+>", " ", html.unescape(str(s or "")))
    return re.sub(r"\s+", " ", s).strip()[:n]


def jobs(state, http):
    if not _due(state, "jobs_time", JOBS_EVERY_MIN):
        return
    state["jobs_time"] = _now().isoformat(timespec="seconds")
    out, ok = [], []

    def add(title, company, url, where, when, src, kind=""):
        if not title or not str(url).startswith("https://"):
            return
        out.append({"t": _clean(title, 110), "co": _clean(company, 60), "url": url, "geo": _clean(where or "Anywhere", 50),
                    "at": when, "src": src, "type": _clean(kind, 30), "sec": _sector(title + " " + kind)})

    try:
        j = http.get("https://remotive.com/api/remote-jobs", params={"limit": 40}, headers=UA, timeout=20).json()
        for x in j.get("jobs", [])[:40]:
            add(x.get("title"), x.get("company_name"), x.get("url"), x.get("candidate_required_location"), x.get("publication_date"), "Remotive", x.get("category", ""))
        ok.append("Remotive")
    except Exception as e:
        print("jobs: remotive", str(e)[:60])
    try:
        j = http.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 40}, headers=UA, timeout=20).json()
        for x in j.get("jobs", [])[:40]:
            add(x.get("jobTitle"), x.get("companyName"), x.get("url"), x.get("jobGeo"), x.get("pubDate"), "Jobicy", " ".join(x.get("jobIndustry") or []))
        ok.append("Jobicy")
    except Exception as e:
        print("jobs: jobicy", str(e)[:60])
    try:
        j = http.get("https://himalayas.app/jobs/api", params={"limit": 40}, headers=UA, timeout=20).json()
        for x in j.get("jobs", [])[:40]:
            ts = x.get("pubDate")
            when = datetime.fromtimestamp(int(ts), timezone.utc).isoformat() if str(ts).isdigit() else ts
            add(x.get("title"), x.get("companyName"), x.get("applicationLink") or x.get("guid"), ", ".join(x.get("locationRestrictions") or []) or "Anywhere", when, "Himalayas", " ".join(x.get("categories") or []))
        ok.append("Himalayas")
    except Exception as e:
        print("jobs: himalayas", str(e)[:60])
    try:
        r = http.get("https://weworkremotely.com/remote-jobs.rss", headers=UA, timeout=20)
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            co, _, t = title.partition(":")
            add(t.strip() or title, co.strip(), it.findtext("link"), it.findtext("region"), it.findtext("pubDate"), "We Work Remotely", it.findtext("category") or "")
            if sum(1 for o in out if o["src"] == "We Work Remotely") >= 30:
                break
        ok.append("We Work Remotely")
    except Exception as e:
        print("jobs: wwr", str(e)[:60])
    learn = []
    try:
        r = http.get("https://www.freecodecamp.org/news/rss/", headers=UA, timeout=20)
        root = ET.fromstring(r.content)
        for it in list(root.iter("item"))[:12]:
            link = it.findtext("link") or ""
            if link.startswith("https://"):
                learn.append({"t": _clean(it.findtext("title"), 110), "url": link, "at": it.findtext("pubDate"), "src": "freeCodeCamp"})
    except Exception as e:
        print("jobs: freecodecamp", str(e)[:60])
    seen, uniq = set(), []
    for o in out:
        k = (o["t"].lower(), o["co"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    if uniq or learn:
        _write("jobs.json", {"jobs": uniq[:150], "learn": learn, "sources": ok})
        print(f"jobs: {len(uniq)} jobs from {', '.join(ok)}")


# =============================== 3. videos ===============================
CHANNELS = [  # (YouTube handle, category)
    ("@WhiteboardCrypto", "crypto"), ("@CoinBureau", "crypto"), ("@BinanceAcademy", "crypto"), ("@CoinGecko", "crypto"),
    ("@freecodecamp", "skills"), ("@GoogleCareerCertificates", "skills"), ("@canva", "skills"), ("@Fiverr", "skills"), ("@Upwork", "skills"),
]
YT_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}


def _channel_id(http, handle, cache):
    if handle in cache:
        return cache[handle]
    r = http.get("https://www.youtube.com/" + handle, headers=dict(UA, **{"Accept-Language": "en"}), cookies={"CONSENT": "YES+1"}, timeout=20)
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', r.text) or re.search(r'youtube\.com/channel/(UC[\w-]{22})', r.text)
    cid = m.group(1) if m else None
    if cid:
        cache[handle] = cid
    return cid


def yt_id(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})", url or "")
    return m.group(1) if m else (url if re.fullmatch(r"[\w-]{11}", url or "") else None)


def videos(state, http, force=False):
    if not force and not _due(state, "videos_time", VIDEOS_EVERY_MIN):
        return
    state["videos_time"] = _now().isoformat(timespec="seconds")
    cache = state.setdefault("yt_ids", {})
    chans = CHANNELS + [(h, c) for h, c in state.get("yt_extra", [])]
    items, ok = [], []
    for handle, cat in chans:
        try:
            cid = _channel_id(http, handle, cache)
            if not cid:
                print("videos: no channel id for", handle)
                continue
            r = http.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": cid}, headers=UA, timeout=20)
            root = ET.fromstring(r.content)
            author = root.findtext("a:title", default=handle, namespaces=YT_NS)
            n = 0
            for e in root.findall("a:entry", YT_NS):
                vid = e.findtext("yt:videoId", namespaces=YT_NS)
                title = e.findtext("a:title", namespaces=YT_NS) or ""
                if not vid or "#shorts" in title.lower():
                    continue
                items.append({"id": vid, "t": _clean(title, 120), "ch": _clean(author, 50), "at": e.findtext("a:published", namespaces=YT_NS), "cat": cat})
                n += 1
                if n >= 6:
                    break
            ok.append(handle)
        except Exception as e:
            print("videos:", handle, str(e)[:60])
        time.sleep(0.5)
    manual = state.get("videos_manual", [])
    seen = set()
    items = [v for v in sorted(items, key=lambda v: v.get("at") or "", reverse=True) if not (v["id"] in seen or seen.add(v["id"]))]
    if items or manual:
        _write("videos.json", {"pinned": manual[:30], "videos": items[:80], "channels": ok})
        print(f"videos: {len(items)} from {len(ok)} channels, {len(manual)} pinned")


def video_command(state, http, text):
    """/video <youtube link> [title]  ·  /video @channel  ·  /video off <link or id>  ·  /video list"""
    arg = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
    man = state.setdefault("videos_manual", [])
    if not arg or arg == "list":
        rows = [f"• {v['t']} ({v['id']})" for v in man[:15]]
        extra = [h for h, _ in state.get("yt_extra", [])]
        return ("🎬 পিন করা ভিডিও:\n" + ("\n".join(rows) or "কিছু নেই") + "\n\nযোগ করা চ্যানেল: " + (", ".join(extra) or "নেই") +
                "\n\nযোগ: <code>/video https://youtu.be/XXXX শিরোনাম</code>\nচ্যানেল: <code>/video @channelname</code>\nবাদ: <code>/video off XXXX</code>")
    if arg.startswith("off"):
        key = arg[3:].strip()
        vid = yt_id(key)
        before = len(man)
        state["videos_manual"] = [v for v in man if v["id"] != vid]
        state["yt_extra"] = [x for x in state.get("yt_extra", []) if x[0].lower() != key.lower()]
        videos(state, http, force=True)
        return "🗑 বাদ দেওয়া হয়েছে।" if len(state["videos_manual"]) < before or key.startswith("@") else "❌ এই ভিডিও তালিকায় নেই।"
    if arg.startswith("@"):
        h = arg.split()[0]
        cid = _channel_id(http, h, state.setdefault("yt_ids", {}))
        if not cid:
            return "❌ এই নামে YouTube চ্যানেল পাওয়া যায়নি।"
        ex = state.setdefault("yt_extra", [])
        if not any(x[0].lower() == h.lower() for x in ex):
            ex.append([h, arg.split()[1] if len(arg.split()) > 1 and arg.split()[1] in ("crypto", "skills") else "crypto"])
        videos(state, http, force=True)
        return f"✅ চ্যানেল {h} যোগ হয়েছে। এর নতুন ভিডিও সাইটে নিজে নিজে আসবে।"
    parts = arg.split(None, 1)
    vid = yt_id(parts[0])
    if not vid:
        return "❌ YouTube লিংক বোঝা যায়নি। যেমন: <code>/video https://youtu.be/abcdefghijk শিরোনাম</code>"
    title = parts[1].strip() if len(parts) > 1 else ""
    if not title:
        try:
            title = http.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, timeout=15).json().get("title", "")
        except Exception:
            title = ""
    man[:] = [v for v in man if v["id"] != vid]
    man.insert(0, {"id": vid, "t": _clean(title or "BEWON video", 120), "at": _now().isoformat(timespec="seconds"), "cat": "bewon"})
    videos(state, http, force=True)
    return f"✅ ভিডিও সাইটে যোগ হয়েছে: {html.escape(title or vid)}"


def run(state, http, frames, get_df, fear_greed=None):
    for name, fn in (("consensus", lambda: consensus(state, http, frames, get_df, fear_greed)),
                     ("jobs", lambda: jobs(state, http)), ("videos", lambda: videos(state, http))):
        try:
            fn()
        except Exception as e:
            print(f"{name} error:", str(e)[:100])
