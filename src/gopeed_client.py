import logging
import os
import re
import time

import requests

logger = logging.getLogger("tg-download-bot")


class GopeedError(Exception):
    pass


class GopeedClient:
    def __init__(self, url="http://127.0.0.1:9999", token=None):
        self.base_url = url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        self.session.trust_env = False

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-Api-Token"] = self.token
        return h

    def _api(self, method, path, data=None, params=None):
        url = self.base_url + path
        try:
            resp = self.session.request(method, url, json=data, params=params, headers=self._headers(), timeout=30)
        except requests.exceptions.ConnectionError:
            raise GopeedError(f"Cannot connect to Gopeed at {self.base_url}")
        if resp.status_code == 401:
            raise GopeedError("Gopeed API unauthorized")
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise GopeedError(body.get("msg", "Unknown Gopeed API error"))
        return body.get("data")

    def _normalize(self, task):
        meta = task.get("meta", {})
        res = meta.get("res")
        if res is None:
            res = {}
        progress = task.get("progress", {})

        total = res.get("size", 0)
        files = []
        for f in res.get("files", []):
            files.append({
                "path": f.get("path", ""),
                "length": str(f.get("size", 0)),
                "uris": [{"uri": meta.get("req", {}).get("url", "")}],
            })
        if total == 0 and files:
            total = sum(int(f["length"]) for f in files)

        status_map = {
            "ready": "waiting",
            "wait": "waiting",
            "running": "active",
            "pause": "paused",
            "error": "error",
            "done": "complete",
        }
        raw_status = task.get("status", "")
        mapped_status = status_map.get(raw_status, raw_status)

        return {
            "gid": task["id"],
            "status": mapped_status,
            "totalLength": str(total),
            "completedLength": str(progress.get("downloaded", 0)),
            "downloadSpeed": str(progress.get("speed", 0)),
            "files": files,
            "errorMessage": None,
            "bittorrent": {"info": task.get("name", "")} if task.get("protocol") == "bt" else {},
            "_raw": task,
        }

    def ping(self):
        try:
            self._api("GET", "/api/v1/tasks")
            return True
        except Exception:
            return False

    def add_uri(self, uri, options=None):
        data = {"req": {"url": uri}, "opts": {}}
        if options:
            path = options.get("dir") or options.get("path", "")
            if path:
                data["opts"]["path"] = path
            name = options.get("name", "")
            if name:
                data["opts"]["name"] = name
            select = options.get("selectFiles")
            if select:
                data["opts"]["selectFiles"] = [i - 1 for i in select]
        return self._api("POST", "/api/v1/tasks", data)

    def tell_status(self, gid):
        task = self._api("GET", f"/api/v1/tasks/{gid}")
        return self._normalize(task)

    def force_remove(self, gid):
        return self._api("DELETE", f"/api/v1/tasks/{gid}", params={"force": "true"})

    def pause(self, gid):
        return self._api("PUT", f"/api/v1/tasks/{gid}/pause")

    def tell_active(self):
        tasks = self._api("GET", "/api/v1/tasks", params={"status": "running"}) or []
        return [self._normalize(t) for t in tasks]

    def tell_waiting(self, offset=0, num=100):
        tasks = self._api("GET", "/api/v1/tasks", params={"status": "ready,wait"}) or []
        return [self._normalize(t) for t in tasks[offset:offset + num]]

    def tell_stopped(self, offset=0, num=100):
        tasks = self._api("GET", "/api/v1/tasks", params={"status": "done,error"}) or []
        return [self._normalize(t) for t in tasks[offset:offset + num]]

    def remove_download_result(self, gid):
        pass

    def wait_for_metadata(self, gid, timeout=30, interval=1):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                task = self._api("GET", f"/api/v1/tasks/{gid}")
            except GopeedError as e:
                if "not found" in str(e).lower() and time.time() - t0 < timeout:
                    time.sleep(interval)
                    continue
                raise
            status = task.get("status", "")
            if status == "error":
                raise GopeedError(f"Task {gid} failed")
            meta = task.get("meta", {})
            res = meta.get("res")
            if res and res.get("files"):
                files = res["files"]
                gopeed_files = []
                for f in files:
                    gopeed_files.append({
                        "path": f.get("path", ""),
                        "length": str(f.get("size", 0)),
                        "uris": [],
                    })
                return gid, gopeed_files
            if status in ("running", "done"):
                res = meta.get("res") or {}
                files = res.get("files", [])
                if files:
                    gopeed_files = []
                    for f in files:
                        gopeed_files.append({
                            "path": f.get("path", ""),
                            "length": str(f.get("size", 0)),
                            "uris": [],
                        })
                    return gid, gopeed_files
            time.sleep(interval)
        raise GopeedError(f"Timeout waiting for metadata of {gid}")

    def set_select_file(self, gid, indices):
        select = [i - 1 for i in indices]
        try:
            self._api("PATCH", f"/api/v1/tasks/{gid}", {"opts": {"selectFiles": select}})
        except Exception as e:
            logger.warning("set_select_file failed: %s", e)

    def get_files(self, gid):
        task = self._api("GET", f"/api/v1/tasks/{gid}")
        meta = task.get("meta", {})
        res = meta.get("res") or {}
        files = res.get("files", [])
        result = []
        for f in files:
            result.append({
                "path": f.get("path", ""),
                "length": str(f.get("size", 0)),
                "uris": [],
            })
        return result


JUNK_PATTERNS = [
    r'(?i)sample',
    r'(?i)trailer',
    r'(?i)extra',
    r'(?i)\.txt$',
    r'(?i)\.nfo$',
    r'(?i)\.jpg$',
    r'(?i)\.jpeg$',
    r'(?i)\.png$',
    r'(?i)\.gif$',
    r'(?i)\.sfv$',
    r'(?i)\.mht$',
    r'(?i)\.url$',
]


def is_junk_file(filename, size):
    for pat in JUNK_PATTERNS:
        if re.search(pat, filename):
            return True
    return False


def filter_keep_files(gopeed_files, min_main_size=50 * 1024 * 1024):
    keep = []
    for i, f in enumerate(gopeed_files, 1):
        path = f.get("path", "")
        size = int(f.get("length", 0))
        name = os.path.basename(path)
        if not name:
            continue
        if is_junk_file(name, size):
            continue
        if size < min_main_size:
            continue
        keep.append(i)
    return keep


def cleanup_junk_files(path, min_size=60 * 1024 * 1024, keep_largest=1):
    deleted = []
    if not os.path.isdir(path):
        return deleted
    try:
        entries = os.listdir(path)
    except OSError:
        return deleted
    files = []
    for name in entries:
        full = os.path.join(path, name)
        if os.path.isfile(full):
            size = os.path.getsize(full)
            files.append((name, full, size))
    for name, full, size in files:
        if size < min_size:
            try:
                os.remove(full)
                deleted.append(f"File: {name} ({size / 1048576:.1f}MB)")
            except OSError:
                pass
    if keep_largest > 0 and files:
        max_size = max(s for _, _, s in files)
        threshold = max_size * 0.2
        for name, full, size in files:
            if size < threshold:
                try:
                    os.remove(full)
                    deleted.append(f"Suspicious: {name}")
                except OSError:
                    pass
    for name in entries:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            sub = cleanup_junk_files(full, min_size, keep_largest=0)
            deleted.extend(sub)
            try:
                remaining = os.listdir(full)
                if not remaining:
                    os.rmdir(full)
                    deleted.append(f"Dir: {name}")
            except OSError:
                pass
    return deleted
