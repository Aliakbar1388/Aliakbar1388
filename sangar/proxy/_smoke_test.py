#!/usr/bin/env python3
# تست دود (smoke test) برای collect.py — فقط برای توسعه
import base64
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PLAIN_PORT = 19001
TLS_PORT = 19002
HTTP_PORT = 18888

procs = []


def tcp_echo(port, tls_ctx=None):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(50)
    s.settimeout(0.5)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                c, _ = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                if tls_ctx:
                    c = tls_ctx.wrap_socket(c, server_side=True)
                c.settimeout(2)
                try:
                    c.recv(64)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                c.close()
            except Exception:
                pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return stop, s


def main():
    os.chdir(HERE)
    # گواهی self-signed
    cert = os.path.join(HERE, "_test_cert.pem")
    key = os.path.join(HERE, "_test_key.pem")
    has_openssl = subprocess.call(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                                   "-keyout", key, "-out", cert, "-days", "2", "-nodes",
                                   "-subj", "/CN=localhost"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    stop1, s1 = tcp_echo(PLAIN_PORT)
    stop2 = s2 = None
    if has_openssl:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        stop2, s2 = tcp_echo(TLS_PORT, ctx)

    # سرویس لینک‌های نمونه
    ss_plain = "ss://" + base64.b64encode(b"aes-256-gcm:testpass").decode() + f"@127.0.0.1:{PLAIN_PORT}#ss-plain"
    vless_tls = f"vless://11111111-1111-1111-1111-111111111111@127.0.0.1:{TLS_PORT}?type=tcp&security=tls&sni=localhost#vless-tls"
    vmess_obj = {"v": "2", "ps": "vmess-plain", "add": "127.0.0.1", "port": str(PLAIN_PORT),
                 "id": "22222222-2222-2222-2222-222222222222", "aid": "0",
                 "net": "tcp", "type": "none", "tls": ""}
    vmess = "vmess://" + base64.b64encode(json.dumps(vmess_obj).encode()).decode()
    mtproto = f"mtproto://0123456789abcdef0123456789abcdef@127.0.0.1:{PLAIN_PORT}#mt-test"
    dead = "trojan://password123@127.0.0.1:9#dead-one"
    dead_udp = "hysteria2://pw@127.0.0.1:9999#dead-udp"
    tme = f"https://t.me/proxy?server=127.0.0.1&port={PLAIN_PORT}&secret=0123456789abcdef"

    lines = [ss_plain, vless_tls, vmess, mtproto, dead, dead_udp, tme,
             "vless://broken-link-without-host", ss_plain, "   "]
    body = "\n".join(lines) + "\n"

    httpd_root = os.path.join(HERE, "_test_http")
    os.makedirs(httpd_root, exist_ok=True)
    with open(os.path.join(httpd_root, "configs.txt"), "w") as f:
        f.write(body)
    # منبع دوم: بدنه base64 (نوع sub)
    with open(os.path.join(httpd_root, "sub.txt"), "w") as f:
        f.write(base64.b64encode(body.encode()).decode())

    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=httpd_root, **k)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)

    # sources.json موقت
    src_file = os.path.join(HERE, "sources.json")
    backup = open(src_file, "r", encoding="utf-8").read()
    test_sources = {
        "timeout": 3, "workers": 16,
        "sources": [
            {"name": "TEST-raw", "url": f"http://127.0.0.1:{HTTP_PORT}/configs.txt", "type": "raw", "enabled": True},
            {"name": "TEST-sub", "url": f"http://127.0.0.1:{HTTP_PORT}/sub.txt", "type": "raw", "enabled": True},
        ],
    }
    with open(src_file, "w", encoding="utf-8") as f:
        json.dump(test_sources, f, ensure_ascii=False, indent=2)

    try:
        out = subprocess.run([sys.executable, "collect.py", "--timeout", "3"],
                             capture_output=True, text=True, timeout=120)
        print(out.stdout)
        print(out.stderr, file=sys.stderr)
        assert out.returncode == 0, "collect exit != 0"

        # بررسی خروجی‌ها
        def rd(p):
            with open(os.path.join(HERE, "output", p), encoding="utf-8") as f:
                return f.read()

        working = rd("working.txt")
        mt = rd("mtproto.txt")
        rep = rd("report.html")
        st = json.loads(rd("status.json"))

        checks = []
        checks.append(("ss در working", ss_plain in working))
        checks.append(("vmess در working", vmess in working))
        if has_openssl:
            checks.append(("vless-tls در working", vless_tls in working))
        checks.append(("dead در working نیست", dead not in working and dead_udp not in working))
        checks.append(("mtproto در mtproto.txt", mtproto in mt))
        checks.append(("tme در mtproto.txt", tme.split("#")[0] in mt or "t.me/proxy" in mt))
        checks.append(("status.json حاوی working", len(st.get("working", {})) >= 2))
        checks.append(("report ساخته شد", "گزارش" in rep and len(rep) > 1000))
        checks.append(("لینک خراب رد شد", "broken-link" not in working))

        # حذف تکراری: ss فقط یک‌بار (دو منبع یکسان)
        checks.append(("حذف تکراری", working.count("@127.0.0.1:%d" % PLAIN_PORT) <= 3))

        # تست no-fetch
        out2 = subprocess.run([sys.executable, "collect.py", "--no-fetch", "--timeout", "3"],
                              capture_output=True, text=True, timeout=120)
        checks.append(("no-fetch موفق", out2.returncode == 0))

        # افزودن منبع
        out3 = subprocess.run([sys.executable, "collect.py", "--add-source", "MY-SRC",
                               "https://example.com/x.txt"], capture_output=True, text=True, timeout=30)
        checks.append(("add-source موفق", out3.returncode == 0 and "MY-SRC" in open(src_file).read()))

        # فهرست منابع
        out4 = subprocess.run([sys.executable, "collect.py", "--list-sources"],
                              capture_output=True, text=True, timeout=30)
        checks.append(("list-sources موفق", out4.returncode == 0 and "TEST-raw" in out4.stdout))

        print("\n--- نتایج ---")
        all_ok = True
        for name, ok in checks:
            print(("  ✅ " if ok else "  ❌ ") + name)
            all_ok = all_ok and ok

        # خروجی‌های تستی را پاک کن تا به گیت نرود
        for f in ("working.txt", "subscription.txt", "mtproto.txt", "status.json", "report.html"):
            p = os.path.join(HERE, "output", f)
            if os.path.exists(p):
                os.unlink(p)
        sys.exit(0 if all_ok else 1)
    finally:
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(backup)
        stop1.set()
        if stop2:
            stop2.set()
        httpd.shutdown()
        for p in (cert, key):
            if os.path.exists(p):
                os.unlink(p)
        import shutil
        shutil.rmtree(httpd_root, ignore_errors=True)


if __name__ == "__main__":
    main()
