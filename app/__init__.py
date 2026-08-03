"""
MEDIAPIPE WVM — KI-Video-Studio.

Aufbau (jede Ebene kennt nur die darunter):

    server ──► pipeline ──► promptsmith ──► llm/        Prompt-Schmiede
                       ├──► higgsfield              Bild- und Videoerzeugung
                       ├──► media                   ffmpeg: Montage und Formate
                       └──► jobstore                Aufträge dauerhaft speichern

    config · logbook · errors     Fundament, von allen benutzt
"""

__version__ = "1.0.0"
