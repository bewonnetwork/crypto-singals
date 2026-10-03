# -*- coding: utf-8 -*-
"""
উৎস পরীক্ষা (source probe)
---------------------------
এই ফাইল GitHub-এর সার্ভার থেকে অনেকগুলো এক্সচেঞ্জ আর ওয়েবসাইটে গিয়ে দেখে:
কোনটা থেকে নতুন লিস্টিং, টোকেন আনলক, এয়ারড্রপ আর নতুন কয়েনের তথ্য সত্যিই আনা যায়।
ফলাফল docs/data/probe.json ফাইলে লেখা হয়। এটা কোনো Telegram মেসেজ পাঠায় না।
চালানো:  python signal_bot.py --probe   (বা প্রথমবার নিজে থেকেই একবার চলে)
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

PROBE_VERSION = 2
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "probe.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ZD = "/api/v2/help_center/en-us/articles.json?per_page=8&sort_by=created_at&sort_order=desc"

# (দল, নাম, URL)
SOURCES = [
    # ---- এক্সচেঞ্জের লিস্টিং ঘোষণা ----
    ("listing", "OKX", "https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings"),
    ("listing", "KuCoin", "https://api.kucoin.com/api/v3/announcements?annType=new-listings&lang=en_US&pageSize=8"),
    ("listing", "Binance", "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=8"),
    ("listing", "Bybit", "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&limit=8"),
    ("listing", "Bitget", "https://api.bitget.com/api/v2/public/annoucements?annType=coin_listings&language=en_US"),
    ("listing", "Gate", "https://www.gate.io/api/v4/announcements"),
    ("listing", "Gate-rss", "https://www.gate.io/articlelist/ann/0"),
    ("listing", "MEXC", "https://www.mexc.com/help/announce/api/en-US/section/15425930840735/articles?page=1&perPage=8"),
    ("listing", "MEXC-zd", "https://support.mexc.com" + ZD),
    ("listing", "HTX", "https://www.htx.com/-/x/support/public/getList/v2?language=en-us&page=1&limit=8&oneLevelId=360000031902&twoLevelId=360000039942"),
    ("listing", "Upbit", "https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=8&category=trade"),
    ("listing", "Bithumb", "https://feed.bithumb.com/notice"),
    ("listing", "Coinbase", "https://blog.coinbase.com/feed"),
    ("listing", "Coinbase-assets", "https://www.coinbase.com/blog/rss.xml"),
    ("listing", "Kraken", "https://blog.kraken.com/category/product/asset-listings/feed"),
    ("listing", "Kraken-all", "https://blog.kraken.com/feed/"),
    ("listing", "Crypto.com", "https://crypto.com/exchange-announcements/rss"),
    ("listing", "Bitfinex", "https://api-pub.bitfinex.com/v2/posts/hist?limit=8&type=1"),
    ("listing", "BingX", "https://bingx.com/api/customer/v1/announcement/listArticles?sectionId=11257060005007&page=1&pageSize=8"),
    ("listing", "LBank", "https://support.lbank.site" + ZD),
    ("listing", "BitMart", "https://support.bitmart.com" + ZD),
    ("listing", "Phemex", "https://phemex.com/announcements/rss"),
    ("listing", "CoinEx", "https://www.coinex.com/res/support/announcement/list?page=1&limit=8&category=new_coin"),
    ("listing", "Poloniex", "https://support.poloniex.com" + ZD),
    ("listing", "WhiteBIT", "https://blog.whitebit.com/feed/"),
    ("listing", "XT", "https://xtsupport.zendesk.com" + ZD),
    ("listing", "Bitstamp", "https://www.bitstamp.net/api/v2/news/"),
    ("listing", "Gemini", "https://www.gemini.com/blog/rss.xml"),
    ("listing", "Bitrue", "https://support.bitrue.com" + ZD),
    ("listing", "AscendEX", "https://ascendex.zendesk.com" + ZD),
    ("listing", "DigiFinex", "https://digifinex.zendesk.com" + ZD),
    ("listing", "Deribit", "https://www.deribit.com/api/v2/public/get_announcements"),
    ("listing", "BitMEX", "https://www.bitmex.com/api/v1/announcement"),
    ("listing", "Coinone", "https://api.coinone.co.kr/public/v2/markets/KRW"),
    # ---- টোকেন আনলক ----
    ("unlock", "DefiLlama-emissions", "https://api.llama.fi/emissions"),
    ("unlock", "DefiLlama-dataset", "https://defillama-datasets.llama.fi/emissions/arbitrum"),
    ("unlock", "DefiLlama-breakdown", "https://defillama-datasets.llama.fi/emissionsBreakdown"),
    ("unlock", "CMC-unlocks", "https://api.coinmarketcap.com/data-api/v3/token-unlock/listing?start=1&limit=20"),
    ("unlock", "CryptoRank-vesting", "https://api.cryptorank.io/v0/coins/vesting?limit=20"),
    ("unlock", "DropsTab", "https://api2.dropstab.com/portfolio/api/vesting/upcoming"),
    ("unlock", "CMC-unlocks-next", "https://api.coinmarketcap.com/data-api/v3/token-unlock/listing?start=1&limit=20&sort=next_unlocked_date&direction=asc&enableSmallUnlocks=false"),
    ("unlock", "CMC-unlock-detail", "https://api.coinmarketcap.com/data-api/v3/token-unlock/detail?slug=arbitrum"),
    ("listing", "HTX-article", "https://www.htx.com/support/55045085577698"),
    ("airdrop", "CMC-airdrops-up", "https://api.coinmarketcap.com/data-api/v3/airdrop/query?status=UPCOMING&limit=20"),
    ("newcoin", "ICODrops-upcoming", "https://icodrops.com/category/upcoming-ico/"),
    ("newcoin", "CMC-upcoming2", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/upcoming?limit=30"),
    # ---- এয়ারড্রপ ----
    ("airdrop", "Airdrops.io-latest", "https://airdrops.io/latest/"),
    ("airdrop", "Airdrops.io-claims", "https://airdrops.io/claims/"),
    ("airdrop", "Airdrops.io-feed", "https://airdrops.io/feed/"),
    ("airdrop", "Airdrops.io-wp", "https://airdrops.io/wp-json/wp/v2/posts?per_page=8"),
    ("airdrop", "AirdropAlert-feed", "https://airdropalert.com/feed/"),
    ("airdrop", "AirdropAlert-farm", "https://airdropalert.com/farm/"),
    ("airdrop", "CryptoRank-drophunting", "https://cryptorank.io/drophunting"),
    ("airdrop", "DappRadar", "https://dappradar.com/rewards/airdrops"),
    ("airdrop", "CMC-airdrops", "https://api.coinmarketcap.com/data-api/v3/airdrop/query?status=ONGOING&limit=20"),
    ("airdrop", "DefiLlama-airdrops", "https://airdrops.llama.fi/config"),
    # ---- বাজারে নতুন কয়েন ----
    ("newcoin", "CMC-new-html", "https://coinmarketcap.com/new/"),
    ("newcoin", "CMC-new-api", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/spotlight?dataType=8&limit=30"),
    ("newcoin", "CMC-upcoming", "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/upcoming?limit=30"),
    ("newcoin", "CoinGecko-trending", "https://api.coingecko.com/api/v3/search/trending"),
    ("newcoin", "CoinGecko-new", "https://api.coingecko.com/api/v3/coins/list/new"),
    ("newcoin", "GeckoTerminal-newpools", "https://api.geckoterminal.com/api/v2/networks/new_pools?include=base_token"),
    ("newcoin", "DexScreener-profiles", "https://api.dexscreener.com/token-profiles/latest/v1"),
    ("newcoin", "CoinPaprika", "https://api.coinpaprika.com/v1/coins"),
    ("newcoin", "ICODrops", "https://icodrops.com/"),
    ("newcoin", "CryptoRank-upcoming", "https://api.cryptorank.io/v0/round/upcoming?limit=20"),
    # ---- খবরের RSS ----
    ("news", "CoinGecko-news", "https://www.coingecko.com/en/news/rss"),
    ("news", "Bitcoin.com", "https://news.bitcoin.com/feed/"),
    ("news", "CryptoPotato", "https://cryptopotato.com/feed/"),
    ("news", "BeInCrypto", "https://beincrypto.com/feed/"),
    ("news", "U.Today", "https://u.today/rss"),
    ("news", "NewsBTC", "https://www.newsbtc.com/feed/"),
    ("news", "AMBCrypto", "https://ambcrypto.com/feed/"),
    ("news", "CryptoNews", "https://cryptonews.com/news/feed/"),
    ("news", "Blockworks", "https://blockworks.co/feed"),
    ("news", "DailyHodl", "https://dailyhodl.com/feed/"),
    ("news", "Bitcoinist", "https://bitcoinist.com/feed/"),
    ("news", "CoinJournal", "https://coinjournal.net/feed/"),
]


FULL = {"CMC-unlocks", "CMC-unlocks-next", "CMC-unlock-detail", "CMC-airdrops", "CMC-airdrops-up", "Bitfinex", "DexScreener-profiles",
        "Airdrops.io-latest", "Airdrops.io-claims", "DappRadar", "ICODrops", "ICODrops-upcoming", "CMC-upcoming2", "HTX-article"}


def _first(v, depth=0):
    """প্রথম আইটেমটা পুরো দেখায় (সব চাবি সহ), যাতে ঠিক নাম জানা যায়"""
    if isinstance(v, dict):
        return {k: _first(x, depth + 1) for k, x in list(v.items())[:60]} if depth < 7 else "{…}"
    if isinstance(v, list):
        return ["len=%d" % len(v)] + ([_first(v[0], depth + 1)] if v else [])
    s = str(v)
    return s if len(s) <= 200 else s[:200] + "…"


def _shape(v, depth=0):
    """JSON-এর গঠন ছোট করে দেখায় (কোন চাবির ভেতরে কী আছে)"""
    if isinstance(v, dict):
        if depth >= 5:
            return "{…%d keys}" % len(v)
        return {k: _shape(x, depth + 1) for k, x in list(v.items())[:14]}
    if isinstance(v, list):
        return ["len=%d" % len(v)] + ([_shape(v[0], depth + 1)] if v else [])
    s = str(v)
    return s if len(s) <= 120 else s[:120] + "…"


def _anchors(text):
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if 6 <= len(t) <= 110 and href not in seen:
            seen.add(href)
            out.append([href[:160], t])
    return out


def check(src):
    group, name, url = src
    row = {"group": group, "name": name, "url": url}
    try:
        headers = {"User-Agent": UA, "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.8",
                   "Accept-Language": "en-US,en;q=0.9"}
        r = requests.get(url, headers=headers, timeout=14)
        text = r.text or ""
        row.update(status=r.status_code, ctype=(r.headers.get("content-type") or "")[:60], size=len(text))
        t = text.lstrip()
        if t[:1] in "{[":
            try:
                row["kind"], row["shape"] = "json", (_first if name in FULL else _shape)(r.json())
            except ValueError:
                row["kind"], row["head"] = "text", t[:400]
        elif "<rss" in t[:600] or "<feed" in t[:600] or "<?xml" in t[:60]:
            titles = re.findall(r"<item[\s>].*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?(?:<pubDate>(.*?)</pubDate>)?", t, re.S)
            row["kind"] = "rss"
            row["items"] = len(re.findall(r"<item[\s>]|<entry[\s>]", t))
            row["sample"] = [[re.sub(r"<!\[CDATA\[|\]\]>", "", a).strip()[:120], b.strip()[:160], c.strip()[:40]] for a, b, c in titles[:4]]
        else:
            row["kind"] = "html"
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
            if m:
                try:
                    row["next_data"] = _shape(json.loads(m.group(1)).get("props", {}).get("pageProps", {}))
                except ValueError:
                    row["next_data"] = m.group(1)[:300]
            a = _anchors(t)
            row["anchors"] = len(a)
            row["sample"] = a[:160] if name in FULL else (a[40:75] if len(a) > 80 else a[:35])
            row["title"] = (re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I) or [None, ""])[1].strip()[:120]
        row["ok"] = bool(r.status_code == 200 and len(text) > 200)
    except Exception as e:
        row.update(status=0, ok=False, error=str(e)[:140])
    return row


def run(extra=None):
    srcs = SOURCES + (extra or [])
    key = os.getenv("CMC_KEY", "")
    with ThreadPoolExecutor(max_workers=12) as ex:
        rows = list(ex.map(check, srcs))
    if key:
        try:
            r = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest",
                             params={"sort": "date_added", "limit": 20}, headers={"X-CMC_PRO_API_KEY": key}, timeout=14)
            rows.append({"group": "newcoin", "name": "CMC-pro-key", "url": "pro-api listings/latest", "status": r.status_code,
                         "ok": r.status_code == 200, "kind": "json", "shape": _shape(r.json())})
        except Exception as e:
            rows.append({"group": "newcoin", "name": "CMC-pro-key", "status": 0, "ok": False, "error": str(e)[:140]})
    ok = [x["name"] for x in rows if x.get("ok")]
    out = {"version": PROBE_VERSION, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "ok": len(ok), "total": len(rows), "results": rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("===== SOURCE PROBE =====")
    for x in rows:
        print(f"{'OK  ' if x.get('ok') else 'FAIL'} {x.get('status', 0):>3} {x['group']:<8} {x['name']:<24} {x.get('kind', ''):<5} {x.get('size', 0)}")
    print(f"===== {len(ok)}/{len(rows)} sources answered =====")
    return out


if __name__ == "__main__":
    run()
