import os
import json
import threading
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np
import sounddevice as sd
import pyperclip
import keyboard
import PySimpleGUI as sg
from PIL import Image, ImageDraw
import pystray
import tkinter as tk  # pour masquer le label "trial/license"

# piper-tts (>= 1.3.0)
from piper import PiperVoice

APP_NAME = "TTS Offline Piper"
APP_DIR = Path(os.path.expanduser("~")) / ".tts_offline_piper"
APP_DIR.mkdir(exist_ok=True)
CONFIG_PATH = APP_DIR / "config.json"
MODELS_DIR = Path.cwd() / "models"

# Cible par défaut si dispo : VB-Cable
VB_CABLE_NAME = "CABLE Input (VB-Audio Virtual Cable)"

DEFAULTS = {
    "voice_model": "",
    "audio_device_name": "",  # auto-forcé vers VB-Cable si présent
    # Raccourcis (on normalise 'espace' -> 'space')
    "hotkey_speak_clipboard": "ctrl+shift+v",
    "hotkey_spotlight": "ctrl+space",
    "hotkey_stop": "ctrl+shift+backspace",
    "volume": 1.0,
    "autostart": False,
}

cfg = DEFAULTS.copy()
EVENT_WIN: Optional[sg.Window] = None
SPOT_WIN: Optional[sg.Window] = None

# ---------- util ----------
def normalize_hotkey(hk: str) -> str:
    if not hk:
        return hk
    return hk.lower().replace("espace", "space").strip()

def load_config():
    global cfg
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass

def save_config():
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- modèles piper ----------
def list_piper_models() -> List[Tuple[str, Path]]:
    return [(p.name, p) for p in MODELS_DIR.glob("*.onnx")] if MODELS_DIR.exists() else []

def pick_first_model() -> Optional[Path]:
    models = list_piper_models()
    return models[0][1] if models else None

# ---------- audio ----------
def list_output_devices() -> List[str]:
    devs = sd.query_devices()
    names = [d["name"] for d in devs if d.get("max_output_channels", 0) > 0]
    return list(dict.fromkeys(names))

def get_device_index_by_name(name: str) -> Optional[int]:
    if not name:
        return None
    devs = sd.query_devices()
    for i, d in enumerate(devs):
        if d.get("max_output_channels", 0) > 0 and d["name"] == name:
            return i
    return None

def ensure_vbcable_as_output():
    names = list_output_devices()
    if VB_CABLE_NAME in names and cfg.get("audio_device_name") != VB_CABLE_NAME:
        cfg["audio_device_name"] = VB_CABLE_NAME
        save_config()

# ---------- Piper voice ----------
voice_lock = threading.Lock()
current_voice: Optional["PiperVoice"] = None
current_model_path: Optional[Path] = None

def load_voice(model_path: Path):
    global current_voice, current_model_path
    with voice_lock:
        if current_voice and current_model_path == model_path:
            return
        current_voice = PiperVoice.load(str(model_path))
        current_model_path = model_path

# ---------- synthèse ----------
def synthesize_to_pcm_float(text: str):
    """Retourne (audio_float32_mono, sample_rate) à partir des AudioChunk Piper."""
    if not text.strip():
        return np.zeros((1,), dtype=np.float32), 22050

    model_path = Path(cfg.get("voice_model") or "")
    if not model_path.exists():
        mp = pick_first_model()
        if not mp:
            raise RuntimeError("Aucun modèle piper .onnx trouvé dans ./models")
        model_path = mp
        cfg["voice_model"] = str(model_path)
        save_config()
    load_voice(model_path)

    parts = []
    for ch in current_voice.synthesize(text):
        if hasattr(ch, "audio_int16_bytes"):
            parts.append(ch.audio_int16_bytes)
        elif hasattr(ch, "audio_int16_array"):
            parts.append(ch.audio_int16_array.tobytes())
        elif hasattr(ch, "audio_float_array"):
            arr = ch.audio_float_array
            arr = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
            parts.append(arr.tobytes())
        elif isinstance(ch, (bytes, bytearray, memoryview)):
            parts.append(bytes(ch))
        else:
            arr = np.asarray(ch)
            if arr.dtype != np.int16:
                arr = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
            parts.append(arr.tobytes())

    pcm_bytes = b"".join(parts)
    if not pcm_bytes:
        raise RuntimeError("Piper a renvoyé un flux PCM vide.")

    data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    sr = current_voice.config.sample_rate
    vol = float(cfg.get("volume", 1.0))
    data = np.clip(data * vol, -1.0, 1.0).astype(np.float32)
    return data, sr

# ---------- lecture audio (bloquante / fiable) ----------
playback_lock = threading.Lock()
stop_flag = threading.Event()

def stop_playback():
    stop_flag.set()
    try:
        sd.stop()
    except Exception:
        pass

def play_audio(data: np.ndarray, sr: int):
    stop_flag.clear()
    device_name = cfg.get("audio_device_name", "")
    device_idx = get_device_index_by_name(device_name)
    try:
        if device_idx is not None:
            sd.default.device = (None, device_idx)  # (input, output)
        try:
            sd.stop()
        except Exception:
            pass
        arr = np.asarray(data, dtype=np.float32).reshape(-1, 1)
        sd.play(arr, sr, blocking=True)
    finally:
        try:
            sd.stop()
        except Exception:
            pass

# ---------- actions ----------
def speak_text(text: str):
    try:
        data, sr = synthesize_to_pcm_float(text)
        play_audio(data, sr)
    except Exception as e:
        sg.popup_error(f"Erreur synthèse/lecture:\n{e}", keep_on_top=True)

def speak_clipboard():
    text = (pyperclip.paste() or "").strip()
    if not text:
        sg.popup_ok("Presse-papiers vide.", keep_on_top=True)
        return
    threading.Thread(target=speak_text, args=(text,), daemon=True).start()

# ---------- HACK: masquer le label "trial/license" en bas à gauche ----------
def _hide_psg_trial_labels(root: tk.Misc):
    """Supprime récursivement les labels Tkinter contenant 'pysimplegui' ou 'license'."""
    try:
        def _walk(w):
            for child in w.winfo_children():
                try:
                    if isinstance(child, tk.Label):
                        txt = (child.cget("text") or "").lower()
                        if "pysimplegui" in txt or "license" in txt or "trial" in txt:
                            child.destroy()
                            continue
                    _walk(child)
                except Exception:
                    pass
        _walk(root)
    except Exception:
        pass

# ---------- UI: Spotlight-like ----------
def make_spotlight_window() -> sg.Window:
    sg.theme("DarkBlack")
    font = ("Segoe UI", 14)
    layout = [[
        sg.Push(),
        sg.Input(
            key="-SPOT-",
            focus=True,
            font=font,
            size=(60, 1),
            border_width=0,
            background_color="#1e1e1f",
            text_color="#f5f5f5",
            justification="left",
            enable_events=True
        ),
        sg.Push()
    ]]
    win = sg.Window(
        "Spotlight",
        layout,
        keep_on_top=True,
        no_titlebar=True,
        finalize=True,
        grab_anywhere=True,
        alpha_channel=0.98,
        margins=(20, 16),
        element_padding=(0, 0),
        background_color="#121214",
        modal=False
    )

    # Masquer visuellement le label "trial/license" (souvent en bas à gauche)
    try:
        _hide_psg_trial_labels(win.TKroot)
    except Exception:
        pass

    # Taille/position
    width, height = 800, 64
    screen_w, screen_h = win.get_screen_dimensions()
    x = int((screen_w - width) / 2)
    y = int(screen_h * 0.18)
    win.TKroot.geometry(f"{width}x{height}+{x}+{y}")

    # Focus curseur
    win["-SPOT-"].Widget.configure(insertbackground="#f5f5f5")
    win["-SPOT-"].set_focus(force=True)
    return win

def toggle_spotlight():
    global SPOT_WIN
    if SPOT_WIN is None:
        SPOT_WIN = make_spotlight_window()
    else:
        try:
            visible = SPOT_WIN.TKroot.state() != "withdrawn"
        except Exception:
            visible = True
        if visible:
            SPOT_WIN.hide()
            return
        else:
            SPOT_WIN.un_hide()
            SPOT_WIN.bring_to_front()
    try:
        SPOT_WIN["-SPOT-"].update("")
        SPOT_WIN["-SPOT-"].set_focus(force=True)
    except Exception:
        pass

def spotlight_submit():
    """Soumettre le texte du Spotlight quand on presse Entrée (hotkey globale)."""
    global SPOT_WIN
    if SPOT_WIN is None:
        return
    try:
        if SPOT_WIN.TKroot.state() == "withdrawn":
            return
    except Exception:
        pass
    try:
        text = (SPOT_WIN["-SPOT-"].get() or "").strip()
        if text:
            threading.Thread(target=speak_text, args=(text,), daemon=True).start()
            SPOT_WIN["-SPOT-"].update("")
            SPOT_WIN["-SPOT-"].set_focus(force=True)
    except Exception:
        pass

def spotlight_close():
    """Fermer Spotlight sur Échap (hotkey globale)."""
    global SPOT_WIN
    if SPOT_WIN is None:
        return
    try:
        SPOT_WIN.hide()
    except Exception:
        pass

# ---------- Tray ----------
def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((18, 10, 46, 50), fill=(0, 0, 0, 255))
    return img

tray_icon: Optional[pystray.Icon] = None

def on_tray_clicked(icon, item):
    label = str(item)
    if label.startswith("🔊"):
        EVENT_WIN.write_event_value("_SPEAK_CLIPBOARD_", None)
    elif label.startswith("⌨️"):
        EVENT_WIN.write_event_value("_SPOTLIGHT_", None)
    elif label.startswith("⏹️"):
        EVENT_WIN.write_event_value("_STOP_", None)
    elif label.startswith("🎧"):
        EVENT_WIN.write_event_value("_CHOOSE_DEVICE_", None)
    elif label.startswith("🗣️"):
        EVENT_WIN.write_event_value("_CHOOSE_VOICE_", None)
    elif label.startswith("Quitter"):
        stop_playback()
        if tray_icon:
            tray_icon.stop()
        EVENT_WIN.write_event_value(sg.WIN_CLOSED, None)

def refresh_tray():
    global tray_icon
    menu = pystray.Menu(
        pystray.MenuItem("🔊 Lire presse-papiers", on_tray_clicked),
        pystray.MenuItem("⌨️ Ouvrir Spotlight", on_tray_clicked),
        pystray.MenuItem("⏹️ Stop", on_tray_clicked),
        pystray.MenuItem("—", lambda *args: None),
        pystray.MenuItem("🎧 Choisir périphérique audio", on_tray_clicked),
        pystray.MenuItem("🗣️ Choisir voix", on_tray_clicked),
        pystray.MenuItem("Quitter", on_tray_clicked),
    )
    if tray_icon is None:
        tray_icon = pystray.Icon(APP_NAME, make_icon(), APP_NAME, menu)
    else:
        tray_icon.menu = menu

# ---------- Dialogs simples ----------
def choose_device_dialog():
    devices = list_output_devices()
    if not devices:
        sg.popup_error("Aucun périphérique audio détecté.", keep_on_top=True)
        return
    layout = [
        [sg.Text("Choisir le périphérique:")],
        [sg.Listbox(values=devices, size=(60, 10), key="-DEV-")],
        [sg.Button("OK"), sg.Button("Annuler")]
    ]
    win = sg.Window("Périphérique audio", layout, keep_on_top=True, finalize=True)
    ev, vals = win.read()
    if ev == "OK" and vals.get("-DEV-"):
        cfg["audio_device_name"] = vals["-DEV-"][0]
        save_config()
    win.close()

def choose_voice_dialog():
    models = list_piper_models()
    if not models:
        sg.popup_error("Pas de modèle trouvé dans ./models", keep_on_top=True)
        return
    labels = [m[0] for m in models]
    layout = [
        [sg.Text("Choisir une voix Piper:")],
        [sg.Listbox(values=labels, size=(60, 10), key="-VOICE-")],
        [sg.Button("OK"), sg.Button("Annuler")]
    ]
    win = sg.Window("Voix Piper", layout, keep_on_top=True, finalize=True)
    ev, vals = win.read()
    if ev == "OK" and vals.get("-VOICE-"):
        label = vals["-VOICE-"][0]
        chosen = [p for (lbl, p) in models if lbl == label][0]
        cfg["voice_model"] = str(chosen)
        save_config()
        load_voice(chosen)
    win.close()

# ---------- hotkeys ----------
def register_hotkeys():
    hk_clip = normalize_hotkey(cfg.get("hotkey_speak_clipboard", "ctrl+shift+v"))
    hk_spot = normalize_hotkey(cfg.get("hotkey_spotlight", "ctrl+space"))
    hk_stop = normalize_hotkey(cfg.get("hotkey_stop", "ctrl+shift+backspace"))
    try:
        keyboard.add_hotkey(hk_clip, lambda: EVENT_WIN.write_event_value("_SPEAK_CLIPBOARD_", None))
        keyboard.add_hotkey(hk_spot, lambda: EVENT_WIN.write_event_value("_SPOTLIGHT_", None))
        keyboard.add_hotkey(hk_stop, lambda: EVENT_WIN.write_event_value("_STOP_", None))
        # Hotkeys internes Spotlight (globales)
        keyboard.add_hotkey("enter", lambda: EVENT_WIN.write_event_value("_SPOT_ENTER_", None))
        keyboard.add_hotkey("escape", lambda: EVENT_WIN.write_event_value("_SPOT_ESC_", None))
    except Exception as e:
        sg.popup_error(
            "Erreur en enregistrant les raccourcis :\n"
            f"{e}\n\nEssaie de lancer l'application en tant qu'administrateur.",
            keep_on_top=True
        )

# ---------- main ----------
def main():
    load_config()
    ensure_vbcable_as_output()

    global EVENT_WIN
    EVENT_WIN = sg.Window(
        "CoreLoop", [[sg.Text("", key="-DUMMY-")]],
        finalize=True, alpha_channel=0,
        keep_on_top=True, no_titlebar=True,
        size=(1, 1), margins=(0, 0)
    )
    EVENT_WIN.hide()

    register_hotkeys()
    refresh_tray()
    threading.Thread(target=lambda: tray_icon.run(), daemon=True).start()

    while True:
        ev, vals = EVENT_WIN.read(timeout=100)
        if ev in (sg.WIN_CLOSED, None):
            break
        elif ev == "_SPEAK_CLIPBOARD_":
            speak_clipboard()
        elif ev == "_SPOTLIGHT_":
            toggle_spotlight()
        elif ev == "_STOP_":
            stop_playback()
        elif ev == "_CHOOSE_DEVICE_":
            choose_device_dialog()
        elif ev == "_CHOOSE_VOICE_":
            choose_voice_dialog()
        elif ev == "_SPOT_ENTER_":
            spotlight_submit()
        elif ev == "_SPOT_ESC_":
            spotlight_close()

    try:
        if tray_icon:
            tray_icon.stop()
    except Exception:
        pass
    EVENT_WIN.close()

if __name__ == "__main__":
    main()
