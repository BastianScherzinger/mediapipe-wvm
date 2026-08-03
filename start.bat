@echo off
setlocal
title MEDIAPIPE WVM - KI-Video-Studio

REM Diese Datei selbst enthaelt bewusst nur ASCII - cmd liest sie in der
REM eingestellten Codepage, und Sonderzeichen wuerden zu Kauderwelsch.
REM Die Ausgabe von Python enthaelt dagegen Umlaute, darum hier auf UTF-8 stellen.
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

echo.
echo   ==================================================================
echo     MEDIAPIPE WVM  -  KI-Video-Studio
echo   ==================================================================
echo.

REM --- 1. Ist Python da? ---------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo   [FEHLT]  Python wurde nicht gefunden.
    echo.
    echo       Bitte Python 3.10 oder neuer installieren:
    echo       https://www.python.org/downloads/
    echo       Beim Installieren "Add Python to PATH" ankreuzen.
    echo.
    pause
    exit /b 1
)

REM --- 2. Sind die Zugangsdaten da? ----------------------------------
if not exist ".env" (
    echo   [FEHLT]  Die Datei .env ist nicht vorhanden.
    echo.
    echo       Sie enthaelt die Zugangsdaten und wird getrennt uebergeben.
    echo       Bitte in diesen Ordner legen:
    echo       %CD%
    echo.
    echo       Notfalls .env.example nach .env kopieren und ausfuellen.
    echo.
    pause
    exit /b 1
)

REM --- 3. Beim ersten Start die Pakete einrichten ---------------------
if not exist ".eingerichtet" (
    echo   Erster Start - benoetigte Pakete werden installiert.
    echo   Das dauert einige Minuten und passiert nur dieses eine Mal.
    echo.
    python -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [FEHLER] Die Installation ist fehlgeschlagen.
        echo            Bitte von Hand ausfuehren und die Meldung lesen:
        echo            python -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo eingerichtet am %DATE% > ".eingerichtet"
    echo   Einrichtung abgeschlossen.
    echo.
)

REM --- 4. Programm starten -------------------------------------------
python run.py %*

if errorlevel 1 (
    echo.
    echo   Das Programm wurde mit einem Fehler beendet - Meldung siehe oben.
    echo.
    pause
)
endlocal
