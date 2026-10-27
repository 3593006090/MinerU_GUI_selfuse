@echo off
rem Unblock MinerU GUI binaries and show a short notice.
rem SmartScreen may still ask once for unsigned apps: click "More info" then "Run anyway".
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -Path 'E:\MinerU\minerU-gui\minerU-gui.exe','E:\MinerU\minerU-install-gui\minerU-install-gui.exe' -ErrorAction SilentlyContinue; Write-Host ''; Write-Host '  Files unblocked.'; Write-Host '  If SmartScreen still appears once: More info -> Run anyway.'"
echo.
echo  If Microsoft Defender keeps flagging the folder, add it as an exclusion:
echo    Windows Security - Virus ^& threat protection - Manage settings
echo    - Exclusions - Add or remove exclusions - Folder - E:\MinerU
pause
