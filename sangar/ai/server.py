#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سنگر — سرور هوش مصنوعی محلی (بدون API، فقط آفلاین)

  • چت با مدل محلی Ollama (فارسی/انگلیسی)
  • دفترچه‌ی دانش (NotebookLM-مانند): فایل‌ها رو بده، روی‌هاشون سؤال بپرس
  • حالت درس و حالت کدنویسی
  • کاملاً آفلاین — بدون اینترنت، بدون API Key

اجرا:
  python server.py                # پورت پیش‌فرض 8321
  python server.py --port 9000

بدون Ollama هم بالا میاد (حالت آزمایشی) تا رابط کاربری رو ببینی.
فقط استاندارد پایتون — pip لازم نیست.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
NOTEBOOK_DIR = os.path.join(HERE, "notebook")
INBOX_DIR = os.path.join(NOTEBOOK_DIR, "inbox")
DATA_DIR = os.path.join(HERE, "data")
INDEX_FILE = os.path.join(DATA_DIR, "index.json")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("SANGAR_MODEL", "qwen3:8b")
DEFAULT_EMBED = os.environ.get("SANGAR_EMBED", "bge-m3")
CHAT_PORT_DEFAULT = 8321

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
MAX_TOPK = 6

SYSTEM_MODES = {
    "chat": (
        "تو «سنگر» هستی؛ دستیار هوشمند آفلاین کاربر. با کاربر فارسی صحبت کن "
        "(مگر او انگلیسی بنویسد). دقیق، صادق و خلاصه جواب بده. اگر از منابع دفترچه استفاده شد، "
        "به آن‌ها استناد کن و اگر در آن‌ها نبود، صادقانه بگو."
    ),
    "study": (
        "تو دستیار درسی «سنگر» هستی مثل NotebookLM. کاربر: جزوه و کتاب دارد. "
        "کارهایت: خلاصه‌نویسی، نکته‌برداری، طرح سؤال و آزمون، فلش‌کارت، ترجمه، توضیح مفاهیم، "
        "بندنویسی و ویرایش متن فارسی و انگلیسی. همیشه ساختاریافته و با تیتر جواب بده."
    ),
    "code": (
        "تو دستیار کدنویسی «سنگر» هستی. کد بنویس، اصلاح و توضیح بده. "
        "جواب را داخل بلاک کد مناسب بگذار و کامنت‌های فارسی بنویس. "
        "کد را کامل و قابل اجرا ارائه کن، نه ناقص."
    ),
}


# ----------------------------------------------------------------------------
# وضعیت و ذخیره‌سازی
# ----------------------------------------------------------------------------
def http_json(url, payload=None, timeout=60, method=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_alive():
    try:
        http_json(OLLAMA_URL + "/api/tags", timeout=3)
        return True
    except Exception:
        return False


def ollama_models():
    try:
        tags = http_json(OLLAMA_URL + "/api/tags", timeout=3)
        return [m.get("name", "") for m in tags.get("models", [])]
    except Exception:
        return []


def load_index():
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"docs": {}, "chunks": [], "vectors": [], "model": "", "updated": 0}


def save_index(idx):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = INDEX_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    os.replace(tmp, INDEX_FILE)


def embed_texts(texts):
    """بردارسازی با مدل embed اولیا. در صورت خطا، None برمی‌گردونه."""
    out = []
    for t in texts:
        try:
            r = http_json(OLLAMA_URL + "/api/embed",
                          {"model": DEFAULT_EMBED, "input": t}, timeout=120)
            if "embeddings" in r and r["embeddings"]:
                out.append(r["embeddings"][0])
            elif "embedding" in r:
                out.append(r["embedding"])
            else:
                return None
        except Exception:
            try:
                r = http_json(OLLAMA_URL + "/api/embeddings",
                              {"model": DEFAULT_EMBED, "prompt": t}, timeout=120)
                out.append(r["embedding"])
            except Exception:
                return None
    return out


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


# ----------------------------------------------------------------------------
# خواندن فایل‌ها و قطعه‌بندی
# ----------------------------------------------------------------------------
class _TextExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def strip_html(text):
    p = _TextExtract()
    try:
        p.feed(text)
    except Exception:
        return re.sub(r"<[^>]+>", " ", text)
    return "\n".join(p.parts)


def read_text_file(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if ext in (".html", ".htm"):
        text = strip_html(text)
    elif ext == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return text


def chunk_text(text):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + CHUNK_SIZE, n)
        if end < n:
            # ترجیح برش روی مرز جمله/خط
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("۔ "))
            if cut > CHUNK_SIZE // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def rebuild_index():
    """ایندکس کامل از notebook/inbox — فقط فایل‌های متنی."""
    os.makedirs(INBOX_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    docs, all_chunks = {}, []
    for root, _, files in os.walk(NOTEBOOK_DIR):
        for fn in files:
            path = os.path.join(root, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in (".txt", ".md", ".html", ".htm", ".json", ".csv", ".srt", ".log"):
                continue
            if os.path.getsize(path) > 25 * 1024 * 1024:
                continue
            try:
                text = read_text_file(path)
            except Exception:
                continue
            rel = os.path.relpath(path, NOTEBOOK_DIR)
            pieces = chunk_text(text)
            docs[rel] = {"chunks": len(pieces), "chars": len(text),
                         "mtime": int(os.path.getmtime(path))}
            for i, p in enumerate(pieces):
                all_chunks.append({"doc": rel, "i": i, "text": p})

    vectors = []
    if all_chunks:
        print(f"  بردارسازی {len(all_chunks)} قطعه با {DEFAULT_EMBED} ...", flush=True)
        vecs = embed_texts([c["text"] for c in all_chunks])
        if vecs and len(vecs) == len(all_chunks):
            vectors = vecs
        else:
            print("  ⚠️ بردارسازی انجام نشد (Ollama/مدل embed در دسترس نیست) — جستجوی متنی ساده فعال می‌شه",
                  flush=True)

    idx = {"docs": docs, "chunks": all_chunks, "vectors": vectors,
           "model": DEFAULT_EMBED if vectors else "", "updated": int(time.time())}
    save_index(idx)
    return idx


def search_docs(query, idx, topk=MAX_TOPK):
    if not idx["chunks"]:
        return []
    if idx.get("vectors") and len(idx["vectors"]) == len(idx["chunks"]):
        qv = embed_texts([query])
        if qv:
            q = qv[0]
            scored = sorted(
                ((cosine(q, idx["vectors"][i]), c) for i, c in enumerate(idx["chunks"])),
                key=lambda x: -x[0])
            return [c for _, c in scored[:topk]]
    # حالت پشتیبان: تطابق کلمات
    terms = set(re.findall(r"[\wآ-ی]{3,}", query.lower()))
    scored = []
    for c in idx["chunks"]:
        text_l = c["text"].lower()
        hit = sum(1 for t in terms if t in text_l)
        if hit:
            scored.append((hit, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:topk]]


# ----------------------------------------------------------------------------
# چت
# ----------------------------------------------------------------------------
def stream_chat(messages, mode, use_docs, on_token):
    """توکن‌ها رو به on_token می‌فرسته. خروجی: (full_text, source_docs)"""
    idx = load_index() if use_docs else None
    source_docs = set()
    final_messages = []

    system = SYSTEM_MODES.get(mode, SYSTEM_MODES["chat"])
    if use_docs and idx and idx["chunks"]:
        hits = search_docs(messages[-1].get("content", ""), idx)
        if hits:
            ctx = "\n\n---\n\n".join(f"[{h['doc']}]\n{h['text']}" for h in hits)
            system += ("\n\n=== بخشی از دفترچه‌ی کاربر (به این‌ها استناد کن) ===\n" + ctx)
            source_docs = sorted({h["doc"] for h in hits})
    final_messages.append({"role": "system", "content": system})
    final_messages.extend(messages[-12:])

    if not ollama_alive():
        note = ("⚠️ اتصال به Ollama برقرار نشد. اول نصب و اجراش کن:\n"
                "فایل install/install_ai را اجرا کن، بعد سرور را دوباره بزن.\n"
                "(این پیام فقط در حالت آزمایشی دیده می‌شود)")
        for word in note.split(" "):
            on_token(word + " ")
        return note, sorted(source_docs)

    model = DEFAULT_MODEL
    models = ollama_models()
    if models and model not in models:
        # اولین مدل موجود که شبیه چت باشه
        pref = [m for m in models if not m.startswith(("bge", "all-minilm", "nomic", "snowflake"))]
        model = (pref or models)[0]

    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps({"model": model, "messages": final_messages,
                         "stream": True, "options": {"num_ctx": 8192}}).encode(),
        headers={"Content-Type": "application/json"})
    full = []
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            buf = b""
            while True:
                chunk = resp.read(512)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    tok = (obj.get("message") or {}).get("content", "")
                    if tok:
                        full.append(tok)
                        on_token(tok)
                    if obj.get("done"):
                        return "".join(full), sorted(source_docs)
    except Exception as e:
        err = f"\n[خطا در ارتباط با مدل: {e}]"
        full.append(err)
        on_token(err)
    return "".join(full), sorted(source_docs)


# ----------------------------------------------------------------------------
# سرور HTTP
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "SangarAI/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_file(self, path, code=200):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    # ---------- routes ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            idx = os.path.join(UI_DIR, "index.html")
            if os.path.exists(idx):
                return self._html_file(idx)
            return self._json({"error": "ui missing"}, 404)
        if path == "/api/status":
            alive = ollama_alive()
            idx = load_index()
            return self._json({
                "ollama": alive,
                "ollama_url": OLLAMA_URL,
                "models": ollama_models(),
                "model": DEFAULT_MODEL,
                "embed_model": DEFAULT_EMBED if idx.get("vectors") else None,
                "docs": len(idx.get("docs", {})),
                "chunks": len(idx.get("chunks", [])),
                "indexed_at": idx.get("updated", 0),
                "testing_mode": not alive,
            })
        if path == "/api/docs":
            idx = load_index()
            docs = [{"name": k, **v} for k, v in sorted(idx.get("docs", {}).items())]
            return self._json({"docs": docs})
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/docs/"):
            name = urllib.parse.unquote(path[len("/api/docs/"):])
            idx = load_index()
            # حذف از لیست + حذف فایل اگه داخل notebook بود
            idx["docs"].pop(name, None)
            idx["chunks"] = [c for c in idx["chunks"] if c["doc"] != name]
            # وکتورها باید هم‌تراز بشن — ساده: ایندکس رو ری‌بیلد می‌کنیم
            save_index(idx)
            fpath = os.path.join(NOTEBOOK_DIR, name)
            if os.path.commonpath([os.path.abspath(fpath), os.path.abspath(NOTEBOOK_DIR)]) == os.path.abspath(NOTEBOOK_DIR):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            idx2 = rebuild_index()
            return self._json({"ok": True, "docs": len(idx2["docs"])})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/chat":
            try:
                data = json.loads(self._read_body().decode("utf-8"))
            except Exception:
                return self._json({"error": "bad json"}, 400)
            messages = data.get("messages") or []
            if not messages:
                return self._json({"error": "empty"}, 400)
            use_docs = bool(data.get("use_docs"))
            mode = data.get("mode", "chat")

            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            def send(obj):
                payload = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
                try:
                    self.wfile.write(("%X\r\n" % len(payload)).encode())
                    self.wfile.write(payload)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                except Exception:
                    raise BrokenPipeError

            def on_token(t):
                send({"t": t})

            try:
                full, sources = stream_chat(messages, mode, use_docs, on_token)
                send({"done": True, "sources": sources, "chars": len(full)})
            except BrokenPipeError:
                pass
            except Exception as e:
                try:
                    send({"error": str(e)[:200], "done": True, "sources": []})
                except Exception:
                    pass
            try:
                self.wfile.write(b"0\r\n\r\n")
            except Exception:
                pass
            return

        if path == "/api/upload":
            # multipart ساده: فیلدهای file (چندتایی)
            try:
                body = self._read_body()
                ct = self.headers.get("Content-Type", "")
                saved = []
                if "multipart/form-data" in ct:
                    boundary = ct.split("boundary=")[-1].encode()
                    for part in body.split(b"--" + boundary):
                        if b'Content-Disposition' not in part:
                            continue
                        head, _, payload = part.partition(b"\r\n\r\n")
                        if not payload:
                            continue
                        payload = payload.rstrip(b"\r\n")
                        m = re.search(rb'filename="([^"]+)"', head)
                        if not m:
                            continue
                        fname = os.path.basename(m.group(1).decode("utf-8", errors="replace"))
                        fname = re.sub(r'[\\/:*?"<>|]', "_", fname)
                        if not fname:
                            continue
                        os.makedirs(INBOX_DIR, exist_ok=True)
                        dest = os.path.join(INBOX_DIR, fname)
                        with open(dest, "wb") as f:
                            f.write(payload)
                        saved.append(fname)
                idx = rebuild_index()
                return self._json({"ok": True, "saved": saved, "docs": len(idx["docs"]),
                                   "chunks": len(idx["chunks"])})
            except Exception as e:
                return self._json({"error": str(e)[:200]}, 500)

        if path == "/api/reindex":
            try:
                idx = rebuild_index()
                return self._json({"ok": True, "docs": len(idx["docs"]),
                                   "chunks": len(idx["chunks"]),
                                   "vectors": len(idx["vectors"])})
            except Exception as e:
                return self._json({"error": str(e)[:200]}, 500)

        return self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Sangar local AI server")
    ap.add_argument("--port", type=int, default=CHAT_PORT_DEFAULT)
    args = ap.parse_args()

    os.makedirs(INBOX_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 54, flush=True)
    print("🤖 سنگر — سرور هوش مصنوعی محلی", flush=True)
    print(f"   رابط کاربری:  http://127.0.0.1:{args.port}", flush=True)
    print(f"   Ollama:       {OLLAMA_URL} — {'✅ متصل' if ollama_alive() else '❌ در دسترس نیست (حالت آزمایشی)'}", flush=True)
    print(f"   مدل چت:      {DEFAULT_MODEL}", flush=True)
    print(f"   مدل بردار:    {DEFAULT_EMBED}", flush=True)
    print("=" * 54, flush=True)

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nمتوقف شد.")
        srv.server_close()


if __name__ == "__main__":
    main()
