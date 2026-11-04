#!/usr/bin/env bash
# سنگر — جمع‌آوری و تست کانفیگ‌ها
cd "$(dirname "$0")"
python3 collect.py "$@"
echo
echo "گزارش: output/report.html"
