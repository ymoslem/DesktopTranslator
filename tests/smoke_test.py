"""Smoke test of DesktopTranslator, mainly to check it on Windows.

Usage: python tests/smoke_test.py path/to/fren

The folder must contain ct2_model and sp_model/fr.model of the French-to-English model.
"""
import os
import sys
import tempfile
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import utils.settings as settings_module
from utils.paragraph_splitter import paragraph_tokenizer, paragraph_detokenizer

failures = []


def check(condition, description):
    print(("PASS " if condition else "FAIL ") + description, flush=True)
    if not condition:
        failures.append(description)


# Translated lines do not end with a space
joined = paragraph_detokenizer(["First.", "Second.", "Third."], [0, 1, "\n", "\n", 2])
check(joined == "First. Second.\n\nThird.", "translated lines have no trailing space: " + repr(joined))

# The settings file is in the per-user application folder
path = settings_module.settings_path()
print("Settings file:", path)
if sys.platform == "win32":
    check(path.startswith(os.environ["APPDATA"]), "settings are stored under %APPDATA%")

# Sentence splitting for Turkish, whose data files were missing from an installer once
sentences, _ = paragraph_tokenizer("Merhaba dünya. Nasılsın?\n\nİyiyim.", "tr")
check(sentences == ["Merhaba dünya.", "Nasılsın?", "İyiyim."], "Turkish text is split into sentences")

# From here on, use a temporary settings file
settings_module.settings_path = lambda: os.path.join(tempfile.mkdtemp(), "settings.json")

import translator

errors = []
translator.showerror = lambda title, message: errors.append((title, message))
translator.showinfo = lambda title, message: errors.append((title, message))

model_dir = sys.argv[1]
root = tk.Tk()
translator.window = root
app = translator.TranslatorGUI(root)
root.update()

if sys.platform == "win32":
    import ctypes

    print("Windows caret blink time (ms):", ctypes.windll.user32.GetCaretBlinkTime())
print("Tk", root.tk.call("info", "patchlevel"), "| text size", app.text_size())

app.load_model(os.path.join(model_dir, "ct2_model"))
app.load_sp_model(os.path.join(model_dir, "sp_model", "fr.model"))
check(app.model_type == "other", "the model is recognised as a bilingual model")


def translate(text):
    app.source_text.delete("1.0", "end")
    app.source_text.insert("1.0", text)
    app.translate_input()
    deadline = time.time() + 120
    while app.worker is not None and time.time() < deadline:
        root.update()
        time.sleep(0.01)
    return app.translation


output = translate("Le comité a approuvé le nouveau budget après un long débat.")
check("committee approved the new budget" in output.lower(), "French is translated to English: " + output.strip())
check(not errors, "no error was reported")

# Files are read and saved as UTF-8
folder = tempfile.mkdtemp()
source_file = os.path.join(folder, "arabic.txt")
with open(source_file, "w", encoding="utf-8") as file:
    file.write("مرحبا بالعالم. كيف حالك اليوم؟\nİyiyim, teşekkürler.\n")
app.read_file(source_file)
check("مرحبا" in app.source_text.get("1.0", "end") and "teşekkürler" in app.source_text.get("1.0", "end"),
      "an Arabic and Turkish UTF-8 file is opened")
check(app.source_rtl, "Arabic text is detected as right to left")

saved_file = os.path.join(folder, "saved.txt")
translator.asksaveasfilename = lambda **options: saved_file
app.show_translation("Привет, мир.\nمرحبا")
app.save_file()
with open(saved_file, "rb") as file:
    saved = file.read()
# Windows text files end their lines with CRLF
check(saved.decode("utf-8").replace("\r\n", "\n").strip() == "Привет, мир.\nمرحبا" and not saved.startswith(b"\xef\xbb\xbf"),
      "a translation is saved as UTF-8")

root.destroy()
print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
