import logging
import os
import re
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger("tg-download-bot")

BASE_URL = "https://www.hgeme.com"


class HGMESession:
    def __init__(self, username, password, proxy_url=None):
        self.username = username
        self.password = password
        self.proxy_url = proxy_url
        self.browser = None
        self.page = None
        self._logged_in = False

    def _ensure_browser(self):
        if self.browser is None:
            p = sync_playwright().start()
            launch_opts = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if self.proxy_url:
                launch_opts["proxy"] = {"server": self.proxy_url}
            self.browser = p.chromium.launch(**launch_opts)
            self.page = self.browser.new_page()
        return self.page

    def ensure_logged_in(self) -> bool:
        if self._logged_in:
            return True
        page = self._ensure_browser()
        try:
            page.goto(BASE_URL, timeout=30000)
            self._wait_for_page(page)
            if "立即登录" not in page.content() and "未登录" not in page.content():
                self._logged_in = True
                return True
            ok = self._login(page)
            if ok:
                self._logged_in = True
            return ok
        except Exception as e:
            logger.error("HGME session error: %s", e)
            return False

    def _login(self, page) -> bool:
        try:
            page.goto(f"{BASE_URL}/user/login", timeout=30000)
            self._wait_for_page(page)
            page.fill("input[name=username]", self.username)
            page.fill("input[name=password]", self.password)
            page.click("#button")
            time.sleep(3)
            if "未登录" in page.content() and "立即登录" in page.content():
                logger.warning("HGME login failed - check credentials")
                return False
            logger.info("HGME login successful")
            return True
        except Exception as e:
            logger.warning("HGME login error: %s", e)
            return False

    def _wait_for_page(self, page, timeout=30):
        """Wait for PoW/browser security check to complete."""
        for _ in range(timeout):
            try:
                if "安全验证" not in page.content():
                    return
            except Exception as e:
                logger.warning("HGME page content check error: %s", e)
            time.sleep(1)
        logger.warning("HGME PoW timed out")

    def search(self, keyword: str):
        from hgme_search import Candidate
        if not self.ensure_logged_in():
            return []
        page = self.page
        if not page:
            return []
        from urllib.parse import quote
        encoded = quote(keyword, safe="")
        try:
            page.goto(f"{BASE_URL}/search?q={encoded}&type=&mode=1", timeout=30000)
            self._wait_for_page(page)
        except Exception as e:
            logger.warning("HGME search error: %s", e)
            return []

        soup = BeautifulSoup(page.content(), "lxml")
        candidates = []

        for v5d in soup.select("div.v5d"):
            title_a = v5d.select_one("a.d16")
            if not title_a:
                continue
            href = title_a.get("href", "")
            m = re.match(r"/(mv|tv|ac)/([a-zA-Z0-9]+)", href)
            if not m:
                continue
            kind = m.group(1)
            id_ = m.group(2)

            title = title_a.get_text(strip=True)

            year = 0
            ym = re.search(r"\((\d{4})\)", title)
            if ym:
                year = int(ym.group(1))
            title = re.sub(r"\s*\(\d{4}\)\s*", "", title, count=1).strip()

            paras = v5d.select("div.text p")
            tags = []
            score = ""
            for p in paras:
                text = p.get_text(strip=True)
                if text.startswith("评分"):
                    score = text.replace("评分：", "").strip()
                elif not text.startswith("又名") and not text.startswith("导演") and not text.startswith("编剧") and not text.startswith("主演"):
                    if "/" in text and len(text) < 80:
                        tags = [t.strip() for t in text.split("/")]

            full_url = f"{BASE_URL}{href}"
            candidates.append(Candidate(
                kind=kind, id=id_, title=title,
                year=year, score=score, tags=tags, url=full_url
            ))

        candidates.sort(key=lambda c: c.year, reverse=True)
        return candidates

    def get_torrents(self, kind: str, id_: str):
        from hgme_search import MagnetItem
        page = self.page
        if not page:
            return []
        try:
            result = page.evaluate(f"""
                async () => {{
                    const r = await fetch('{BASE_URL}/res/downurl/{kind}/{id_}');
                    return await r.json();
                }}
            """)
        except Exception as e:
            logger.warning("HGME get_torrents error: %s", e)
            return []

        if not isinstance(result, dict) or result.get("code") != 200:
            return []
        dl = result.get("downlist")
        if not dl:
            return []

        type_map = dict(zip(dl["type"]["b"], dl["type"]["a"]))
        targets = [k for k, v in type_map.items() if "中字" in v]

        items = []
        for i in range(len(dl["list"]["m"])):
            tag_id = dl["list"]["p"][i] if i < len(dl["list"]["p"]) else ""
            if tag_id not in targets:
                continue
            title = dl["list"]["t"][i] if i < len(dl["list"]["t"]) else ""
            size = dl["list"]["s"][i] if i < len(dl["list"]["s"]) else ""
            btih = dl["list"]["m"][i] if i < len(dl["list"]["m"]) else ""
            magnet = f"magnet:?xt=urn:btih:{btih}"
            tag_label = type_map.get(tag_id, tag_id)
            items.append(MagnetItem(title=title, size=size, tag=tag_label, magnet=magnet))

        def _size_bytes(size_str):
            if not size_str:
                return 0
            n = re.search(r"([\d.]+)\s*([GTKM]?)", size_str)
            if not n:
                return 0
            v = float(n.group(1))
            u = n.group(2).upper()
            return int(v * {"G": 1e9, "T": 1e12, "M": 1e6, "K": 1e3}.get(u, 0))

        items.sort(key=lambda x: _size_bytes(x.size))
        return items

    def close(self):
        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                logger.warning("Failed to close browser: %s", e)
            self.browser = None
            self.page = None


_session = None


def get_session():
    global _session
    if _session is None:
        username = os.getenv("HGME_USERNAME", "")
        password = os.getenv("HGME_PASSWORD", "")
        proxy_url = os.getenv("PROXY_URL") or os.getenv("HTTP_PROXY") or None
        _session = HGMESession(username, password, proxy_url)
    return _session


def close_session():
    global _session
    if _session:
        _session.close()
        _session = None
