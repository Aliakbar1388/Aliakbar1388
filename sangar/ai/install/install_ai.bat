@echo off
chcp 65001 >nul
title Sangar - Install AI (one time)
color 0B
echo ==========================================================
echo   سنگر - نصب یک‌باره‌ی هوش مصنوعی محلی
echo   (فقط یک‌بار با اینترنت اجرا کن، بعد برای همیشه آفلاین)
echo ==========================================================
echo.

REM ---------- بررسی پایتون ----------
set PY=
where python >nul 2>nul && set PY=python
if not defined PY where py >nul 2>nul && set PY=py
if not defined PY (
  echo [X] پایتون پیدا نشد. اول Python نصب کن: https://www.python.org/downloads/
  echo     موقع نصب گزینه "Add Python to PATH" را بزن.
  pause
  exit /b 1
)
echo [OK] پایتون پیدا شد.

REM ---------- بررسی Ollama ----------
where ollama >nul 2>nul
if %errorlevel%==0 (
  echo [OK] Ollama نصب است.
  goto MODELS
)
echo [-] Ollama نصب نیست. دانلود از GitHub ...
set "INSTALLER=%TEMP%\OllamaSetup.exe"
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe' -OutFile '%INSTALLER%'" 2>nul
if not exist "%INSTALLER%" (
  echo [X] دانلود ناموفق بود. اینترنت را چک کن یا دستی دانلود کن:
  echo     https://ollama.com/download
  pause
  exit /b 1
)
echo [OK] دانلود شد. حالا نصب‌کننده را اجرا می‌کنم (روی Next/Install بزن)...
start /wait "" "%INSTALLER%"
where ollama >nul 2>nul
if %errorlevel% neq 0 (
  echo [!] نصب تمام شد ولی مسیرش هنوز در PATH نیست. ترمینال را ببند و دوباره اجرا کن.
  pause
  exit /b 1
)

:MODELS
echo.
echo ==========================================================
echo   دانلود مدل‌ها (اولین بار چند دقیقه طول می‌کشد)
echo ==========================================================
echo [1/2] مدل گفت‌وگو و درس (qwen3:8b - فارسی عالی) ...
ollama pull qwen3:8b
echo [2/2] مدل بردار برای جستجوی دفترچه (bge-m3) ...
ollama pull bge-m3

echo.
set /p WANTCODE="آیا مدل تخصصی کدنویسی هم بگیرم؟ (qwen2.5-coder:7b / حدود 5GB) [y/N] "
if /i "%WANTCODE%"=="y" ollama pull qwen2.5-coder:7b

echo.
echo ==========================================================
echo  [OK] نصب کامل شد!
echo   حالا start_ai.bat را اجرا کن تا دستیار باز شود.
echo ==========================================================
pause
