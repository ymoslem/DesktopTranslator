"""Test of the behaviour of DesktopTranslator, with its interface.

Usage: python tests/gui_test.py path/to/fren path/to/nllb-200-model-folder

The first folder holds ct2_model and sp_model/fr.model of the French-to-English model.
The second folder holds a NLLB-200 CTranslate2 model with sentencepiece.model.
"""
import json
import os
import sys
import tempfile
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import utils.settings as settings_module

SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
settings_module.settings_path = lambda: SETTINGS_FILE

import engine
import translator
from utils.rtl import is_rtl_target, add_rtl_marks, strip_bidi_marks

FREN = sys.argv[1]
NLLB = sys.argv[2]
FREN_MODEL, FREN_SP = os.path.join(FREN, "ct2_model"), os.path.join(FREN, "sp_model", "fr.model")
NLLB_SP = os.path.join(NLLB, "sentencepiece.model")

failures = []
errors, infos, questions = [], [], []
translator.showerror = lambda title, message: errors.append((title, message))
translator.showinfo = lambda title, message: infos.append((title, message))
translator.askyesno = lambda title, message: (questions.append(message), False)[1]
FOLDER = tempfile.mkdtemp()


def check(condition, description):
    print(("PASS " if condition else "FAIL ") + description, flush=True)
    if not condition:
        failures.append(description)


root = tk.Tk()
translator.window = root
root.geometry("1400x700")
app = translator.TranslatorGUI(root)
root.update()


def selector():
    return str(app.combobox.cget("state")), app.combobox.get()


def wait():
    deadline = time.time() + 300
    while app.worker is not None and time.time() < deadline:
        root.update()
        time.sleep(0.01)


def run(text, target=None, source=None):
    errors.clear()
    app.source_text.delete("1.0", "end")
    app.source_text.insert("1.0", text)
    if target:
        app.combobox.set(target)
    if source:
        app.source_combobox.set(source)
    app.translate_input()
    wait()
    return app.translation


def open_file(name, content=None, encoding="utf-8"):
    path = os.path.join(FOLDER, name)
    if content is not None:
        with open(path, "w", encoding=encoding) as file:
            file.write(content)
    translator.askopenfilename = lambda **options: path
    errors.clear()
    app.open_file()
    return app.source_text.get("1.0", "end")


# Selectors before, and with, a bilingual model
check(selector() == ("disabled", "Load a model first"), "no model: the target selector is disabled")
app.load_model(FREN_MODEL)
app.load_sp_model(FREN_SP)
check(app.model_type == "other" and selector() == ("disabled", "Not needed"), "bilingual model: no language is asked for")
check(str(app.source_combobox.cget("state")) == "disabled", "bilingual model: the source selector is disabled")
check("Model: ct2_model" in app.model_info.cget("text"), "the model name is shown")
output = run("Le comité a approuvé le nouveau budget après un long débat.\nIl se réunira le mois prochain.\n\nMerci.")
check(output.startswith("The Committee approved") and "\n\n" in output, "French is translated, keeping the paragraphs: " + repr(output))
check(all(line == line.rstrip() for line in output.split("\n")), "no translated line ends with a space")
check(app.source_header.cget("text") == "Source (detected: fr)", "the detected source language is shown")
for text in ("12345 6789", "x x x x", "!!! ???", "a"):
    run(text)
    check(True, "text without letters does not fail: " + repr(text))

# The engine on its own
check(engine.format_duration(45) == "45 s" and engine.format_duration(600) == "10 min" and engine.format_duration(7200) == "2.0 h",
      "durations are formatted")
check(engine.longest_line("a\n" + "b" * 10) == 10, "the longest line is measured")

# Multilingual model
app.load_model(NLLB)
app.load_sp_model(NLLB_SP)
check(app.model_type == "nllb" and selector() == ("readonly", "Select a language..."), "NLLB-200: a language is asked for")
check(len(app.combobox.cget("values")) == 202 and len(app.source_combobox.cget("values")) == 203, "202 languages, and Auto detect for the source")
run("The committee approved the new budget.")
check(errors and errors[0][1] == "Please select the target language.", "no target language is reported")
output = run("The committee approved the new budget after a long debate.", target="French")
check(output.startswith("La commission a approuvé"), "English to French: " + repr(output))
output = run("Komite uzun bir tartışmadan sonra yeni bütçeyi onayladı.", target="English")
check("committee approved the new budget" in output.lower() and app.source_header.cget("text") == "Source (detected: tr)", "Turkish to English: " + repr(output))
app.engine.language_codes = dict(app.engine.language_codes, Bogus="xxx_Latn")
run("Hello world, this is a test.", target="Bogus")
check(errors and "does not support" in errors[0][1], "a language the model lacks is reported")
app.engine.language_codes.pop("Bogus")
output = run("Le comité a approuvé le nouveau budget après un long débat.", target="English", source="French")
check("committee approved the new budget" in output.lower() and app.source_header.cget("text") == "Source", "a selected source language is used")

# Join lines
text = "The committee met on Monday to discuss the\nnew budget and decided to approve it\nafter a long debate."
app.join_lines_option.set(True)
check("\n" not in run(text, target="French", source="Auto detect"), "Join Lines on: one sentence")
app.join_lines_option.set(False)
check("\n" in run(text, target="French"), "Join Lines off: the lines stay apart")

# Right-to-left target
output = run("Hello, how are you today?\n\nThank you very much.", target="Arabic (Modern Standard)")
shown = app.target_text.get("1.0", "end")
check(app.target_locked and str(app.target_text.cget("state")) == "disabled" and "‫" in shown and "‫" not in app.translation,
      "an Arabic translation is read-only, with direction marks: " + repr(output))
app.target_text.focus_force()
root.update()
cursor = app.target_text.index("insert")
for sequence in ("<Button-1>", "<B1-Motion>", "<Shift-Button-1>", "<ButtonRelease-1>"):
    app.target_text.event_generate(sequence, x=300, y=12)
    root.update()
check(not app.target_text.tag_ranges("sel") and app.target_text.index("insert") == cursor, "clicks do not select or move the cursor")
app.button_copy.invoke()
check(root.clipboard_get() == app.translation and "‫" not in root.clipboard_get(), "Copy copies the text without marks")
saved = os.path.join(FOLDER, "saved.txt")
translator.asksaveasfilename = lambda **options: saved
app.save_file()
with open(saved, "rb") as file:
    data = file.read()
check(b"\xef\xbb\xbf" not in data[:3] and "‫" not in data.decode("utf-8") and "مرحبا" in data.decode("utf-8"),
      "the saved file is UTF-8 without marks")
translator.asksaveasfilename = lambda **options: ""
app.save_file()
check(True, "cancelling the Save dialog does not fail")
app.rtl_view_option.set(False)
app.toggle_rtl_view()
check(str(app.target_text.cget("state")) == "normal" and "‫" not in app.target_text.get("1.0", "end"), "the view can be switched off to edit")
app.target_text.insert("end", "تعديل")
app.rtl_view_option.set(True)
app.toggle_rtl_view()
check("تعديل" in app.translation and app.target_locked, "edits survive switching the view on again")
run("Good morning.", target="French")
check(not app.target_locked and str(app.target_text.cget("state")) == "normal", "other languages stay editable")
app.clear()
infos.clear()
app.save_file()
check(infos and infos[0][1] == "Nothing to save!", "an empty translation is not saved")

# Right-to-left source
app.source_combobox.set("Arabic (Modern Standard)")
app.on_source_selected()
check(app.source_rtl, "an Arabic source language right-aligns the source")
app.source_combobox.set("Auto detect")
app.on_source_selected()
check(not app.source_rtl, "Auto detect with no text goes back to left to right")
arabic = "مرحبا بالعالم. كيف حالك اليوم؟\nشكرا جزيلا."
app.source_text.insert("1.0", arabic)
app.update_source_direction()
root.update()
box = app.source_text.bbox("1.0")
check(app.source_rtl and box[0] > app.source_text.winfo_width() / 2, "detected Arabic is drawn on the right")

# Cancelling, progress, and the time left
long_text = " ".join(["The committee approved the new budget after a long debate in the main hall."] * 40)
app.source_text.delete("1.0", "end")
app.source_text.insert("1.0", long_text)
app.combobox.set("French")
statuses, ticks = [], []
app.translate_input()
started = time.time()
while app.worker is not None and time.time() - started < 6:
    root.update()
    statuses.append(app.statusbar.cget("text"))
    ticks.append(time.time())
    time.sleep(0.02)
check(len(ticks) > 50 and app.button_translate.cget("text") == "Cancel", "the window stays responsive while translating")
check(any("left" in status for status in statuses), "the time left is shown")
app.button_translate.invoke()
wait()
check(app.statusbar.cget("text") == "Translation cancelled." and app.button_translate.cget("text") == "Translate", "translation can be cancelled")

# Files
check("é" in open_file("utf8.txt", "Le comité a approuvé le nouveau budget.\n") and "Encoding: utf-8" in app.statusbar.cget("text"), "a UTF-8 file is opened")
open_file("bom.txt", "Hello world.\n", "utf-8-sig")
check(app.source_text.get("1.0", "end").startswith("Hello"), "a byte order mark is dropped")
open_file("latin1.txt", "Le café est très bon. Où est la gare ?\n", "latin-1")
translator.askstring = lambda *args, **options: "latin-1"
app.reopen_with_encoding()
check(app.source_text.get("1.0", "end").startswith("Le café est très bon. Où est la gare ?"), "a file can be reopened with another encoding")
translator.askstring = lambda *args, **options: "no-such-encoding"
app.reopen_with_encoding()
check("unknown encoding" in errors[-1][1].lower(), "an unknown encoding is reported")
translator.askopenfilename = lambda **options: os.path.join(FOLDER, "missing.txt")
errors.clear()
app.open_file()
check(errors and errors[0][0] == "Cannot open the file", "a missing file is reported")
questions.clear()
open_file("long.txt", "x " * 60000)
check(questions and "120,000 characters" in questions[0], "a very long line asks first")

# Remembering the last model and language
app.remember_paths.set(True)
app.load_model(NLLB)
app.load_sp_model(NLLB_SP)
app.combobox.set("French")
app.on_target_selected()
saved_settings = json.load(open(SETTINGS_FILE))
check(saved_settings["ct2_model"] == NLLB and saved_settings["target_language"] == {"nllb": "French"}, "the model and the language are saved")
app.main_frame.destroy()
app = translator.TranslatorGUI(root)
check(app.translator is None and selector() == ("readonly", "French") and "Last used model" in app.statusbar.cget("text"),
      "the next session shows them, without loading the model")
check(run("The committee approved the new budget.").startswith("Le comité"), "the model is loaded when translating")
app.remember_paths.set(False)
app.store_settings()
check("target_language" not in json.load(open(SETTINGS_FILE)), "turning remembering off removes them")

root.destroy()
print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
