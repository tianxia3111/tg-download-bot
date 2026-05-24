# -*- coding: utf-8 -*-
"""
Poster/cover fetching: TMDB for movies, javbus + avmoo for AV.
"""
import logging
import re
import time

import cloudscraper
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("tg-download-bot")


def _upgrade_tmdb_poster(url):
    return re.sub(r"/t/p/w\d+_and_h\d+_face/", "/t/p/w780/", url)


def fetch_movie_poster(name, proxies=None):
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}

    def _search(query):
        url = f"https://www.themoviedb.org/search/movie?query={query}"
        try:
            resp = requests.get(url, headers=headers, proxies=proxies, timeout=15)
        except Exception as e:
            logger.warning("TMDB search error: %s", e)
            return None
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all("p"):
            if "No results" in tag.text:
                return None
        for img in soup.find_all("img"):
            alt = img.get("alt", "")
            if alt and alt != "The Movie Database (TMDB)":
                parent = img.find_parent("a")
                if parent and parent.get("href"):
                    return parent["href"]
        return None

    href = _search(name)
    if not href:
        name_no_year = re.sub(r'\b\d{4}\b', '', name).strip()
        if name_no_year != name:
            href = _search(name_no_year)
    if not href:
        return None

    detail_url = "https://www.themoviedb.org" + href
    try:
        resp = requests.get(detail_url, headers=headers, proxies=proxies, timeout=15)
    except Exception as e:
        logger.warning("TMDB detail error: %s", e)
        return None
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    imgs = soup.find_all("img")
    if len(imgs) < 2:
        return None
    poster = imgs[1].get("src")
    return _upgrade_tmdb_poster(poster) if poster else None


def fetch_av_poster(code, proxies=None):
    result = _fetch_javbus_poster(code, proxies)
    if result:
        return result
    logger.info("javbus miss for %s, trying avmoo...", code)
    return _fetch_avmoo_poster(code, proxies)


def _fetch_javbus_poster(code, proxies=None):
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": "existmag=mag; age=verified; dv=1"}

    def _search(search_url):
        try:
            resp = requests.get(search_url, headers=headers, proxies=proxies, timeout=15)
        except Exception as e:
            logger.warning("javbus search error: %s", e)
            return None
        if resp.status_code != 200:
            logger.info("javbus %s -> %d, skipping", search_url, resp.status_code)
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", class_="movie-box"):
            href = a_tag.get("href", "")
            if code.lower() in href.lower():
                return href
        return None

    detail_url = _search(f"https://www.javbus.com/search/{code}")
    if not detail_url:
        detail_url = _search(f"https://www.javbus.com/uncensored/search/{code}")
    if not detail_url:
        return None

    try:
        resp = requests.get(detail_url, headers=headers, proxies=proxies, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        big_img = soup.find("a", class_="bigImage")
        if big_img and big_img.get("href"):
            src = big_img["href"]
            if not src.startswith("http"):
                src = f"https://www.javbus.com{src}"
            return src
        img = soup.find("img", class_="bigImage")
        if img and img.get("src"):
            src = img["src"]
            if not src.startswith("http"):
                src = f"https://www.javbus.com{src}"
            return src
    except Exception as e:
        logger.warning("javbus detail error: %s", e)
    return None


def _fetch_avmoo_poster(code, proxies=None):
    try:
        scraper = cloudscraper.create_scraper()
        if proxies:
            scraper.proxies = proxies
        r = scraper.get(f"https://avmoo.shop/cn/search/{code}", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        item = soup.find("div", class_="item")
        if not item:
            return None
        movie_link = item.find("a", class_="movie-box")
        if not movie_link:
            return None
        link = movie_link.get("href", "")
        if link.startswith("//"):
            link = f"https:{link}"
        r = scraper.get(link, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        screencap = soup.find("div", class_="screencap")
        if screencap:
            big_img = screencap.find("a", class_="bigImage")
            if big_img and big_img.get("href"):
                logger.info("avmoo poster found for %s: %s", code, big_img["href"])
                return big_img["href"]
        return None
    except Exception as e:
        logger.warning("avmoo error for %s: %s", code, e)
        return None


def download_poster_bytes(url, proxies=None):
    """Download poster image through proxy."""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": url}
    try:
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning("Download poster error: %s", e)
        return None
