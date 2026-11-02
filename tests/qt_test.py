"""Test of the Qt interface.

Usage: QT_QPA_PLATFORM=offscreen python tests/qt_test.py path/to/fren path/to/nllb-200-model-folder
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import utils.settings as settings_module

SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
settings_module.settings_path = lambda: SETTINGS_FILE

from PySide6.QtCore import QMimeData, QUrl, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

import qt_app

FREN, NLLB = sys.argv[1], sys.argv[2]
FOLDER = tempfile.mkdtemp()
failures, messages = [], []


def check(condition, description):
    print(("PASS " if condition else "FAIL ") + description, flush=True)
    if not condition:
        failures.append(description)


QMessageBox.critical = staticmethod(lambda parent, title, text, *a: messages.append((title, text)))
QMessageBox.information = staticmethod(lambda parent, title, text, *a: messages.append((title, text)))
QMessageBox.question = staticmethod(lambda *a, **k: (messages.append(a[2]), QMessageBox.StandardButton.No)[1])
app = QApplication([])


def wait(window, seconds=300):
    deadline = time.time() + seconds
    while window.worker is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def translate(window, text, target=None, source=None):
    messages.clear()
    window.source_text.setPlainText(text)
    if target:
        window.target_combo.choose(target)
    if source:
        window.source_combo.choose(source)
    window.translate_or_cancel()
    wait(window)
    return window.translation


window = qt_app.Window()
window.show()
check(window.target_combo.currentText() == "Open a model first" and not window.target_combo.isEnabled(), "no model: the target list is disabled")

# A bilingual model, opened with the folder dialog; two SentencePiece files need a choice
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: os.path.join(FREN, "ct2_model"))
asked = []
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (asked.append(a[2]), os.path.join(FREN, "sp_model", "fr.model"))[1:] and (os.path.join(FREN, "sp_model", "fr.model"), ""))
window.open_model()
check(asked and asked[0].endswith("sp_model"), "two SentencePiece files: the user is asked, starting in their folder")
check(window.target_combo.currentText() == "Not needed" and not window.source_combo.isEnabled(), "bilingual model: no language is asked for")
output = translate(window, "Le comité a approuvé le nouveau budget après un long débat.\n\nMerci.")
check(output.startswith("The Committee approved") and "\n\n" in output, "French is translated: " + repr(output))
check(all(line == line.rstrip() for line in output.split("\n")), "no line ends with a space")
check(window.source_header.text() == "Source (detected: fr)", "the detected language is shown")

# A multilingual model with one SentencePiece file inside: no question
asked.clear()
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: NLLB)
window.open_model()
check(not asked and window.engine.sp_model is not None, "one SentencePiece file inside the folder is used without asking")
check(window.target_combo.isEditable() and window.target_combo.count() == 202 and window.source_combo.count() == 203, "NLLB-200: 202 languages, and Auto detect")
translate(window, "The committee approved the new budget.")
check(messages and messages[0][1] == "Please select the target language.", "a target language is required")
output = translate(window, "The committee approved the new budget after a long debate.", target="French")
check(output.startswith("La commission a approuvé"), "English to French: " + repr(output))
check(window.selected_target() == "French" and window.detected_name == "English", "the detected language is kept for swapping")
window.swap_languages()
check(window.selected_source() == "French" and window.selected_target() == "English", "the languages are swapped")
output = translate(window, "La commission a approuvé le nouveau budget après un long débat.")
check("approved the new budget" in output.lower(), "French to English with the swapped languages: " + repr(output))
output = translate(window, "Merhaba dünya.", target="English", source="Turkish")
check("hello" in output.lower() and window.source_header.text() == "Source", "a selected source language is used: " + repr(output))
window.source_combo.choose("Auto detect")
check(window.source_combo.completer() is not None, "the language lists can be searched by typing")

# Right-to-left text takes its direction from each paragraph
translate(window, "Hello, how are you today?\n\nThank you very much.", target="Arabic (Modern Standard)")
block = window.target_text.document().firstBlock()
check(block.textDirection() == Qt.LayoutDirection.RightToLeft, "an Arabic translation is right to left")
window.source_text.setPlainText("مرحبا بالعالم.\nHello world.")
check(window.source_text.document().firstBlock().textDirection() == Qt.LayoutDirection.RightToLeft
      and window.source_text.document().firstBlock().next().textDirection() == Qt.LayoutDirection.LeftToRight,
      "in the source, Arabic and English paragraphs have their own direction")

# Files
path = os.path.join(FOLDER, "arabic.txt")
with open(path, "w", encoding="utf-8") as file:
    file.write("مرحبا بالعالم.\nİyiyim.\n")
window.open_text_file(path)
check("مرحبا" in window.source_text.toPlainText() and "utf-8" in window.status_label.text(), "a UTF-8 file is opened: " + window.status_label.text())
latin = os.path.join(FOLDER, "latin1.txt")
with open(latin, "w", encoding="latin-1") as file:
    file.write("Le café est très bon. Où est la gare ?\n")
window.open_text_file(latin)
QInputDialog.getText = staticmethod(lambda *a, **k: ("latin-1", True))
window.reopen_with_encoding()
check(window.source_text.toPlainText().startswith("Le café est très bon. Où est la gare ?"), "a file is reopened with another encoding")
window.open_text_file(os.path.join(FOLDER, "missing.txt"))
check(messages and messages[-1][0] == "Cannot open the file", "a missing file is reported")
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(path)])
window.source_text.setPlainText("")
window.source_text.insertFromMimeData(mime)
check("مرحبا" in window.source_text.toPlainText(), "a dropped text file is opened")
messages.clear()
window.open_text_file(os.path.join(FOLDER, "long.txt")) if False else None
long_path = os.path.join(FOLDER, "long.txt")
with open(long_path, "w", encoding="utf-8") as file:
    file.write("x " * 60000)
window.open_text_file(long_path)
check(messages and "120,000 characters" in messages[-1], "a very long line asks first")

translate(window, "Good morning.", target="French")
saved = os.path.join(FOLDER, "saved.txt")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (saved, ""))
window.save_translation()
with open(saved, "rb") as file:
    data = file.read()
check(data.decode("utf-8").strip() == window.translation.strip() and data[:3] != b"\xef\xbb\xbf", "the translation is saved as UTF-8")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
window.save_translation()
check(True, "cancelling the Save dialog does not fail")
window.copy_translation()
check(QApplication.clipboard().text().strip() == window.translation.strip(), "Copy copies the translation")
window.clear()
messages.clear()
window.save_translation()
check(messages and "nothing to save" in messages[-1][1].lower(), "an empty translation is not saved")

# Cancelling, the progress bar and the time left
long_text = " ".join(["The committee approved the new budget after a long debate in the main hall."] * 120)  # long enough to still be translating after 5 seconds
window.source_text.setPlainText(long_text)
window.target_combo.choose("French")
window.translate_or_cancel()
started, statuses = time.time(), []
while window.worker is not None and time.time() - started < 5:
    app.processEvents()
    statuses.append(window.status_label.text())
    time.sleep(0.02)
check(window.translate_button.text() == "Cancel" and window.progress_bar.isVisibleTo(window) and any("left" in s for s in statuses),
      "while translating, the button says Cancel, a progress bar shows, and the time left is shown")
window.cancel_action.trigger()
wait(window)
check(window.status_label.text() == "Translation cancelled." and window.translate_button.text() == "Translate" and not window.target_text.toPlainText(),
      "translation can be cancelled")

# A model that may not fit in the memory asks first
model_before = window.engine.model_dir
original = qt_app.memory_warning
qt_app.memory_warning = lambda model_dir: "This model needs about 5.4 GB of memory, and 2.0 GB is free now."
messages.clear()
check(window.load_model(FREN + "/ct2_model") is False and messages and "5.4 GB" in messages[-1] and window.engine.model_dir == model_before,
      "a model that may not fit in the memory is not opened without a yes")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
check(window.load_model(FREN + "/ct2_model") is True and window.engine.model_dir == FREN + "/ct2_model", "it is opened after a yes")
qt_app.memory_warning = original
window.load_model(NLLB)
window.target_combo.choose("French")
QMessageBox.question = staticmethod(lambda *a, **k: (messages.append(a[2]), QMessageBox.StandardButton.No)[1])

# The detected language by name, the word count, the focus, and the layout
translate(window, "The committee approved the new budget after a long debate.", target="French", source="Auto detect")
check(window.source_header.text() == "Source (detected: English)", "the detected language is shown by name: " + window.source_header.text())
for text, expected in (("one two three", "3 words"), ("one", "1 word"), ("", ""), ("a, b" + " c" * 1200, "1,202 words")):
    window.source_text.setPlainText(text)
    deadline = time.time() + 3
    while window.count_label.text() != expected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(window.count_label.text() == expected, "the word count shows %r: %r" % (expected, window.count_label.text()))
window.load_model(NLLB)
check(window.focusWidget() is window.source_text, "the cursor is in the source pane after opening a model")
top_row_bottom = window.target_combo.mapTo(window, window.target_combo.rect().bottomLeft()).y()
header_top = window.source_header.mapTo(window, window.source_header.rect().topLeft()).y()
check(0 <= header_top - top_row_bottom <= 24, "the headers are close to the toolbar: %d px" % (header_top - top_row_bottom))
centre = lambda label: label.mapTo(window, label.rect().center()).y()
check(abs(centre(window.source_header) - centre(window.target_header)) <= 1, "both headers are centred on the same line")

# Text size and the menus
sizes = [window.source_text.font().pointSize()]
for name in ("Larger Text", "Larger Text", "Smaller Text", "Actual Size"):
    next(a for a in window.findChildren(qt_app.QAction) if a.text() == name).trigger()
    sizes.append((window.source_text.font().pointSize(), window.target_text.font().pointSize()))
check(sizes == [14, (15, 15), (16, 16), (15, 15), (14, 14)], "the text can be made larger and smaller in both panes: " + str(sizes))
larger = next(a for a in window.findChildren(qt_app.QAction) if a.text() == "Larger Text")
check(any(k.toString() == "Ctrl+=" for k in larger.shortcuts()), "Ctrl+= also makes the text larger")
about = next(a for a in window.findChildren(qt_app.QAction) if a.text().startswith("About"))
check(about.menuRole() == qt_app.QAction.MenuRole.NoRole and any(a is about for a in window.menuBar().actions()[-1].menu().actions()), "About is in the Help menu")

# Preferences, and the next session
window.preferences.set("beam_size", 5)
window.preferences.set("join_lines", True)
window.save_settings()
window.close()
saved_settings = json.load(open(SETTINGS_FILE))
check(saved_settings["ct2_model"] == NLLB and saved_settings["beam_size"] == 5 and saved_settings["target_language"] == {"nllb": "French"} and "geometry" in saved_settings,
      "the model, the language, the quality and the window are saved")
window = qt_app.Window()
check(window.engine.translator is None and window.target_combo.currentText() == "French" and "Last used model" in window.status_label.text(),
      "the next session shows the last model and language without loading it")
output = translate(window, "The committee approved the new budget.")
check(output.startswith("Le comité") and window.engine.translator is not None, "the model is loaded when translating: " + repr(output))
text = "The committee met on Monday to discuss the\nnew budget and decided to approve it\nafter a long debate."
check("\n" not in translate(window, text), "Join Lines from the preferences joins the lines")
dialog = qt_app.PreferencesDialog(window, 5, True, False)
check(dialog.values() == (5, True, False), "the preferences window shows the saved values")
window.close()
print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
