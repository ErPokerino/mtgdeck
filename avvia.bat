@echo off
rem Avvia Aetherdeck (doppio clic). Opzioni: avvia.bat -Dev ^| -Db percorso.db ^| -Setup ^| -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0avvia.ps1" %*
if errorlevel 1 pause
