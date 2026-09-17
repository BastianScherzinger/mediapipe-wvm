# Diese Datei ist bewusst UTF-8 MIT Byte-Reihenfolge-Marke gespeichert: Windows
# PowerShell 5.1 liest ein Skript ohne Marke in der ANSI-Codepage, und jedes "ä"
# zerlegt dann die Zeile, in der es steht.
# verknuepfung_anlegen.ps1 — legt die Verknüpfung „MEDIAPIPE WVM“ auf den Desktop.
#
# Warum ein eigenes Skript und kein Satz in der Anleitung: Eine Verknüpfung von Hand
# anzulegen heißt Rechtsklick, Ziel suchen, Symbol wählen — drei Stellen, an denen es
# schiefgeht. Hier ist es ein Doppelklick.
#
# Aufruf:  powershell -ExecutionPolicy Bypass -File tools\verknuepfung_anlegen.ps1
# Entfernen: dieselbe Zeile mit  -Entfernen

param([switch]$Entfernen)

$ErrorActionPreference = "Stop"

$projekt = Split-Path -Parent $PSScriptRoot
$ziel    = Join-Path $projekt "start.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$linkPfad = Join-Path $desktop "MEDIAPIPE WVM.lnk"

if ($Entfernen) {
    if (Test-Path $linkPfad) { Remove-Item $linkPfad -Force; Write-Output "Verknüpfung entfernt." }
    else { Write-Output "Es gab keine Verknüpfung." }
    exit 0
}

if (-not (Test-Path $ziel)) {
    Write-Error "start.bat wurde nicht gefunden: $ziel"
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPfad)
$link.TargetPath       = $ziel
$link.WorkingDirectory = $projekt
$link.Description      = "MEDIAPIPE WVM — KI-Video-Studio"
$link.WindowStyle      = 1

# Ein eigenes Symbol, wenn eines im Projekt liegt; sonst das von cmd, damit die
# Verknüpfung nicht ohne Bild dasteht.
$symbol = Join-Path $projekt "static\img\mediapipe.ico"
if (Test-Path $symbol) { $link.IconLocation = $symbol }
else { $link.IconLocation = "$env:SystemRoot\System32\cmd.exe,0" }

$link.Save()
Write-Output "Verknüpfung angelegt: $linkPfad"
