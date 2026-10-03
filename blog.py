# -*- coding: utf-8 -*-
"""ওয়েবসাইটের ব্লগ পাতা (docs/data/blog.json): Market Digest, Trending আর শেখার পোস্ট।
Telegram-এ শুধু ছোট লেখা + লিংক যায়; পুরো লেখা সাইটে খোলে।"""
import json
import os
from datetime import datetime, timezone

BLOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "blog.json")
BLOG_KEEP = 120
CG = "https://api.coingecko.com/api/v3/"
STABLE = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDS", "PYUSD", "USD1", "BUSD", "USDD", "WBTC", "STETH", "WETH", "WSTETH", "WEETH"}

# শেখার লেখা: প্রতিদিন একটা করে ঘুরে ঘুরে যায়
LESSONS = [
    {"key": "what-is-a-stop-loss", "en": "What Is a Stop-Loss Order and How Does It Work?", "bn": "Stop Loss কী এবং কীভাবে কাজ করে?",
     "sum_en": "A stop-loss closes your trade by itself when price reaches the level where your idea is proven wrong. Here is how to place it and why it sometimes fills at a different price.",
     "sum_bn": "দাম আপনার ঠিক করা জায়গায় পৌঁছালে Stop Loss নিজে থেকে ট্রেড বন্ধ করে দেয়। কোথায় বসাবেন আর কেন কখনো অন্য দামে বন্ধ হয়, জেনে নিন।",
     "pts_bn": ["Stop Loss হলো আগে থেকে দেওয়া একটা অর্ডার: দাম ওই জায়গায় এলে ট্রেড নিজে বন্ধ হবে। এতে ছোট ক্ষতি বড় ক্ষতিতে গড়ায় না।",
                "কোথায় বসাবেন: যে দামে গেলে আপনার ধারণা ভুল প্রমাণ হয়। BUY হলে শেষ সাপোর্টের একটু নিচে, SELL হলে শেষ রেজিস্ট্যান্সের একটু ওপরে।",
                "Stop-market দাম ছুঁলেই বাজার দামে বেচে দেয় (নিশ্চিত বন্ধ, দাম একটু এদিক-ওদিক হতে পারে)। Stop-limit শুধু আপনার দামে বেচে (দাম ঠিক, কিন্তু বন্ধ নাও হতে পারে)।",
                "দাম খুব দ্রুত নড়লে Stop Loss আপনার দামের চেয়ে খারাপ দামে বন্ধ হতে পারে। একে slippage বলে।",
                "নিয়ম: Stop Loss ছাড়া কোনো ট্রেড নয়, আর ট্রেড চলার সময় Stop Loss দূরে সরাবেন না।"],
     "pts_en": ["A stop-loss is an order you place in advance: when price reaches that level the trade closes by itself, so a small loss cannot grow into a big one.",
                "Where to put it: at the price that proves your idea wrong. For a BUY, a little below the last support; for a SELL, a little above the last resistance.",
                "A stop-market order sells at the market price once triggered (it will close, but the price may differ slightly). A stop-limit sells only at your price (the price is fixed, but it may not fill).",
                "When price moves very fast the stop can fill at a worse price than you set. This is called slippage.",
                "Rule: no trade without a stop-loss, and never move the stop further away while the trade is running."]},
    {"key": "position-size-and-the-1-percent-rule", "en": "Position Size and the 1% Rule", "bn": "এক ট্রেডে কত টাকা? ১% নিয়ম",
     "sum_en": "How much you risk per trade matters more than which coin you pick. The 1% rule keeps one bad trade from hurting your account.",
     "sum_bn": "কোন কয়েন কিনছেন তার চেয়ে বড় কথা এক ট্রেডে কত ঝুঁকি নিচ্ছেন। ১% নিয়ম একটা খারাপ ট্রেড থেকে আপনার টাকা বাঁচায়।",
     "pts_bn": ["নিয়ম: এক ট্রেডে মোট টাকার ১–২%-এর বেশি হারানোর ঝুঁকি নেবেন না।",
                "হিসাব: ঝুঁকির টাকা ÷ (Entry থেকে Stop Loss-এর দূরত্ব %) = ট্রেডের আকার। যেমন ১০০০ ডলারে ১% = ১০ ডলার ঝুঁকি; Stop Loss ২% দূরে হলে ট্রেডের আকার ৫০০ ডলার।",
                "Stop Loss দূরে হলে ট্রেড ছোট হবে, কাছে হলে বড় হতে পারে। ঝুঁকির টাকা একই থাকে।",
                "টানা ১০টা ট্রেড হারলেও এই নিয়মে মাত্র ১০% মতো যায়, আপনি খেলায় টিকে থাকেন।",
                "ওয়েবসাইটের ডেমো পাতায় নকল টাকায় এই হিসাব প্র্যাকটিস করুন।"],
     "pts_en": ["Rule: never risk more than 1–2% of your total money on one trade.",
                "Maths: risk amount ÷ (distance from entry to stop-loss in %) = position size. With $1,000, 1% is $10 of risk; if the stop is 2% away the position is $500.",
                "A wider stop means a smaller position, a tighter stop allows a bigger one. The money at risk stays the same.",
                "Even ten losing trades in a row cost only about 10%, so you stay in the game.",
                "Practise this with play money on the demo page of our site."]},
    {"key": "risk-reward-ratio-explained", "en": "Risk : Reward Ratio Explained", "bn": "Risk : Reward কী?",
     "sum_en": "A trade is worth taking only if the possible gain is clearly bigger than the possible loss. Here is how to measure it before you enter.",
     "sum_bn": "সম্ভাব্য লাভ সম্ভাব্য ক্ষতির চেয়ে পরিষ্কারভাবে বড় হলে তবেই ট্রেড নেওয়ার মতো। ঢোকার আগে কীভাবে মাপবেন দেখুন।",
     "pts_bn": ["Risk = Entry থেকে Stop Loss। Reward = Entry থেকে Target।",
                "১ : ২ মানে ১ টাকা ঝুঁকিতে ২ টাকা লাভের সুযোগ। এতে ১০টার মধ্যে মাত্র ৪টা জিতলেও লাভে থাকা যায়।",
                "১ : ১-এর কম হলে অর্ধেকের বেশি ট্রেড জিততে হবে, যা কঠিন।",
                "Target বাস্তব জায়গায় বসান (আগের হাই বা রেজিস্ট্যান্স), শুধু অনুপাত মেলাতে দূরে বসাবেন না।",
                "ফি-ও হিসাবে ধরুন: ছোট টার্গেটের ট্রেডে ফি লাভের বড় অংশ খেয়ে ফেলে।"],
     "pts_en": ["Risk = entry to stop-loss. Reward = entry to target.",
                "1 : 2 means risking 1 to make 2. With that you can win only 4 trades out of 10 and still be in profit.",
                "Below 1 : 1 you need to win more than half your trades, which is hard.",
                "Put the target at a real level (a previous high or resistance); do not stretch it just to make the ratio look good.",
                "Count fees too: on small-target trades fees eat a large share of the gain."]},
    {"key": "support-and-resistance-basics", "en": "Support and Resistance Basics", "bn": "সাপোর্ট ও রেজিস্ট্যান্স",
     "sum_en": "Prices often stop and turn at the same levels again and again. Learn how to find those levels and how traders use them.",
     "sum_bn": "দাম প্রায়ই একই জায়গায় এসে থামে বা ঘুরে যায়। সেই জায়গাগুলো কীভাবে খুঁজবেন আর কাজে লাগাবেন জেনে নিন।",
     "pts_bn": ["সাপোর্ট: যে দামে ক্রেতা বেশি আসে, দাম পড়া থামে। রেজিস্ট্যান্স: যে দামে বিক্রেতা বেশি আসে, দাম ওঠা থামে।",
                "যে জায়গা থেকে দাম ২–৩ বার ফিরে গেছে সেটা শক্ত। বড় টাইমফ্রেমের (৪ঘ, ১দিন) লেভেল বেশি গুরুত্বপূর্ণ।",
                "রেজিস্ট্যান্স ভেঙে ওপরে গেলে সেটা অনেক সময় নতুন সাপোর্ট হয়ে যায়।",
                "লেভেল একটা দাগ নয়, একটা এলাকা। ঠিক দামে না ধরে আশপাশের কয়েকটা দাম ধরুন।",
                "লেভেলের একদম গায়ে Stop Loss বসালে সহজে হিট হয়; একটু বাইরে বসান।"],
     "pts_en": ["Support is a price where buyers step in and the fall stops. Resistance is a price where sellers step in and the rise stops.",
                "A level that turned price two or three times is strong. Levels on bigger timeframes (4h, 1 day) matter more.",
                "When resistance breaks, it often becomes the new support.",
                "A level is a zone, not a thin line. Think of a small price area rather than one exact number.",
                "A stop placed exactly on the level gets hit easily; put it a little beyond."]},
    {"key": "what-is-leverage-and-liquidation", "en": "What Is Leverage and Liquidation?", "bn": "লিভারেজ ও লিকুইডেশন কী?",
     "sum_en": "Leverage lets you trade a bigger size than your money, and it makes losses bigger just as fast. See how liquidation happens.",
     "sum_bn": "লিভারেজে নিজের টাকার চেয়ে বড় ট্রেড করা যায়, আর ক্ষতিও ততটাই দ্রুত বড় হয়। লিকুইডেশন কীভাবে হয় দেখুন।",
     "pts_bn": ["১০x লিভারেজ মানে ১০০ ডলার দিয়ে ১০০০ ডলারের ট্রেড। দাম ১% নড়লে আপনার টাকায় ১০% লাভ বা ক্ষতি।",
                "দাম উল্টো দিকে প্রায় ১০% গেলে (১০x-এ) পুরো টাকা শেষ। এক্সচেঞ্জ তখন ট্রেড জোর করে বন্ধ করে দেয়, এটাই লিকুইডেশন।",
                "লিভারেজ যত বেশি, লিকুইডেশনের দাম তত কাছে। ৫০x-এ মাত্র ২% নড়াচড়াই যথেষ্ট।",
                "নতুনদের জন্য লিভারেজ নয়। আগে স্পটে আর ডেমোতে শিখুন।",
                "ব্যবহার করলেও কম লিভারেজ (২–৩x) আর সবসময় Stop Loss।"],
     "pts_en": ["10x leverage means a $1,000 trade with $100. A 1% price move is a 10% gain or loss on your money.",
                "If price goes about 10% against you (at 10x) the money is gone. The exchange force-closes the trade: that is liquidation.",
                "The higher the leverage, the closer the liquidation price. At 50x a 2% move is enough.",
                "Leverage is not for beginners. Learn on spot and on the demo first.",
                "If you do use it, keep it low (2–3x) and always use a stop-loss."]},
    {"key": "how-to-read-rsi", "en": "How to Read RSI", "bn": "RSI কীভাবে পড়বেন",
     "sum_en": "RSI shows how fast price has been rising or falling on a 0–100 scale. Here is what the numbers mean and the common mistake to avoid.",
     "sum_bn": "RSI ০–১০০ স্কেলে দেখায় দাম কত জোরে উঠছে বা পড়ছে। সংখ্যাগুলোর মানে আর সাধারণ ভুলটা জেনে নিন।",
     "pts_bn": ["৫০-এর ওপরে মানে ক্রেতারা শক্তিশালী, ৫০-এর নিচে বিক্রেতারা।",
                "৭০-এর ওপরে 'overbought', ৩০-এর নিচে 'oversold'। মানে দাম দ্রুত অনেকটা চলে গেছে।",
                "সাধারণ ভুল: RSI ৭০ দেখেই বেচে দেওয়া। শক্ত ট্রেন্ডে RSI অনেকক্ষণ ৭০-এর ওপরে থাকতে পারে।",
                "দাম নতুন হাই করছে কিন্তু RSI করছে না: এটাকে divergence বলে, ট্রেন্ড দুর্বল হওয়ার ইঙ্গিত।",
                "RSI একা সিদ্ধান্ত নয়। ট্রেন্ড আর সাপোর্ট-রেজিস্ট্যান্সের সাথে মিলিয়ে দেখুন।"],
     "pts_en": ["Above 50 buyers are stronger; below 50 sellers are.",
                "Above 70 is called overbought and below 30 oversold: price has moved far, fast.",
                "Common mistake: selling just because RSI is 70. In a strong trend RSI can stay above 70 for a long time.",
                "Price makes a new high but RSI does not: this is divergence, a hint that the trend is weakening.",
                "RSI alone is not a decision. Read it together with the trend and support/resistance."]},
    {"key": "market-cap-vs-fdv", "en": "Market Cap vs FDV", "bn": "Market Cap আর FDV-এর পার্থক্য",
     "sum_en": "Two numbers that tell you how big a coin is today and how much new supply is still coming. A big gap between them is a warning.",
     "sum_bn": "দুটো সংখ্যা: কয়েনটা আজ কত বড়, আর সামনে কত নতুন টোকেন আসবে। দুটোর মধ্যে বড় ফারাক একটা সতর্কবার্তা।",
     "pts_bn": ["Market cap = এখন বাজারে থাকা টোকেন × দাম।",
                "FDV = মোট যত টোকেন কখনো হবে × দাম।",
                "FDV যদি Market cap-এর অনেক গুণ হয়, সামনে প্রচুর টোকেন বাজারে আসবে (আনলক)। সরবরাহ বাড়লে দামে চাপ পড়ে।",
                "কেনার আগে আনলকের তারিখ দেখে নিন। সাইটের 'শেখা' পাতায় সামনের আনলকের তালিকা আছে।",
                "কম দামের কয়েন মানেই সস্তা নয়। দাম নয়, Market cap দিয়ে তুলনা করুন।"],
     "pts_en": ["Market cap = tokens in circulation now × price.",
                "FDV = every token that will ever exist × price.",
                "If FDV is many times the market cap, a lot of tokens will still be unlocked. More supply puts pressure on price.",
                "Check unlock dates before buying. The Learn page on our site lists upcoming unlocks.",
                "A low price does not mean cheap. Compare by market cap, not by price."]},
    {"key": "how-to-avoid-airdrop-scams", "en": "How to Avoid Airdrop Scams", "bn": "এয়ারড্রপের প্রতারণা থেকে বাঁচবেন কীভাবে",
     "sum_en": "Real airdrops never ask for your seed phrase or for money first. These simple checks keep your wallet safe.",
     "sum_bn": "আসল এয়ারড্রপ কখনো seed phrase বা আগে টাকা চায় না। এই কয়টা সহজ নিয়ম আপনার ওয়ালেট নিরাপদ রাখবে।",
     "pts_bn": ["কেউ seed phrase বা private key চাইলে সেটা শতভাগ প্রতারণা।",
                "'আগে টাকা বা গ্যাস ফি পাঠান, তারপর এয়ারড্রপ' — এটাও সবসময় প্রতারণা।",
                "এয়ারড্রপের জন্য আলাদা খালি ওয়ালেট ব্যবহার করুন, মূল টাকার ওয়ালেট নয়।",
                "লিংক সবসময় প্রজেক্টের অফিসিয়াল সাইট বা অফিসিয়াল X অ্যাকাউন্ট থেকে নিন। মেসেজে আসা লিংকে চাপবেন না।",
                "ওয়ালেটে হঠাৎ অচেনা টোকেন এলে সেটা বেচতে বা 'claim' করতে যাবেন না; এগুলো প্রায়ই ফাঁদ।"],
     "pts_en": ["Anyone asking for your seed phrase or private key is a scammer, every time.",
                "'Send money or gas first, then get the airdrop' is also always a scam.",
                "Use a separate empty wallet for airdrops, never the wallet that holds your main funds.",
                "Take links only from the project's official site or official X account. Do not tap links sent in messages.",
                "If unknown tokens suddenly appear in your wallet, do not try to sell or claim them; they are often traps."]},
    {"key": "trend-and-timeframes", "en": "Trend and Timeframes: Trade With the Bigger Picture", "bn": "ট্রেন্ড ও টাইমফ্রেম: বড় ছবির সাথে ট্রেড করুন",
     "sum_en": "A signal on a small chart works better when the bigger charts agree. Learn the simple top-down check our engine also uses.",
     "sum_bn": "ছোট চার্টের সিগনাল তখনই ভালো কাজ করে যখন বড় চার্টও একই কথা বলে। আমাদের ইঞ্জিন যে সহজ পরীক্ষাটা করে সেটা শিখুন।",
     "pts_bn": ["আগে দৈনিক আর ৪ ঘণ্টার চার্ট দেখুন: দাম উঠছে, নামছে, না পাশাপাশি চলছে?",
                "তারপর ১ ঘণ্টার চার্টে Entry খুঁজুন, বড় ট্রেন্ডের দিকেই।",
                "বড় ট্রেন্ডের উল্টো দিকে ট্রেড মানে স্রোতের বিপরীতে সাঁতার।",
                "আমাদের Market Watch নোটে 'Timeframes' লাইনে ✅ মানে ওই টাইমফ্রেম একমত, ❌ মানে নয়।",
                "সব টাইমফ্রেম একমত হলেও লাভের নিশ্চয়তা নেই; শুধু সম্ভাবনা একটু ভালো।"],
     "pts_en": ["Start with the daily and 4-hour charts: is price rising, falling or moving sideways?",
                "Then look for an entry on the 1-hour chart, in the direction of the bigger trend.",
                "Trading against the bigger trend is swimming against the current.",
                "In our Market Watch notes the 'Timeframes' line shows ✅ when a timeframe agrees and ❌ when it does not.",
                "Even when every timeframe agrees nothing is guaranteed; the odds are only somewhat better."]},
    {"key": "why-keep-a-trading-journal", "en": "Why Keep a Trading Journal", "bn": "ট্রেডিং খাতা কেন রাখবেন",
     "sum_en": "Writing down every trade is the fastest way to find your own mistakes. Here is what to record.",
     "sum_bn": "প্রতিটা ট্রেড লিখে রাখা নিজের ভুল ধরার সবচেয়ে দ্রুত উপায়। কী কী লিখবেন দেখুন।",
     "pts_bn": ["লিখুন: কয়েন, দিক, Entry, Stop Loss, Target, কেন নিলেন, ফলাফল।",
                "ট্রেডের সময় কেমন লাগছিল সেটাও লিখুন (ভয়, লোভ, রাগ)। আবেগের ট্রেড সহজে ধরা পড়ে।",
                "সপ্তাহে একবার পড়ুন: কোন ধরনের ট্রেডে বেশি হারছেন?",
                "২০–৩০টা ট্রেডের পর বুঝবেন আপনার নিয়ম আসলে কাজ করে কিনা।",
                "সাইটের ডেমো পাতায় প্রতিটা ডেমো ট্রেডের ইতিহাস নিজে থেকে জমা হয়।"],
     "pts_en": ["Record: coin, direction, entry, stop-loss, target, why you took it, and the result.",
                "Also write how you felt (fear, greed, anger). Emotional trades become easy to spot.",
                "Read it once a week: which kind of trade loses most?",
                "After 20–30 trades you will know whether your rules really work.",
                "The demo page on our site keeps a history of every demo trade for you."]},
]


def load():
    try:
        with open(BLOG_FILE, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d.get("posts"), list):
                return d
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"posts": []}


def add(post):
    d = load()
    d["posts"] = [post] + [p for p in d["posts"] if p.get("slug") != post["slug"]]
    del d["posts"][BLOG_KEEP:]
    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(BLOG_FILE), exist_ok=True)
    with open(BLOG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def _day(now):
    return f"{now:%B} {now.day}, {now.year}", f"{now:%B}-{now.day}-{now.year}".lower()


def _coin(c):
    return {"sym": str(c.get("symbol", "")).upper(), "name": c.get("name", ""), "price": c.get("current_price"),
            "ch": round(c.get("price_change_percentage_24h") or 0, 2), "vol": c.get("total_volume"), "rank": c.get("market_cap_rank")}


def markets(http, ua):
    r = http.get(CG + "coins/markets", params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 150, "page": 1},
                 headers=ua, timeout=25).json()
    return [_coin(c) for c in r if isinstance(c, dict) and str(c.get("symbol", "")).upper() not in STABLE and c.get("current_price")]


def digest(http, ua, majors, extra):
    """majors: [{sym, price, ch}] বটের নিজের কয়েন; extra: fear_greed, fx, record"""
    now = datetime.now(timezone.utc)
    day, dslug = _day(now)
    try:
        mk = markets(http, ua)
    except Exception as e:
        print("digest markets error:", str(e)[:70])
        mk = []
    pool = mk or majors
    if not pool:
        return None
    gain = sorted(pool, key=lambda x: -x["ch"])[:8]
    lose = sorted(pool, key=lambda x: x["ch"])[:8]
    lead = max(pool, key=lambda x: abs(x["ch"]))
    up = sum(1 for x in pool if x["ch"] > 0)
    post = {"slug": f"crypto-market-digest-{dslug}", "type": "digest", "date": now.isoformat(timespec="seconds"),
            "title": f"Crypto Market Digest — {day}",
            "sum_en": f"{lead['sym']} leads today's movers ({lead['ch']:+.1f}%) — see the full gainers and losers breakdown.",
            "sum_bn": f"আজ সবচেয়ে বেশি নড়েছে {lead['sym']} ({lead['ch']:+.1f}%) — কারা বাড়ল, কারা কমল, পুরো তালিকা দেখুন।",
            "body": dict({"gainers": gain, "losers": lose, "majors": majors, "up": up, "total": len(pool)}, **extra)}
    add(post)
    return post


def trending(http, ua):
    now = datetime.now(timezone.utc)
    day, dslug = _day(now)
    r = http.get(CG + "search/trending", headers=ua, timeout=20).json()
    hot = []
    for c in (r.get("coins") or [])[:10]:
        it = c.get("item", {})
        d = it.get("data") or {}
        try:
            price = float(d.get("price"))
        except (TypeError, ValueError):
            price = None
        ch = (d.get("price_change_percentage_24h") or {}).get("usd")
        hot.append({"sym": str(it.get("symbol", "")).upper(), "name": it.get("name", ""), "rank": it.get("market_cap_rank"),
                    "price": price, "ch": round(ch, 2) if isinstance(ch, (int, float)) else None})
    if len(hot) < 3:
        return None
    try:
        vol = sorted(markets(http, ua), key=lambda x: -(x["vol"] or 0))[:8]
    except Exception:
        vol = []
    post = {"slug": f"trending-in-crypto-{dslug}", "type": "trending", "date": now.isoformat(timespec="seconds"),
            "title": f"Trending in Crypto — {day}",
            "sum_en": "The coins getting the most attention today — most searched and volume leaders.",
            "sum_bn": f"আজ যেসব কয়েন সবচেয়ে বেশি খোঁজা হচ্ছে ({', '.join(h['sym'] for h in hot[:3])}…) আর যেগুলোতে লেনদেন সবচেয়ে বেশি।",
            "body": {"hot": hot, "volume": vol}}
    add(post)
    return post


def lesson(day_number):
    now = datetime.now(timezone.utc)
    L = LESSONS[day_number % len(LESSONS)]
    post = {"slug": L["key"], "type": "learn", "date": now.isoformat(timespec="seconds"),
            "title": L["en"], "title_bn": L["bn"], "sum_en": L["sum_en"], "sum_bn": L["sum_bn"],
            "body": {"pts_bn": L["pts_bn"], "pts_en": L["pts_en"]}}
    add(post)
    return post
