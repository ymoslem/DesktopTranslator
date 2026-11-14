"""Information about the app, the computer and the settings, for the report of an issue

It holds no text, file names, or paths: only versions, hardware, the name of the model folder, and the settings.
"""
import os
import platform
import subprocess
import sys

import ctranslate2
import sentencepiece

from engine import gpu_count, memory_info

# The settings to report, with the value that the app uses when a setting was never changed
SETTINGS = {"beam_size": 3, "join_lines": False, "repetition_penalty": 1.0, "device": "cpu", "cpu_speed": "standard",
            "load_at_start": True, "remember_model_paths": True, "text_size": 14}
MAX_ERROR = 500


def hide_paths(text):
    """The text without the home folder of the user, and cut to a short length"""
    home = os.path.expanduser("~")
    for form in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if len(form) > 3:
            text = text.replace(form, "~")
    return text if len(text) <= MAX_ERROR else text[:MAX_ERROR] + "..."


def gpu_details():
    """Name, driver and memory of the first NVIDIA GPU from nvidia-smi, or an empty string"""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True, creationflags=flags,
        ).stdout
        return out.splitlines()[0].strip()
    except Exception:
        return ""


def collect(app_name, version, engine, settings, source_name, target_name, last_error):
    """The information as a list of (section, [(name, value), ...]); settings is the dictionary of the Preferences"""
    memory = memory_info()
    model_folder = os.path.basename(os.path.normpath(engine.model_dir)) if engine.model_dir else "none"
    model_file = os.path.join(engine.model_dir, "model.bin") if engine.model_dir else ""
    sentences, call_tokens, batch_tokens = engine.limits()
    try:
        import PySide6

        qt = PySide6.__version__
    except Exception:
        qt = "unknown"
    return [
        ("App", [
            ("Version", "%s %s (%s)" % (app_name, version, "installed app" if getattr(sys, "frozen", False) else "run from source")),
            ("Libraries", "CTranslate2 %s, SentencePiece %s, Qt for Python %s, Python %s" % (
                ctranslate2.__version__, sentencepiece.__version__, qt, platform.python_version())),
        ]),
        ("Computer", [
            ("System", platform.platform()),
            ("Processor", "%s, %s, %s cores" % (platform.machine(), platform.processor() or "unknown", os.cpu_count())),
            ("Memory", "%.1f GB, %.1f GB free" % (memory[0] / 1e9, memory[1] / 1e9) if memory else "unknown"),
            ("NVIDIA GPUs found", "%d%s" % (gpu_count(), (": " + gpu_details()) if gpu_count() else "")),
        ]),
        ("Model", [
            ("Folder name", model_folder),
            ("Kind", engine.model_type or "none"),
            ("Size of model.bin", "%.2f GB" % (os.path.getsize(model_file) / 1e9) if model_file and os.path.isfile(model_file) else "unknown"),
            ("Running on", "%s%s" % (engine.device, (", " + engine.compute_type) if engine.compute_type else "")),
            ("Sentences per call, tokens per call, tokens per batch", "%s, %s, %s" % (sentences, call_tokens or "no limit", batch_tokens)),
            ("Languages", "%s to %s" % (source_name or "none", target_name or "none")),
        ]),
        ("Settings", [(key, "%s%s" % (settings.get(key, default), "" if key in settings else " (default)")) for key, default in SETTINGS.items()]),
        ("Last error", [("Message", hide_paths("%s: %s" % last_error) if last_error else "none")]),
    ]


def to_markdown(info):
    """The information as text to paste into an issue"""
    lines = []
    for section, items in info:
        lines.append("**%s**" % section)
        lines.extend("- %s: %s" % item for item in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
