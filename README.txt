TTS Offline Piper
This project is a local Text-to-Speech (TTS) application based on the Piper engine.
It provides a simple interface inspired by macOS Spotlight: a centered, lightweight window where you can type text and hear it spoken instantly.

---

Features
Fully offline speech synthesis, no Internet connection required.
Supports .onnx Piper models (placed in the models/ folder).
Selectable audio output device (e.g., VB-Cable, headphones, speakers).
Configurable global hotkeys:
Ctrl + Space: open/close the Spotlight window
Enter: read the text
Esc: close the window
Ctrl + Shift + V: read the clipboard
Ctrl + Shift + Backspace: stop playback
System tray icon with quick access to actions.

---

Installation
Prerequisites
Python 3.10 or higher (tested with Python 3.12)
Up-to-date pip
Piper models available in .onnx format

Clone and install
```bash
git clone https://github.com/RezeGH/tts.git
cd tts-offline-piper
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt