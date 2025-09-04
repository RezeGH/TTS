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
```

Minimal requirements.txt
piper-tts==1.3.0
sounddevice==0.4.7
soundfile==0.12.1
numpy==1.26.4
pystray==0.19.5
Pillow==10.4.0
keyboard==0.13.5
pyperclip==1.9.0
PySimpleGUI==5.0.8.3

Run
python main.py

Build an Executable

Using PyInstaller
:

.venv\Scripts\activate
pyinstaller --onefile --noconsole --name TTSOffline ^
  --add-data "models;models" ^
  --collect-binaries sounddevice ^
  --collect-data piper ^
  main.py


The final executable will be located in dist/TTSOffline.exe.

Using with Discord (optional)

With VB-Cable
:

Configure the application to output to CABLE Input (VB-Audio Virtual Cable).

In Discord, set the microphone to CABLE Output.

Discord will directly receive the synthesized speech.

Development Note

This project was created as an experiment.
It was partially generated and assisted by AI tools.
The code may contain limitations or require improvements. Contributions are welcome.
