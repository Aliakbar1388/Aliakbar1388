#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سنگر — روشن‌کردن پروکسی دسکتاپ با xray
کانفیگ سالم را از output/status.json برمی‌دارد، با xray اجرا می‌کند و
یک پروکسی محلی SOCKS (10808) + HTTP (10809) می‌سازد.

با این پروکسی: گوگل، گیت‌هاب، تلگرامِ دسکتاپ — همه باز می‌شوند.

نیاز: یک کانفیگِ سالم از collect.py + باینری xray
(اگر xray نباشد خودش از GitHub دانلود می‌کند)

اجرا:
  python start_proxy.py            بهترین کانفیگ
  python start_proxy.py --index 3  سومین کانفیگ
  python start_proxy.py --list     نمایش کانفیگ‌های سالم
"""

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from collect import link_to_xray_outbound, socks_http_get  # noqa: E402

STATUS_FILE = os.path.join(HERE, "output", "status.json")
TOOLS_DIR = os.path.join(HERE, "tools")
SOCKS_PORT = 10808
HTTP_PORT = 10809
HEALTH_URL = "http://www.gstatic.com/generate_204"
XRAY_RELEASE = "https://github.com/XTLS/Xray-core/releases/latest/download/"


def log(m):
    print(m, flush=True)


def xray_path():
    name = "xray.exe" if platform.system() == "Windows" else "xray"
    cand = os.path.join(TOOLS_DIR, name)
    if os.path.exists(cand):
        return cand
    w = shutil.which("xray")
    return w


def download_xray():
    """دانلود باینری xray از GitHub (روی سیستم کاربر، هنگام اجرا)."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        fname = "Xray-windows-64.zip"
        if machine in ("arm64", "aarch64"):
            fname = "Xray-windows-arm64.zip"
    elif system == "Darwin":
        fname = "Xray-macos-64.zip"
        if machine in ("arm64", "aarch64"):
            fname = "Xray-macos-arm64-v8a.zip"
    else:
        fname = "Xray-linux-64.zip"
        if machine in ("aarch64", "arm64"):
            fname = "Xray-linux-arm64-v8a.zip"
        elif machine == "armv7l":
            fname = "Xray-linux-arm32-v7a.zip"

    url = XRAY_RELEASE + fname
    log(f"⬇️ دانلود xray: {url}")
    os.makedirs(TOOLS_DIR, exist_ok=True)
    zip_path = os.path.join(TOOLS_DIR, "xray.zip")
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(TOOLS_DIR)
        os.unlink(zip_path)
        name = "xray.exe" if system == "Windows" else "xray"
        p = os.path.join(TOOLS_DIR, name)
        if os.path.exists(p) and system != "Windows":
            os.chmod(p, 0o755)
        log("✅ xray آماده شد.")
        return p
    except Exception as e:
        log(f"[X] دانلود xray ناموفق بود: {e}")
        log("    دستی دانلود کن و در پوشه proxy/tools بگذار:")
        log("    https://github.com/XTLS/Xray-core/releases")
        return None


def load_working():
    if not os.path.exists(STATUS_FILE):
        return []
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    items = list(st.get("working", {}).values())
    items.sort(key=lambda x: x.get("latency") or 999999)
    return items


def build_config(link):
    # ساخت‌وساز outbound از collect.py قرض گرفته می‌شود
    from collect import parse_link
    cfg = parse_link(link)
    if not cfg:
        return None
    outb = link_to_xray_outbound(cfg)
    if not outb:
        return None
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "socks", "listen": "127.0.0.1", "port": SOCKS_PORT,
             "protocol": "socks", "settings": {"udp": True}},
            {"tag": "http", "listen": "127.0.0.1", "port": HTTP_PORT,
             "protocol": "http", "settings": {}},
        ],
        "outbounds": [outb, {"tag": "direct", "protocol": "freedom"}],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0, help="شماره کانفیگ از لیست سالم")
    ap.add_argument("--list", action="store_true", help="فهرست کانفیگ‌های سالم")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    items = load_working()
    if not items:
        log("[X] کانفیگ سالمی نیست. اول collect.py را اجرا کن (run.bat).")
        sys.exit(1)

    if args.list:
        for i, it in enumerate(items[:30]):
            log(f"{i:>3}. {it.get('proto','?'):<9} {it.get('latency','?'):>6} ms")
        return

    xray = xray_path() or (None if args.no_download else download_xray())
    if not xray:
        sys.exit(1)

    choice = items[args.index] if args.index < len(items) else items[0]
    conf = build_config(choice.get("link", ""))
    if not conf:
        log("[X] تبدیل کانفیگ ناموفق بود. کانفیگ بعدی را با --index امتحان کن.")
        sys.exit(1)

    conf_path = os.path.join(TOOLS_DIR, "current_config.json")
    os.makedirs(TOOLS_DIR, exist_ok=True)
    with open(conf_path, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=1)

    log(f"🚀 اجرای xray با کانفیگ: {choice.get('proto')} {choice.get('latency')}ms ...")
    proc = subprocess.Popen([xray, "run", "-c", conf_path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")

    time.sleep(1.5)
    if proc.poll() is not None:
        log("[X] xray بالا نیامد. خروجی:")
        try:
            log(proc.stdout.read()[:1500])
        except Exception:
            pass
        sys.exit(1)

    ok = False
    for attempt in range(5):
        try:
            if socks_http_get("127.0.0.1", SOCKS_PORT, HEALTH_URL, 6):
                ok = True
                break
        except Exception:
            pass
        time.sleep(1)

    print()
    print("=" * 56)
    if ok:
        print("✅ پروکسی روشن است و تست سلامت را رد کرد!")
    else:
        print("⚠️ پروکسی روشن شد ولی تست سلامت موفق نبود — کانفیگ بعدی را امتحان کن:")
        print(f"   python start_proxy.py --index {args.index + 1}")
    print(f"   SOCKS5 : 127.0.0.1:{SOCKS_PORT}")
    print(f"   HTTP   : 127.0.0.1:{HTTP_PORT}")
    print("-" * 56)
    print("📡 برای باز شدن گوگل/گیت‌هاب در ویندوز:")
    print(f"   ۱) tools\\set_system_proxy.bat را اجرا کن (فقط یک‌بار)")
    print("   یا مرورگر را این‌طوری باز کن:")
    print('   chrome.exe --proxy-server="socks5://127.0.0.1:10808"')
    print("📡 تلگرام دسکتاپ: Settings → Advanced → Connection → Use custom proxy")
    print(f"   نوع SOCKS5، آدرس 127.0.0.1 پورت {SOCKS_PORT}")
    print("📡 تلگرام موبایل: پوشه proxy/output/mtproto.txt (لینک‌ها را در تلگرام Import کن)")
    print("=" * 56)
    print("برای توقف: Ctrl+C")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
