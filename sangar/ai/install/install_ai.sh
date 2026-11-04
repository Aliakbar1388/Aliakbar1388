#!/usr/bin/env bash
# سنگر — نصب یک‌باره‌ی هوش مصنوعی محلی (لینوکس / مک)
set -e
echo "=========================================================="
echo "  سنگر — نصب یک‌باره‌ی هوش مصنوعی محلی"
echo "  فقط یک‌بار با اینترنت اجرا کن، بعد برای همیشه آفلاین"
echo "=========================================================="

# ---------- پایتون ----------
if ! command -v python3 >/dev/null 2>&1; then
  echo "[X] python3 پیدا نشد. نصب کن: sudo apt install python3"
  exit 1
fi
echo "[OK] پایتون: $(python3 --version)"

# ---------- Ollama ----------
if ! command -v ollama >/dev/null 2>&1; then
  echo "[-] Ollama نصب نیست. دانلود از GitHub ..."
  ARCH=$(uname -m)
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  case "$OS" in
    linux)  URL="https://github.com/ollama/ollama/releases/latest/download/ollama-linux-${ARCH}.tgz" ;;
    darwin) URL="https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz" ;;
    *) echo "[X] سیستم‌عامل پشتیبانی نمی‌شود؛ دستی نصب کن: https://ollama.com/download"; exit 1 ;;
  esac
  echo "    $URL"
  TMP=$(mktemp -d)
  if curl -fL "$URL" -o "$TMP/ollama.tgz"; then
    echo "    استخراج ..."
    mkdir -p "$HOME/.local"
    tar -xzf "$TMP/ollama.tgz" -C "$HOME/.local"
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" 2>/dev/null || true
    echo "[OK] Ollama نصب شد."
  else
    echo "[X] دانلود ناموفق. دستی نصب کن: https://ollama.com/download"
    exit 1
  fi
  rm -rf "$TMP"
else
  echo "[OK] Ollama نصب است."
fi

# ---------- مدل‌ها ----------
echo
echo "[1/2] مدل گفت‌وگو و درس (qwen3:8b - فارسی عالی) ..."
ollama pull qwen3:8b
echo "[2/2] مدل بردار برای جستجوی دفترچه (bge-m3) ..."
ollama pull bge-m3

read -p "آیا مدل تخصصی کدنویسی هم بگیرم؟ (qwen2.5-coder:7b - حدود 5GB) [y/N] " WANTCODE
if [ "$WANTCODE" = "y" ] || [ "$WANTCODE" = "Y" ]; then
  ollama pull qwen2.5-coder:7b
fi

echo
echo "=========================================================="
echo " [OK] نصب کامل شد!"
echo "  حالا ./start_ai.sh را اجرا کن تا دستیار باز شود."
echo "=========================================================="
