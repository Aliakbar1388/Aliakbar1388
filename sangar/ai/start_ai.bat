@echo off
chcp 65001 >nul
title Sangar - AI Assistant
cd /d "%~dp0"
set PY=
where python >nul 2>nul && set PY=python
if not defined PY where py >nul 2>nul && set PY=py
if not defined PY (
  echo [X] Python پیدا نشد.
  pause
  exit /b 1
)
echo در حال روشن شدن دستیار سنگر ...
start "" http://127.0.0.1:8321
%PY% server.py
pause
