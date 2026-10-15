@echo off
cd /d "%~dp0"
title Albion DPS Meter
set PYTHONUTF8=1

if not exist "%SystemRoot%\System32\Npcap\wpcap.dll" (
  echo Npcap kurulu degil. Acilan sayfadan indirip varsayilan ayarlarla kur,
  echo sonra bu dosyayi tekrar calistir.
  start "" "https://npcap.com/#download"
  pause
  exit /b
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python bulunamadi. Acilan sayfadan Python indirip kur.
  echo Kurarken "Add python.exe to PATH" kutusunu isaretlemeyi unutma.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b
)

%PY% -c "import scapy" >nul 2>nul
if errorlevel 1 (
  echo Ilk calistirma: gerekli paket kuruluyor ^(scapy^)...
  %PY% -m pip install --user --disable-pip-version-check scapy
)

%PY% albion_dps.py
pause
