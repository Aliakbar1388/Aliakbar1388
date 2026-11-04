@echo off
chcp 65001 >nul
title Sangar - Collect & Test Configs
cd /d "%~dp0"
set PY=
where python >nul 2>nul && set PY=python
if not defined PY where py >nul 2>nul && set PY=py
if not defined PY (
  echo [X] Python پیدا نشد. از python.org نصب کن.
  pause
  exit /b 1
)
echo در حال جمع‌آوری و تست کانفیگ‌ها ...
%PY% collect.py %*
echo.
echo گزارش: output\report.html
pause
