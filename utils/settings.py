import json
import os
import sys

APP_NAME = "DesktopTranslator"


def settings_path():
    """Return the path of the per-user settings file"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME, "settings.json")


def load_settings(path=None):
    """Read the settings; return an empty dict if missing or unreadable"""
    try:
        with open(path or settings_path(), encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings, path=None):
    """Write the settings; return False if the location is not writable"""
    path = path or settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=2)
    except OSError:
        return False
    return True
