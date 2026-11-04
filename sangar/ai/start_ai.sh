#!/usr/bin/env bash
# سنگر — روشن‌کردن دستیار هوشمند
cd "$(dirname "$0")"
echo "در حال روشن شدن دستیار سنگر ..."
echo "مرورگر: http://127.0.0.1:8321"
( sleep 1; xdg-open http://127.0.0.1:8321 2>/dev/null || open http://127.0.0.1:8321 2>/dev/null ) &
python3 server.py
