# -*- coding: utf-8 -*-
"""
AV search module: fetch magnet links from sukebei.nyaa.si
Prioritize: 1080P only, prefer 无码破解+中字 > 中字 > 无码破解 > 色花堂 > other
"""
import re

import requests
from bs4 import BeautifulSoup

UNCENSORED_CRACKED = re.compile(
    r"无码破解|無碼破解|破解|破壊|uncensor|leak|流出|モザイク破壊|"
    r"[-_](U|UC)\b|"
    r"\[(U|UC)\]",
    re.IGNORECASE,
)
CHINESE_SUB = re.compile(
    r"中字|中文字幕|中文|CHS|CHT|官中|"
    r"[-_](C)\b|"
    r"\[C\]|FHDC",
    re.IGNORECASE,
)
SEHUA = re.compile(r"色花|sehua|2048|1024|91porn|桃花|魔性", re.IGNORECASE)
RES_1080 = re.compile(
    r"(?<!\d)1080[pi](?!\d)|"
    r"\bFHD\b|\bFHDC\b|"
    r"\bFull\s*HD\b",
    re.IGNORECASE,
)


def _priority(title):
    has_1080 = bool(RES_1080.search(title))
    has_uncrack = bool(UNCENSORED_CRACKED.search(title))
    has_cn = bool(CHINESE_SUB.search(title))
    has_sehua = bool(SEHUA.search(title))

    if not has_1080:
        return -1

    if has_uncrack and has_cn:
        return 100
    if has_cn:
        return 80
    if has_uncrack:
        return 70
    if has_sehua:
        return 60
    return 10


def search_av(av_number, proxies=None):
    url = "https://sukebei.nyaa.si/"
    params = {"q": av_number, "f": 0, "c": "0_0"}
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.get(url, params=params, headers=headers, timeout=30, proxies=proxies)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for tr in soup.find_all("tr", class_=["default", "success", "danger"]):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        title_a = tr.find("a", href=lambda x: x and x.startswith("/view/"))
        title = title_a.get_text(strip=True) if title_a else "Unknown"

        magnet_a = tr.find("a", href=lambda x: x and x.startswith("magnet:"))
        magnet = magnet_a["href"] if magnet_a else None

        size = tds[3].get_text(strip=True) if len(tds) > 3 else ""
        seeders = tds[5].get_text(strip=True) if len(tds) > 5 else "0"

        pri = _priority(title)
        if pri < 0:
            continue

        if magnet:
            results.append({
                "title": title,
                "magnet": magnet,
                "size": size,
                "seeders": int(seeders) if seeders.isdigit() else 0,
                "priority": pri,
            })

    results.sort(key=lambda x: (-x["priority"], -x["seeders"]))
    return results


def get_top_magnet(av_number):
    results = search_av(av_number)
    if results:
        return results[0]
    return None


if __name__ == "__main__":
    import sys
    av = sys.argv[1] if len(sys.argv) > 1 else "ABP-123"
    print(f"Searching: {av}")
    results = search_av(av)
    print(f"Found {len(results)} results (1080P only)")
    for i, r in enumerate(results[:5], 1):
        print(f"{i}. [P{r['priority']} {r['seeders']}S] {r['title']} | {r['size']}")
        print(f"   Magnet: {r['magnet'][:80]}...")
