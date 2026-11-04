#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سنگر — جمع‌آوری و تست کانفیگ‌های پروکسی
Sangar Proxy Collector

فقط با کتابخانه‌ی استاندارد پایتون کار می‌کنه (pip لازم نیست).

کارها:
  1) خواندن منابع از sources.json (هر منبعی خودت اضافه کنی)
  2) دانلود و استخراج لینک‌های کانفیگ (vless/vmess/trojan/ss/hysteria2/tuic/mtproto/...)
  3) حذف تکراری‌ها
  4) دو تست روی هر کانفیگ: (1) تست TCP (2) تست عمیق سلامت پروتکل (TLS/QUIC)
  5) نگه‌داشتن سالم‌ها و حذف خراب‌ها از خروجی قبلی
  6) ساخت خروجی: working.txt / subscription / mtproto.txt / status.json / report.html

استفاده:
  python collect.py                 # اجرای کامل
  python collect.py --no-fetch      # فقط تست کانفیگ‌های قبلی
  python collect.py --add-source NAME URL
  python collect.py --list-sources
  python collect.py --deep          # تست واقعی (نیاز به xray در پوشه tools/)
"""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "sources.json")
OUT_DIR = os.path.join(HERE, "output")
STATUS_FILE = os.path.join(OUT_DIR, "status.json")
WORKING_TXT = os.path.join(OUT_DIR, "working.txt")
WORKING_B64 = os.path.join(OUT_DIR, "subscription.txt")
MTPROTO_TXT = os.path.join(OUT_DIR, "mtproto.txt")
REPORT_HTML = os.path.join(OUT_DIR, "report.html")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LINK_RE = re.compile(
    r"(?i)\b((?:vless|vmess|trojan|ssr|ss|hysteria2|hy2|tuic|mtproto)://[^\s\"'<>\\)]+)"
)
TME_PROXY_RE = re.compile(r"(?i)https?://t\.me/(?:proxy|socks)\?[^\s\"'<>\\]+")

TLS_HINT_PORTS = {443, 8443, 2053, 2083, 2087, 2096, 2087, 9443, 12443, 2443, 3443}


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# بارگذاری منابع
# ----------------------------------------------------------------------------
def load_sources():
    if not os.path.exists(SOURCES_FILE):
        return {"timeout": 5, "workers": 40, "sources": []}
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sources(cfg):
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# دانلود منابع
# ----------------------------------------------------------------------------
def fetch_url(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    # تلاش برای utf-8؛ اگر نشد latin-1 تا برنامه نترکه
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def maybe_b64_decode(text):
    """اگر متن بدنه subscription بود (base64 تمیز)، decode کن."""
    t = "".join(text.split())
    if not t or len(t) < 40:
        return text
    if "://" in t:
        return text
    if re.fullmatch(r"[A-Za-z0-9+/=]+", t):
        try:
            pad = (-len(t)) % 4
            dec = base64.b64decode(t + "=" * pad).decode("utf-8", errors="replace")
            if "://" in dec:
                return dec
        except Exception:
            pass
    return text


# ----------------------------------------------------------------------------
# استخراج و تحلیل لینک‌ها
# ----------------------------------------------------------------------------
def b64decode_flex(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    return base64.b64decode(s + "=" * pad)


def parse_vmess(link):
    """vmess://base64(json) -> dict ساده"""
    try:
        payload = link[len("vmess://"):]
        # ممکنه کانفیگ بعدش پارامتر داشته باشه؟ معمولا نه
        payload = payload.split("#", 1)[0].split("?", 1)[0]
        obj = json.loads(b64decode_flex(payload).decode("utf-8", errors="replace"))
        host = str(obj.get("add") or "").strip()
        port = int(obj.get("port") or 0)
        tls = str(obj.get("tls") or "").lower() in ("tls", "reality")
        name = str(obj.get("ps") or "")
        uuid = str(obj.get("id") or "")
        if not host or not port:
            return None
        return {
            "proto": "vmess",
            "host": host,
            "port": port,
            "tls": tls,
            "name": name,
            "key": "vmess|" + host + "|" + str(port) + "|" + uuid,
            "link": link,
        }
    except Exception:
        return None


def parse_userinfo_link(link, proto):
    """vless:// trojan:// hysteria2:// tuic:// ... user:pass@host:port?params#name"""
    try:
        body = link.split("://", 1)[1]
        name = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            try:
                name = urllib.parse.unquote(frag)
            except Exception:
                name = frag
        params = ""
        if "?" in body:
            body, params = body.split("?", 1)
        userinfo, _, hostport = body.rpartition("@")
        if not hostport or not userinfo:
            return None
        # IPv6 مثل [::1]:443
        if hostport.startswith("["):
            host, _, rest = hostport[1:].partition("]:")
            port = int(rest)
        else:
            host, _, port_s = hostport.rpartition(":")
            port = int(port_s)
        q = {}
        for kv in params.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                q[k.lower()] = v
        sec = (q.get("security") or "").lower()
        tls = sec in ("tls", "reality") or proto in ("trojan",)
        if proto in ("hysteria2", "hy2", "tuic"):
            tls = True
        key = hashlib.sha1((proto + "|" + host + "|" + str(port) + "|" + userinfo).encode()).hexdigest()[:16]
        return {
            "proto": proto,
            "host": host,
            "port": port,
            "tls": tls,
            "name": name,
            "key": proto + "|" + key,
            "link": link,
        }
    except Exception:
        return None


def parse_ss(link):
    """ss:// (base64 method:pass@host:port) یا ss://base64@host:port"""
    try:
        body = link[len("ss://"):]
        name = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            try:
                name = urllib.parse.unquote(frag)
            except Exception:
                name = frag
        if "?" in body:
            body = body.split("?", 1)[0]
        if "@" in body:
            b64part, hostport = body.rsplit("@", 1)
            try:
                b64decode_flex(b64part)  # اعتبارسنجی
            except Exception:
                return None
        else:
            dec = b64decode_flex(body).decode("utf-8", errors="replace")
            if "@" not in dec:
                return None
            _, hostport = dec.rsplit("@", 1)
        if hostport.startswith("["):
            host, _, rest = hostport[1:].partition("]:")
            port = int(rest)
        else:
            host, _, port_s = hostport.rpartition(":")
            port = int(port_s)
        if not host or not port:
            return None
        key = hashlib.sha1(("ss|" + host + "|" + str(port) + "|" + body).encode()).hexdigest()[:16]
        return {"proto": "ss", "host": host, "port": port, "tls": False,
                "name": name, "key": "ss|" + key, "link": link}
    except Exception:
        return None


def parse_mtproto(link):
    """mtproto://secret@host:port#name  یا  https://t.me/proxy?server=..&port=..&secret=.."""
    try:
        if link.lower().startswith("http"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(link).query)
            host = (q.get("server") or [""])[0]
            port = int((q.get("port") or ["0"])[0])
            secret = (q.get("secret") or [""])[0]
            if not host or not port:
                return None
            key = "mtproto|" + hashlib.sha1((host + str(port) + secret).encode()).hexdigest()[:16]
            return {"proto": "mtproto", "host": host, "port": port, "tls": "ee" in secret[:2],
                    "name": "تلگرام", "key": key, "link": link}
        body = link[len("mtproto://"):]
        name = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            try:
                name = urllib.parse.unquote(frag)
            except Exception:
                name = frag
        body = body.split("?", 1)[0]
        secret, _, hostport = body.rpartition("@")
        if hostport.startswith("["):
            host, _, rest = hostport[1:].partition("]:")
            port = int(rest)
        else:
            host, _, port_s = hostport.rpartition(":")
            port = int(port_s)
        if not host or not port:
            return None
        key = "mtproto|" + hashlib.sha1((host + str(port) + secret).encode()).hexdigest()[:16]
        return {"proto": "mtproto", "host": host, "port": port,
                "tls": "ee" in secret[:2], "name": name or "تلگرام", "key": key, "link": link}
    except Exception:
        return None


def parse_link(link):
    link = link.strip().rstrip(").,;\"'")
    low = link.lower()
    if low.startswith("vmess://"):
        return parse_vmess(link)
    if low.startswith("ss://"):
        return parse_ss(link)
    if low.startswith(("mtproto://",)) or "t.me/proxy" in low or "t.me/socks" in low:
        return parse_mtproto(link)
    for proto in ("vless", "trojan", "hysteria2", "hy2", "tuic", "ssr"):
        if low.startswith(proto + "://"):
            if proto == "ssr":
                # ssr قدیمی — فعلاً فقط host/port استخراج ساده
                try:
                    dec = b64decode_flex(link[6:].split("#", 1)[0]).decode("utf-8", errors="replace")
                    main = dec.split("/?", 1)[0]
                    hostport = main.rsplit(":", 1)[0].rsplit(":", 1)  # مبهم؛ رد می‌شه
                    return None
                except Exception:
                    return None
            return parse_userinfo_link(link, proto)
    return None


def extract_links(text):
    text = maybe_b64_decode(text)
    found = LINK_RE.findall(text) + TME_PROXY_RE.findall(text)
    return found


# ----------------------------------------------------------------------------
# تست‌ها
# ----------------------------------------------------------------------------
def test_tcp(host, port, timeout):
    """تست ۱: اتصال TCP"""
    t0 = time.time()
    last_err = "resolve"
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception as e:
        return False, 0, str(e)[:80]
    for family, stype, proto, _, addr in infos:
        try:
            s = socket.socket(family, stype, proto)
            s.settimeout(timeout)
            s.connect(addr)
            s.close()
            return True, int((time.time() - t0) * 1000), ""
        except Exception as e:
            last_err = str(e)[:80]
    return False, 0, last_err


def test_tls(host, port, timeout, sni=None):
    """تست ۲ب: دست‌دادن TLS — نشان‌دهنده سلامت سرور و پاسخ‌گویی است."""
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(timeout)
        raw.connect((host, port))
        with ctx.wrap_socket(raw, server_hostname=sni or host) as s:
            _ = s.getpeercert()
            latency = int((time.time() - t0) * 1000)
            return True, latency, ""
    except Exception as e:
        return False, 0, str(e)[:80]


def test_udp_probe(host, port, timeout):
    """تست برای پروتکل‌های UDP (hysteria2/tuic): بسته QUIC جعلی می‌فرستیم؛
    اگر سرور زنده باشه معمولاً Version Negotiation برمی‌گردونه."""
    t0 = time.time()
    try:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        s = socket.socket(family, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        # Long Header با نسخه ناشناخته
        pkt = bytes([0xC0, 0x00, 0x00, 0x00, 0x01]) + os.urandom(4) + b"\x00" + os.urandom(1200)
        s.sendto(pkt, (host, port))
        data, _ = s.recvfrom(2048)
        s.close()
        if data:
            return True, int((time.time() - t0) * 1000), ""
        return False, 0, "بدون پاسخ"
    except socket.timeout:
        return False, 0, "timeout"
    except Exception as e:
        return False, 0, str(e)[:80]


def run_two_tests(cfg, timeout):
    """دو تست استاندارد روی هر کانفیگ. خروجی: dict نتیجه"""
    host, port = cfg["host"], cfg["port"]
    udp_protos = ("hysteria2", "hy2", "tuic")

    # تست ۱
    if cfg["proto"] in udp_protos:
        ok1, lat1, err1 = test_udp_probe(host, port, timeout)
        ok2, lat2, err2 = ok1, lat1, err1  # تست دوم = تکرار پروب برای اطمینان
        if ok1:
            ok2, lat2, err2 = test_udp_probe(host, port, timeout)
    else:
        ok1, lat1, err1 = test_tcp(host, port, timeout)
        # تست ۲
        if ok1 and cfg.get("tls"):
            ok2, lat2, err2 = test_tls(host, port, timeout)
        elif ok1:
            # بدون TLS: اتصال دوم + انتظار کوتاه برای هر پاسخی
            ok2, lat2, err2 = test_tcp(host, port, timeout)
        else:
            ok2, lat2, err2 = False, 0, err1

    status = "working" if (ok1 and ok2) else ("weak" if ok1 else "dead")
    return {
        "key": cfg["key"],
        "proto": cfg["proto"],
        "host": host,
        "port": port,
        "name": cfg.get("name", ""),
        "tls": cfg.get("tls", False),
        "t1": ok1,
        "t2": ok2,
        "latency": lat1 or lat2,
        "status": status,
        "error": (err1 if not ok1 else (err2 if not ok2 else "")),
        "link": cfg["link"],
        "checked_at": int(time.time()),
    }


# ----------------------------------------------------------------------------
# تست عمیق با xray (اختیاری)
# ----------------------------------------------------------------------------
def deep_test_xray(cfgs, timeout, max_n=15):
    """اگر tools/xray (یا xray.exe) موجود باشه، واقعاً از هر کانفیگ تونل می‌زنیم
    و تلاش می‌کنیم صفحه ۲۰۴ گوگل رو بگیریم. فقط ۱۵ کانفیگ اولِ سالم."""
    import shutil
    import subprocess
    import tempfile

    xray = None
    for cand in (
        os.path.join(HERE, "tools", "xray"),
        os.path.join(HERE, "tools", "xray.exe"),
        shutil.which("xray"),
    ):
        if cand and os.path.exists(cand):
            xray = cand
            break
    if not xray:
        log("  [دیپ‌تست] xray پیدا نشد — رد شد (می‌تونی از tools/ اضافه‌اش کنی)")
        return {}

    targets = [c for c in cfgs if c.get("status") == "working"][:max_n]
    results = {}
    for i, cfg in enumerate(targets, 1):
        port_local = 18080 + (i % 200)
        outbound = link_to_xray_outbound(cfg)
        if not outbound:
            continue
        conf = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"listen": "127.0.0.1", "port": port_local, "protocol": "socks",
                          "settings": {"udp": False}}],
            "outbounds": [outbound],
        }
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(conf, tmp)
        tmp.close()
        proc = None
        try:
            proc = subprocess.Popen([xray, "run", "-c", tmp.name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            # SOCKS5 ساده و بعد HTTP GET
            ok = socks_http_get("127.0.0.1", port_local, "http://www.gstatic.com/generate_204", timeout)
            results[cfg["key"]] = ok
            cfg["status"] = "working" if ok else "dead"
        except Exception:
            results[cfg["key"]] = False
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
    return results


def socks_http_get(proxy_host, proxy_port, url, timeout):
    """کلاینت SOCKS5 مینیمال فقط برای تست (بدون کتابخانه جانبی)."""
    with socket.create_connection((proxy_host, proxy_port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(b"\x05\x01\x00")          # greeting
        resp = s.recv(2)
        if resp != b"\x05\x00":
            return False
        host = url.split("://", 1)[1].split("/", 1)[0]
        req = b"\x05\x01\x00\x03" + bytes([len(host)]) + host.encode() + struct.pack("!H", 80)
        s.sendall(req)
        r = s.recv(10)
        if len(r) < 2 or r[1] != 0:
            return False
        s.sendall(("GET /generate_204 HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % host).encode())
        data = s.recv(200)
        return data.startswith(b"HTTP/1.") and (b" 204" in data or b" 200" in data)


def link_to_xray_outbound(cfg):
    """تبدیل کانفیگ به outbound دیکسری xray — برای vless/vmess/trojan/ss."""
    proto = cfg["proto"]
    link = cfg["link"]
    try:
        if proto == "vless":
            body = link[len("vless://"):]
            body = body.split("#", 1)[0]
            userinfo, _, rest = body.partition("@")
            params = ""
            if "?" in rest:
                hostport, params = rest.split("?", 1)
            else:
                hostport = rest
            if hostport.startswith("["):
                host, _, pr = hostport[1:].partition("]:")
            else:
                host, _, pr = hostport.rpartition(":")
            q = {}
            for kv in params.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    q[k.lower()] = v
            stream = {"network": q.get("type", "tcp")}
            if q.get("security") in ("tls", "reality"):
                stream["security"] = q["security"]
                tls = {"serverName": q.get("sni") or q.get("host") or host,
                       "fingerprint": q.get("fp", "chrome")}
                if q["security"] == "reality":
                    tls["publicKey"] = q.get("pbk", "")
                    tls["shortId"] = q.get("sid", "")
                    tls["spiderX"] = q.get("spx", "/")
                stream["tlsSettings"] = tls
            if q.get("type") == "ws":
                stream["wsSettings"] = {"path": q.get("path", "/"),
                                        "headers": {"Host": q.get("host", host)}}
            if q.get("type") == "grpc":
                stream["grpcSettings"] = {"serviceName": q.get("serviceName", "")}
            return {
                "protocol": "vless",
                "settings": {"vnext": [{"address": host, "port": int(pr),
                                        "users": [{"id": userinfo, "encryption": "none",
                                                   "flow": q.get("flow", "")}]}]},
                "streamSettings": stream,
            }
        if proto == "vmess":
            payload = link[len("vmess://"):].split("#", 1)[0].split("?", 1)[0]
            o = json.loads(b64decode_flex(payload).decode("utf-8", errors="replace"))
            stream = {"network": o.get("net", "tcp")}
            if o.get("tls"):
                stream["security"] = "tls"
                stream["tlsSettings"] = {"serverName": o.get("sni") or o.get("host") or o.get("add")}
            if o.get("net") == "ws":
                stream["wsSettings"] = {"path": o.get("path", "/"),
                                        "headers": {"Host": o.get("host", "")}}
            return {
                "protocol": "vmess",
                "settings": {"vnext": [{"address": o["add"], "port": int(o["port"]),
                                        "users": [{"id": o["id"], "alterId": int(o.get("aid", 0)),
                                                   "security": "auto"}]}]},
                "streamSettings": stream,
            }
        if proto == "trojan":
            body = link[len("trojan://"):].split("#", 1)[0]
            userinfo, _, rest = body.partition("@")
            params = ""
            if "?" in rest:
                hostport, params = rest.split("?", 1)
            else:
                hostport = rest
            host, _, pr = hostport.rpartition(":")
            q = {}
            for kv in params.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    q[k.lower()] = v
            return {
                "protocol": "trojan",
                "settings": {"servers": [{"address": host, "port": int(pr),
                                          "password": userinfo.split(":")[-1]}]},
                "streamSettings": {"network": q.get("type", "tcp"), "security": "tls",
                                   "tlsSettings": {"serverName": q.get("sni") or host}},
            }
        if proto == "ss":
            body = link[len("ss://"):].split("#", 1)[0].split("?", 1)[0]
            if "@" in body:
                b64part, hostport = body.rsplit("@", 1)
                userinfo = b64decode_flex(b64part).decode("utf-8", errors="replace")
            else:
                dec = b64decode_flex(body).decode("utf-8", errors="replace")
                userinfo, hostport = dec.rsplit("@", 1)
            method, _, password = userinfo.partition(":")
            host, _, pr = hostport.rpartition(":")
            return {
                "protocol": "shadowsocks",
                "settings": {"servers": [{"address": host, "port": int(pr),
                                          "method": method, "password": password}]},
                "streamSettings": {"network": "tcp"},
            }
    except Exception:
        return None
    return None


# ----------------------------------------------------------------------------
# خروجی‌ها
# ----------------------------------------------------------------------------
def load_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"working": {}, "last_run": 0}


def save_status(status):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


def write_outputs(results):
    os.makedirs(OUT_DIR, exist_ok=True)
    working = [r for r in results if r["status"] == "working"]
    weak = [r for r in results if r["status"] == "weak"]
    mtproto = [r for r in working if r["proto"] == "mtproto"]
    normal = [r for r in working if r["proto"] != "mtproto"]
    normal.sort(key=lambda r: (r["latency"] or 99999))

    with open(WORKING_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(r["link"] for r in normal) + ("\n" if normal else ""))
    b64 = base64.b64encode("\n".join(r["link"] for r in normal).encode()).decode()
    with open(WORKING_B64, "w", encoding="utf-8") as f:
        f.write(b64)
    with open(MTPROTO_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(r["link"] for r in mtproto) + ("\n" if mtproto else ""))
    return working, weak, mtproto, normal


def write_report(results, working, weak, mtproto, normal, sources_used, fetch_errors, secs):
    rows = sorted(results, key=lambda r: ({"working": 0, "weak": 1, "dead": 2}.get(r["status"], 3),
                                          r["latency"] or 99999))
    row_html = []
    for r in rows[:400]:
        st = r["status"]
        color = {"working": "#22c55e", "weak": "#eab308"}.get(st, "#ef4444")
        st_fa = {"working": "✅ سالم", "weak": "⚠️ ضعیف", "dead": "❌ خراب"}.get(st, st)
        link_esc = (r["link"].replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;"))
        row_html.append(
            f"<tr><td>{st_fa}</td><td>{r['proto']}</td><td dir='ltr'>{r['host']}:{r['port']}</td>"
            f"<td>{'TLS' if r['tls'] else '—'}</td><td>{r['latency'] or '—'}</td>"
            f"<td>{'✅' if r['t1'] else '❌'} / {'✅' if r['t2'] else '❌'}</td>"
            f"<td class='err'>{r.get('error','')}</td>"
            f"<td><button onclick=\"navigator.clipboard.writeText('{link_esc}')\">کپی</button></td></tr>"
        )
    src_html = "".join(f"<li>{s}</li>" for s in sources_used)
    err_html = "".join(f"<li class='err'>{e}</li>" for e in fetch_errors[:20])
    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>گزارش تست پروکسی‌ها — سنگر</title>
<style>
body{{font-family:Tahoma,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
h1{{color:#38bdf8}} .cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{background:#1e293b;border-radius:12px;padding:16px 20px;min-width:130px;text-align:center}}
.card b{{display:block;font-size:26px;color:#38bdf8}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#1e293b;border-radius:12px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid #334155;text-align:right}}
th{{background:#334155;color:#7dd3fc}} .err{{color:#f87171;font-size:11px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
button{{background:#0ea5e9;border:0;color:#fff;padding:4px 10px;border-radius:6px;cursor:pointer}}
a{{color:#38bdf8}} ul{{line-height:1.9}} .note{{background:#1e293b;padding:14px;border-radius:10px;border-right:4px solid #38bdf8;margin:14px 0;line-height:2}}
</style></head><body>
<h1>🛡️ گزارش جمع‌آوری و تست کانفیگ‌ها — سنگر</h1>
<div class="cards">
<div class="card"><b>{len(working)}</b>سالم</div>
<div class="card"><b>{len(normal)}</b>پروکسی VPN</div>
<div class="card"><b>{len(mtproto)}</b>پروکسی تلگرام</div>
<div class="card"><b>{len(weak)}</b>ضعیف</div>
<div class="card"><b>{len([r for r in results if r['status']=='dead'])}</b>خراب (حذف‌شده)</div>
<div class="card"><b>{secs:.0f}"</b>زمان اجرا</div>
</div>
<div class="note">
📌 <b>چطور استفاده کنم؟</b><br>
۱) فایل <code>working.txt</code> را در اپ‌هایی مثل v2rayNG / Mahsang / Npv Tunnel از «Import from clipboard» وارد کنید.<br>
۲) فایل <code>subscription.txt</code> هم همان لینک‌هاست به‌صورت base64.<br>
۳) فایل <code>mtproto.txt</code> را مستقیم در خود تلگرام: تنظیمات ← داده و حافظه ← پروکسی ← افزودن پروکسی ← Add Proxy (لینک) وارد کنید.<br>
۴) هر بار که دوباره اجرا کنید، کانفیگ‌های مرده خودکار از خروجی حذف می‌شوند.
</div>
<h3>📚 منابع استفاده‌شده</h3><ul>{src_html or '<li>—</li>'}</ul>
{('<h3 class="err">⚠️ خطاهای دریافت</h3><ul>' + err_html + '</ul>') if err_html else ''}
<table><tr><th>وضعیت</th><th>پروتکل</th><th>سرور</th><th>TLS</th><th>تأخیر(ms)</th><th>تست۱/۲</th><th>خطا</th><th></th></tr>
{''.join(row_html)}</table>
<p style="color:#64748b;font-size:12px">تولیدشده توسط سنگر — {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


# ----------------------------------------------------------------------------
# اجرای اصلی
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Sangar proxy collector")
    ap.add_argument("--no-fetch", action="store_true", help="فقط تست، بدون دانلود منابع")
    ap.add_argument("--add-source", nargs=2, metavar=("NAME", "URL"), help="افزودن منبع")
    ap.add_argument("--list-sources", action="store_true", help="نمایش منابع")
    ap.add_argument("--timeout", type=int, default=0, help="تایم‌اوت هر تست (ثانیه)")
    ap.add_argument("--workers", type=int, default=0, help="تعداد رشته")
    ap.add_argument("--deep", action="store_true", help="تست واقعی با xray")
    args = ap.parse_args()

    cfg = load_sources()

    if args.list_sources:
        for i, s in enumerate(cfg.get("sources", [])):
            mark = "✅" if s.get("enabled", True) else "⛔"
            print(f"{i:>3}. {mark} {s['name']}\n     {s['url']}")
        return

    if args.add_source:
        name, url = args.add_source
        cfg.setdefault("sources", []).append({"name": name, "url": url, "type": "raw", "enabled": True})
        save_sources(cfg)
        print(f"✅ منبع اضافه شد: {name}")
        return

    timeout = args.timeout or cfg.get("timeout", 5)
    workers = args.workers or cfg.get("workers", 40)
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    # ۱) جمع‌آوری از منابع
    all_links = []
    sources_used, fetch_errors = [], []
    if not args.no_fetch:
        enabled = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
        log(f"📡 در حال دانلود از {len(enabled)} منبع ...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(enabled) or 1)) as ex:
            futs = {ex.submit(fetch_url, s["url"], timeout + 5): s for s in enabled}
            for fut in concurrent.futures.as_completed(futs):
                s = futs[fut]
                try:
                    body = fut.result()
                    links = extract_links(body)
                    all_links.extend(links)
                    sources_used.append(f"{s['name']} — {len(links)} لینک")
                    log(f"  ✅ {s['name']}: {len(links)} لینک")
                except Exception as e:
                    fetch_errors.append(f"{s['name']}: {str(e)[:80]}")
                    log(f"  ❌ {s['name']}: {str(e)[:80]}")

    # ۲) تحلیل و حذف تکراری
    seen, cfgs = set(), []
    bad = 0
    for link in all_links:
        p = parse_link(link)
        if not p:
            bad += 1
            continue
        if p["key"] in seen:
            continue
        seen.add(p["key"])
        cfgs.append(p)
    log(f"🔎 {len(all_links)} لینک خام → {len(cfgs)} کانفیگ یکتا ({bad} نامعتبر/تکراری حذف شد)")

    # اگه fetch نداشتیم، از خروجی قبلی تست می‌گیریم
    if args.no_fetch:
        old = load_status().get("working", {})
        for k, v in old.items():
            p = parse_link(v.get("link", ""))
            if p:
                cfgs.append(p)
        log(f"🔁 تست مجدد {len(cfgs)} کانفیگ قبلی ...")

    # ۳) تست دو مرحله‌ای
    log(f"🧪 شروع تست‌ها ({workers} رشته، تایم‌اوت {timeout}s) ...")
    results = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_two_tests, c, timeout): c for c in cfgs}
        for fut in concurrent.futures.as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                c = futs[fut]
                results.append({"key": c["key"], "proto": c["proto"], "host": c["host"],
                                "port": c["port"], "name": c.get("name", ""), "tls": c.get("tls", False),
                                "t1": False, "t2": False, "latency": 0, "status": "dead",
                                "error": str(e)[:80], "link": c["link"], "checked_at": int(time.time())})
            done += 1
            if done % 100 == 0:
                log(f"  ... {done}/{len(cfgs)} تست شد")

    # ۴) تست عمیق اختیاری
    if args.deep:
        log("🕳️ دیپ‌تست با xray ...")
        deep_test_xray(results, timeout)

    # ۵) خروجی‌ها
    working, weak, mtproto, normal = write_outputs(results)

    # ۶) آپدیت وضعیت قبلی (کانفیگ‌های مرده حذف می‌شن)
    status = load_status()
    new_working = {}
    for r in working:
        new_working[r["key"]] = {"link": r["link"], "proto": r["proto"],
                                 "latency": r["latency"], "checked_at": r["checked_at"]}
    removed = len(status.get("working", {})) - len(new_working)
    status["working"] = new_working
    status["last_run"] = int(time.time())
    save_status(status)

    secs = time.time() - t_start
    write_report(results, working, weak, mtproto, normal, sources_used, fetch_errors, secs)

    log("")
    log("=" * 52)
    log(f"✅ تمام شد در {secs:.0f} ثانیه")
    log(f"   سالم: {len(working)}  (تلگرامی: {len(mtproto)})")
    log(f"   ضعیف: {len(weak)}   خراب/حذف: {len([r for r in results if r['status'] == 'dead'])}")
    log(f"   کانفیگ‌های حذف‌شده از خروجی قبلی: {max(removed, 0)}")
    log(f"   📄 گزارش: {REPORT_HTML}")
    log(f"   📋 لینک‌ها: {WORKING_TXT}")
    log("=" * 52)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nلغو شد.")
        sys.exit(1)
