@echo off
chcp 65001 >nul
title Sangar - System Proxy ON/OFF
cd /d "%~dp0"
echo ==================================================
echo   پروکسی سیستم (ویندوز) — بدون نیاز به ادمین
echo ==================================================
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2>nul | find "0x1" >nul
if %errorlevel%==0 (
  echo وضعیت فعلی: روشن — دارم خاموشش می‌کنم...
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
  echo [OK] پروکسی سیستم خاموش شد.
) else (
  echo وضعیت فعلی: خاموش — دارم روشنمش می‌کنم...
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:10809" /f >nul
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
  echo [OK] پروکسی سیستم روشن شد: 127.0.0.1:10809
  echo     مرورگر و اپ‌های ویندوز حالا از پروکسی استفاده می‌کنند.
)
echo.
echo نکته: start_proxy.py باید در حال اجرا باشد.
pause
