@echo off
setlocal
chcp 65001 >nul
title MEDIAPIPE WVM - KI-Video-Studio

cd /d "%~dp0"

echo.
echo   ==================================================================
echo     MEDIAPIPE WVM - KI-Video-Studio
echo   ==================================================================
echo.

REM ── 1. Python vorhanden? ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo   [X] Python wurde nicht gefunden.
    echo.
    echo       Bitte Python 3.10 oder neuer installieren:
    echo       https://www.python.org/downloads/
    echo       Beim Installieren "Add Python to PATH" ankreuzen.
    echo.
    pause
    exit /b 1
)

REM ── 2. Zugangsdaten vorhanden? ────────────────────────────────────────
if not exist ".env" (
    echo   [X] Die Datei .env fehlt.
    echo.
    echo       Sie enthaelt die Zugangsdaten und wird getrennt uebergeben.
    echo       Legen Sie sie in diesen Ordner:
    echo       %CD%
    echo.
    echo       Zur Not: .env.example nach .env kopieren und ausfuellen.
    echo.
    pause
    exit /b 1
)

REM ── 3. Abhaengigkeiten beim ersten Start einrichten ───────────────────
if not exist ".eingerichtet" (
    echo   Erster Start - benoetigte Pakete werden installiert.
    echo   Das dauert einige Minuten und passiert nur dieses eine Mal.
    echo.
    python -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [X] Die Installation ist fehlgeschlagen.
        echo       Bitte diesen Befehl von Hand ausfuehren und die Meldung lesen:
        echo       python -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo eingerichtet am %DATE% > ".eingerichtet"
    echo   Fertig eingerichtet.
    echo.
)

REM ── 4. Starten ────────────────────────────────────────────────────────
python run.py %*

if errorlevel 1 (
    echo.
    echo   Das Programm wurde mit einem Fehler beendet - Meldung siehe oben.
    echo.
    pause
)
endlocal
