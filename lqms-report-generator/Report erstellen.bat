@echo off
rem ins Unterverzeichnis data\dist wechseln
cd /d "%~dp0data\dist"

rem Info an den Nutzer
echo Report Erstellung wird gestartet, bitte warten
timeout /t 2 /nobreak >nul

rem Programm starten
start "" "generate_report.exe"

rem Batch-Fenster schliessen
exit
