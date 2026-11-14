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

from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QInputDialog, QMessageBox, QToolTip

import engine as engine_module
import gui.widgets
import gui.workers
import qt_app
from utils.paragraph_splitter import TextBuilder, paragraph_detokenizer

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
check(window.source_header.text().startswith("Source (detected: fr, "), "the detected language is shown")

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
check("hello" in output.lower() and window.source_header.text().startswith("Source (") and "detected" not in window.source_header.text(), "a selected source language is used: " + repr(output))
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
    file.write("x" * 120000)  # one very long line, but only one word
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
long_text = " ".join("The committee approved the new budget number %d after a long debate in the main hall." % i for i in range(120))  # long enough to still be translating after 5 seconds
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
check("cancelled" in window.status_label.text() and window.translate_button.text() == "Translate" and not window.target_text.isReadOnly(),
      "translation can be cancelled, and the pane can be edited again")

# A model that may not fit in the memory asks first
model_before = window.engine.model_dir
original = qt_app.memory_warning
qt_app.memory_warning = lambda model_dir: "This model needs about 6.1 GB of memory, and 2.0 GB is free now."
messages.clear()
check(window.load_model(FREN + "/ct2_model") is False and messages and "6.1 GB" in messages[-1] and window.engine.model_dir == model_before,
      "a model that may not fit in the memory is not opened without a yes")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
check(window.load_model(FREN + "/ct2_model") is True and window.engine.model_dir == FREN + "/ct2_model", "it is opened after a yes")
qt_app.memory_warning = original
window.load_model(NLLB)
window.target_combo.choose("French")
QMessageBox.question = staticmethod(lambda *a, **k: (messages.append(a[2]), QMessageBox.StandardButton.No)[1])

# The detected language by name, the word count, the focus, and the layout
translate(window, "The committee approved the new budget after a long debate.", target="French", source="Auto detect")
check(window.source_header.text().startswith("Source (detected: English, "), "the detected language is shown by name: " + window.source_header.text())
for text, expected in (("one two three", "Source (detected: English, 3 words)"), ("one", "Source (detected: English, 1 word)"), ("", "Source"), ("a, b" + " c" * 1200, "Source (detected: English, 1,202 words)")):
    window.source_text.setPlainText(text)
    deadline = time.time() + 3
    while window.source_header.text() != expected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(window.source_header.text() == expected, "the word count shows %r: %r" % (expected, window.source_header.text()))
window.load_model(NLLB)
check(window.focusWidget() is window.source_text, "the cursor is in the source pane after opening a model")
top_row_bottom = window.target_combo.mapTo(window, window.target_combo.rect().bottomLeft()).y()
header_top = window.source_header.mapTo(window, window.source_header.rect().topLeft()).y()
check(0 <= header_top - top_row_bottom <= 24, "the headers are close to the toolbar: %d px" % (header_top - top_row_bottom))
centre = lambda label: label.mapTo(window, label.rect().center()).y()
check(abs(centre(window.source_header) - centre(window.target_header)) <= 1, "both headers are centred on the same line")

# The repetition penalty is off by default, and a preference turns it on
penalties = []
real_translate_batch = window.engine.translate_batch
window.engine.translate_batch = lambda *a, **k: (penalties.append(a[4] if len(a) > 4 else k.get("repetition_penalty")), real_translate_batch(*a, **k))[1]
translate(window, "The committee approved the new budget.", target="French")
check(penalties and set(penalties) == {1.0}, "no repetition penalty by default: " + str(set(penalties)))
penalties.clear()
window.preferences.set("repetition_penalty", 1.2)
translate(window, "The committee approved the new budget.")
check(penalties and set(penalties) == {1.2}, "the preference turns on the penalty of 1.2: " + str(set(penalties)))
window.preferences.set("repetition_penalty", 1.0)
window.engine.translate_batch = real_translate_batch

# The text builder gives the same text as the detokenizer, step by step
for sentences, breaks in ((["A.", "B.", "C."], [0, 1, "\n", "\n", 2]), (["A.", "B."], [0, "\n", 1]), (["A."], [0])):
    builder, built = TextBuilder(breaks), ""
    for count in range(1, len(sentences) + 1):
        built += builder.add(sentences[:count])
    check(built.rstrip() == paragraph_detokenizer(sentences, breaks).rstrip(), "the text built step by step is the same: " + repr(built))

# The translation is shown as it is produced, and a cancel keeps the translated part
many = " ".join("The committee approved the new budget number %d after a long debate in the main hall." % i for i in range(30))
window.source_text.setPlainText(many)
window.target_combo.choose("French")
window.translate_or_cancel()
lengths, read_only, copy_enabled = [], [], []
started = time.time()
while window.worker is not None and time.time() - started < 120:
    app.processEvents()
    if window.worker is not None:
        lengths.append(len(window.target_text.toPlainText()))
        read_only.append(window.target_text.isReadOnly())
        copy_enabled.append(window.copy_button.isEnabled())
    time.sleep(0.02)
check(any(0 < n < max(lengths) for n in lengths) and all(read_only), "the translation grows while it is made, and the pane is read-only meanwhile")
check(copy_enabled and not any(copy_enabled) and window.copy_button.isEnabled(), "Copy is disabled while translating, and enabled after")
check(not window.target_text.isReadOnly() and window.target_text.toPlainText().rstrip() == window.translation, "the final text is the translation, and the pane can be edited")
window.source_text.setPlainText(many + " " + many)
window.translate_or_cancel()
started = time.time()
while not window.target_text.toPlainText() and time.time() - started < 60:
    app.processEvents()
    time.sleep(0.02)
window.cancel_action.trigger()
wait(window)
partial = window.target_text.toPlainText()
check(partial and partial.rstrip() == window.translation and len(partial) < 2 * len(window.translation) + 10 and "kept" in window.status_label.text(),
      "a cancel keeps the translated part: %d characters" % len(partial))

# A text over the word limit is offered as a document
offers = []
window.offer_document = lambda words, path=None: offers.append((words, path)) or False
qt_app.WORD_LIMIT = 20
messages.clear()
window.source_text.setPlainText("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one")
window.translate_or_cancel()
check(offers and offers[0][0] == 21 and window.worker is None, "a text over the limit is not translated in the window: " + str(offers))
window.source_text.setPlainText("Short text.")
long_file = os.path.join(FOLDER, "words.txt")
with open(long_file, "w", encoding="utf-8") as file:
    file.write("word " * 30)
# Files that are not plain text are explained, in the window and in document mode
for name, start in (("a.pdf", b"%PDF-1.7\n"), ("b.docx", b"PK\x03\x04\x14\x00"), ("c.doc", b"\xd0\xcf\x11\xe0\xa1\xb1")):
    not_text = os.path.join(FOLDER, name)
    with open(not_text, "wb") as file:
        file.write(start + b"\x00" * 40)
    messages.clear()
    window.open_text_file(not_text)
    check(messages and messages[-1][0] == "Not a plain text file" and "plain text" in messages[-1][1] and window.source_text.toPlainText() == "Short text.",
          "%s is explained, and not loaded" % name)
try:
    window.engine.translate_file(not_text, os.path.join(FOLDER, "never.txt"), "fra_Latn")
    check(False, "a Word file is refused in document mode")
except engine_module.EngineError as error:
    check(error.title == "Not a plain text file", "a Word file is refused in document mode")
offers.clear()
window.open_text_file(long_file)
check(offers and offers[0][1] == long_file and window.source_text.toPlainText() == "Short text.", "a file over the limit is offered as a document, and is not loaded")
qt_app.WORD_LIMIT = engine_module.WORD_LIMIT
del window.offer_document

# Document mode
paragraphs = ["The committee approved the new budget after a long debate. It will meet again next month. The members were pleased.",
              "Thank you very much for your help. Does this work for you? We hope so.", "Good morning. See you tomorrow.",
              "The weather is nice today. We went for a walk. The park was full of people."]
document = os.path.join(FOLDER, "document.txt")
with open(document, "w", encoding="utf-8") as file:
    file.write("\n\n".join(paragraphs) + "\n")
window.target_combo.choose("French")
window.source_combo.choose("Auto detect")
sentences, breaks, batches, _ = window.engine.split("\n\n".join(paragraphs), "en")
expected = paragraph_detokenizer(window.engine.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks) + "\n"
saved_documents = []


def run_document(path, output, cancel_after_first=False):
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (output, ""))

    def run_dialog(self):
        if cancel_after_first:
            real = window.engine.translate_batch
            calls = []

            def cancel_after_one_batch(*args, **kw):
                result = real(*args, **kw)
                calls.append(1)
                self.worker.cancel = True  # the first batch is translated, so stop
                return result

            window.engine.translate_batch = cancel_after_one_batch
        self.start()
        while self.worker.isRunning() or self.outcome == "":
            app.processEvents()
            time.sleep(0.01)
        if cancel_after_first:
            window.engine.translate_batch = real
        return 0

    qt_app.DocumentDialog.exec = run_dialog
    window.translate_document(path)


output_file = os.path.join(FOLDER, "document.French.txt")
run_document(document, output_file)
with open(output_file, encoding="utf-8") as file:
    produced = file.read()
check(produced == expected and "done" in window.status_label.text().lower() or "translated" in window.status_label.text().lower(), "a document is translated to a file with the same paragraphs: " + repr(produced[:60]))
check(produced == expected, "the file has the translation, with the blank lines kept, and no trailing spaces")
engine_module.DOCUMENT_LINES = 2
run_document(document, output_file)
with open(output_file, encoding="utf-8") as file:
    produced_in_parts = file.read()
check(produced_in_parts == expected, "translating in small parts gives the same file")
engine_module.DOCUMENT_LINES = 3
cancelled_file = os.path.join(FOLDER, "cancelled.txt")
run_document(document, cancelled_file, cancel_after_first=True)
with open(cancelled_file, encoding="utf-8") as file:
    partial_document = file.read()
check(0 < len(partial_document) < len(expected) and expected.startswith(partial_document.rstrip()) and "Cancelled" in window.status_label.text(),
      "a cancelled document keeps the translated part: %d of %d characters" % (len(partial_document), len(expected)))
engine_module.DOCUMENT_LINES = 200

# A repeated sentence is translated once, and gets the same translation everywhere
sentences = ["The committee approved the new budget.", "It will meet again next month.", "The committee approved the new budget."] * 6
batches = [sentences[i : i + 8] for i in range(0, len(sentences), 8)]
sent, real = [], window.engine.translate_batch
window.engine.translate_batch = lambda batch, *args, **kw: (sent.extend(batch), real(batch, *args, **kw))[1]
translated = window.engine.translate(batches, 3, window.engine.target_language("French"), "eng_Latn")
window.engine.translate_batch = real
check(len(translated) == len(sentences) and len(sent) == 2 and len(set(translated[0::3])) == 1 and translated[0] == translated[2],
      "repeated sentences are translated once: %d of %d sentences sent to the model" % (len(sent), len(sentences)))
messages.clear()
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (document, ""))
window.translate_document(document)
check(messages and "different file" in messages[-1][1], "the output file must differ from the input file")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))

# Text size and the menus
sizes = [window.source_text.font().pointSize()]
for name in ("Larger Text", "Larger Text", "Smaller Text", "Actual Size"):
    next(a for a in window.findChildren(qt_app.QAction) if a.text() == name).trigger()
    sizes.append((window.source_text.font().pointSize(), window.target_text.font().pointSize()))
check(sizes == [14, (15, 15), (16, 16), (15, 15), (14, 14)], "the text can be made larger and smaller in both panes: " + str(sizes))
larger = next(a for a in window.findChildren(qt_app.QAction) if a.text() == "Larger Text")
check(any(k.toString() == "Ctrl+=" for k in larger.shortcuts()), "Ctrl+= also makes the text larger")
about = next(a for a in window.findChildren(qt_app.QAction) if a.text().startswith("About"))
check(about.menuRole() == qt_app.QAction.MenuRole.AboutRole and any(a is about for a in window.menuBar().actions()[-1].menu().actions()), "About has the About role, and is in the Help menu except on macOS")
shown = []
real_exec = qt_app.QMessageBox.exec
qt_app.QMessageBox.exec = lambda box: shown.append((box.text(), box.informativeText())) or 0
window.show_about()
qt_app.QMessageBox.exec = real_exec
check(shown and qt_app.APP_NAME in shown[0][0] and "Version " + qt_app.VERSION in shown[0][1] and qt_app.NOTICE_URL in shown[0][1]
      and qt_app.APP_NAME not in shown[0][1].split("<br>")[0], "About shows the name as the main text, and the version and links below")
report = next(a for a in window.menuBar().actions()[-1].menu().actions() if a.text() == "Report an Issue...")
opened = []
real_open = qt_app.QDesktopServices.openUrl
qt_app.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
report.trigger()
qt_app.QDesktopServices.openUrl = real_open
check(opened == ["https://github.com/ymoslem/DesktopTranslator/issues"], "Report an Issue in the Help menu opens the issues page: " + str(opened))

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
dialog = qt_app.PreferencesDialog(window, 5, True, False, True)
check(dialog.values() == (5, True, False, True), "the preferences window shows the saved values")
check(dialog.load_at_start.isChecked() and not dialog.load_at_start.isEnabled(), "loading at start is on by default, and off for a model that is not remembered")

# Loading the last model at the start
starter = qt_app.Window()
starter.preferences.set("load_at_start", False)
starter.load_last_model()
check(starter.engine.translator is None and starter.pending_model, "with the option off, the last model waits for the first translation")
starter.preferences.set("load_at_start", True)
real_warning = qt_app.memory_warning
qt_app.memory_warning = lambda model_dir: "This model needs about 6.1 GB of memory, and 2.0 GB is free now."
starter.load_last_model()
check(starter.engine.translator is None and starter.pending_model and "may not fit in memory" in starter.status_label.text(),
      "a model that may not fit in memory waits for the first translation")
qt_app.memory_warning = real_warning
starter.load_last_model()
check(starter.engine.translator is not None and starter.engine.sp_model is not None and not starter.pending_model, "the last model is loaded at the start")
starter.close()
window.close()

# Downloading a model: the engine, with a local server
import hashlib
import http.server
import io
import shutil
import threading
import zipfile

archive = io.BytesIO()
with zipfile.ZipFile(archive, "w") as zipped:
    zipped.writestr("tiny-model/model.bin", b"x" * 100000)
    zipped.writestr("tiny-model/sentencepiece.model", b"sp")
payload = archive.getvalue()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        for i in range(0, len(payload), 10000):
            self.wfile.write(payload[i : i + 10000])
            time.sleep(0.005)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
info = {"name": "Tiny model", "url": "http://127.0.0.1:%d/m.zip" % server.server_port, "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload), "folder": "tiny-model"}
models = engine_module.models_dir()
progress = []
folder = engine_module.download_model(info, on_progress=lambda done, total: progress.append((done, total)))
check(folder == os.path.join(models, "tiny-model") and os.path.isfile(os.path.join(folder, "model.bin")) and engine_module.downloaded_model(info) == folder,
      "a model is downloaded and extracted into the models folder")
check(progress and progress[-1] == (len(payload), len(payload)) and os.listdir(models) == ["tiny-model"], "the progress is reported, and nothing else is left behind")
try:
    engine_module.download_model(dict(info, sha256="0" * 64))
    check(False, "a damaged download is refused")
except engine_module.EngineError as error:
    check(error.title == "Download failed" and "damaged" in error.message and os.listdir(models) == ["tiny-model"], "a damaged download is refused, and removed")
seen = []
check(engine_module.download_model(info, is_cancelled=lambda: len(seen) > 0, on_progress=lambda done, total: seen.append(done)) is None
      and os.listdir(models) == ["tiny-model"], "a cancelled download returns nothing, and leaves nothing")
try:
    engine_module.download_model(dict(info, url="http://127.0.0.1:1/m.zip"))
    check(False, "an unreachable server is reported")
except engine_module.EngineError as error:
    check(error.title == "Download failed" and "Internet" in error.message, "an unreachable server is reported: " + error.message[:60])
server.shutdown()
shutil.rmtree(models)

# The welcome dialog at the first start
with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
    json.dump({}, file)
shown = []
choice = {"value": "later", "skip": False}


def fake_welcome(self):
    shown.append(1)
    self.choice = choice["value"]
    self.skip.setChecked(choice["skip"])
    return 0


def run_download(self):
    self.start_time = time.time()
    self.worker.start()
    deadline = time.time() + 30
    while self.worker.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()  # delivers the signal that the worker has finished
    return 0


qt_app.WelcomeDialog.exec = fake_welcome
qt_app.DownloadDialog.exec = run_download
fresh = qt_app.Window()
fresh.offer_first_model()
check(len(shown) == 1 and fresh.engine.translator is None and not fresh.preferences.get("skip_welcome", False),
      "the welcome dialog is shown at the first start, and Later changes nothing")
choice["skip"] = True
fresh.offer_first_model()
check(json.load(open(SETTINGS_FILE)).get("skip_welcome") is True, "Do not show this again is saved")
fresh.offer_first_model()
check(len(shown) == 2, "the welcome dialog is not shown again after that")
fresh.preferences.set("skip_welcome", False)
choice.update(value="download", skip=False)
downloads = []


def fake_download(is_cancelled=None, on_progress=None):
    downloads.append(1)
    on_progress(5e6, 10e6)
    return FREN + "/ct2_model"


gui.workers.download_model = fake_download
messages.clear()
fresh.offer_first_model()
check(downloads and fresh.engine.model_dir == FREN + "/ct2_model" and fresh.engine.sp_model is not None, "Download downloads the model, opens it, and finds its SentencePiece model")
with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
    json.dump({}, file)
fresh = qt_app.Window()
gui.workers.download_model = lambda is_cancelled=None, on_progress=None: (_ for _ in ()).throw(engine_module.EngineError("Download failed", "No Internet"))
messages.clear()
fresh.offer_first_model()
check(messages and messages[-1] == ("Download failed", "No Internet") and fresh.engine.translator is None, "a failed download is explained")
gui.workers.download_model = lambda is_cancelled=None, on_progress=None: None
fresh.offer_first_model()
check("cancelled" in fresh.status_label.text() and fresh.engine.translator is None, "a cancelled download is said so")
texts = lambda downloaded: [b.text() for b in qt_app.WelcomeDialog(fresh, downloaded).findChildren(qt_app.QPushButton)]
check(texts(False)[0].startswith("Download ") and texts(True)[0].startswith("Use "), "the first button downloads the model, or uses the one that is already there")
fresh.close()

# GPU selection, with CTranslate2 replaced, because the test machine may have no NVIDIA GPU
ct2 = engine_module.ctranslate2
real = (ct2.Translator, ct2.get_cuda_device_count, ct2.get_supported_compute_types)
calls, gpu_full = [], []


def fake_translator(model_dir, **kwargs):
    calls.append(kwargs)
    if kwargs.get("device") == "cuda" and gpu_full:
        raise RuntimeError("CUDA failed with error out of memory")
    return object()


def load_on(device, gpus, types):
    ct2.get_cuda_device_count = lambda: gpus
    ct2.get_supported_compute_types = lambda name: types
    calls.clear()
    loaded = engine_module.Engine()
    loaded.load_model(NLLB, device)
    return loaded, calls[-1]


ct2.Translator = fake_translator
engine, used = load_on("cpu", 1, {"float16"})
check(engine.device == "cpu" and used["device"] == "cpu", "the CPU is the default device")
engine, used = load_on("cuda", 0, {"float16"})
check(engine.device == "cpu" and used["device"] == "cpu", "without a GPU, the CPU is used")
engine, used = load_on("cuda", 1, {"int8", "float16", "int8_float16", "float32"})
check(engine.device == "cuda" and used["device"] == "cuda" and used["compute_type"] == "float16", "a GPU runs a model as float16")
engine, used = load_on("cuda", 1, {"int8", "float32"})
check(used["compute_type"] == "float32", "a GPU without float16 runs a model as float32")
engine, used = load_on("cuda", 1, {"int8"})
check(used["compute_type"] == "default", "a GPU with no known type keeps the type of the model")
engine = engine_module.Engine()
gpu_full.append(True)
ct2.get_cuda_device_count = lambda: 1
ct2.get_supported_compute_types = lambda name: {"float32"}
try:
    engine.load_model(NLLB, "cuda")
    raised = None
except engine_module.EngineError as error:
    raised = error
check(raised is not None and "out of memory" in raised.message and engine.translator is None and engine.device == "cpu", "a GPU that cannot load the model is explained, and nothing changes")
check("CUDA 12" not in raised.message, "a GPU that is out of memory is not blamed on missing CUDA libraries")
gpu_full.clear()
missing = ct2.Translator


def no_cublas(model_dir, **kwargs):
    if kwargs.get("device") == "cuda":
        raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
    return object()


ct2.Translator = no_cublas
try:
    engine_module.Engine().load_model(NLLB, "cuda")
    raised = None
except engine_module.EngineError as error:
    raised = error
ct2.Translator = missing
check(raised is not None and "cublas64_12.dll" in raised.message and "CUDA 12.x" in raised.message and "Preferences" in raised.message,
      "a missing CUDA library is named, with what to install")

# A model that does not fit on the GPU as float16 is loaded as int8_float16


def fits_only_in_8_bits(model_dir, **kwargs):
    calls.append(kwargs)
    if kwargs.get("device") == "cuda" and kwargs.get("compute_type") == "float16":
        raise RuntimeError("CUDA failed with error out of memory")
    return object()


ct2.Translator = fits_only_in_8_bits
ct2.get_supported_compute_types = lambda name: {"float16", "int8_float16", "float32"}
calls.clear()
small = engine_module.Engine()
small.load_model(NLLB, "cuda")
check(small.device == "cuda" and small.compute_type == "int8_float16" and [c["compute_type"] for c in calls] == ["float16", "int8_float16"],
      "a model that is too large as float16 is loaded as int8_float16")
ct2.Translator = fake_translator
gpu_full.append(True)
try:
    engine_module.Engine().load_model(NLLB, "cuda")
    raised = None
except engine_module.EngineError as error:
    raised = error
gpu_full.clear()
check(raised is not None and "out of memory" in raised.message, "a model that does not fit in either type is explained")

# The limits of a call: 8 sentences on the CPU, and 128 sentences or 4,096 tokens on a GPU
cpu_engine = engine_module.Engine()
cpu_engine.load_model(NLLB)
cpu_engine.load_sp_model(os.path.join(NLLB, "sentencepiece.model"))
text = "\n".join("This is sentence number %d of the test." % i for i in range(300))
sizes = lambda batches: [len(b) for b in batches]
check(set(sizes(cpu_engine.split(text, "en")[2])[:-1]) == {8}, "the CPU translates 8 sentences per call")
cpu_engine.device = "cuda"
check(sizes(cpu_engine.split(text, "en")[2]) == [128, 128, 44], "a GPU translates 128 sentences per call")
cpu_engine.call_tokens = 100
tokens_of = lambda batch: sum(len(t) + 2 for t in cpu_engine.sp_model.encode(batch, out_type=str))
batches = cpu_engine.split(text, "en")[2]
check(len(batches) > 3 and all(tokens_of(b) <= 100 or len(b) == 1 for b in batches) and [s for b in batches for s in b] == text.split("\n"),
      "a call ends at the limit of tokens, and no sentence is lost or reordered")
cpu_engine.call_tokens = 5
check(all(len(b) == 1 for b in cpu_engine.split(text, "en")[2]), "a sentence over the limit of tokens is a call of its own")
cpu_engine.device = "cpu"

# The speed levels on the CPU: 8, 16 or 32 sentences per call, and no more than 40 tokens per sentence of the limit
cpu_engine.batch_sentences = cpu_engine.call_tokens = cpu_engine.max_batch_tokens = None  # the earlier checks set limits by hand
check(cpu_engine.cpu_speed == "standard", "the speed on the CPU is Standard by default")
for level, number in (("faster", 16), ("fastest", 32)):
    cpu_engine.cpu_speed = level
    check(set(sizes(cpu_engine.split(text, "en")[2])[:-1]) == {number}, "%s: the CPU translates %d sentences per call" % (level, number))
cpu_engine.cpu_speed = "fastest"
long_text = "\n".join(("This is a long sentence number %d, " % i) + "with many words, " * 12 + "that ends here." for i in range(40))
long_tokens = len(cpu_engine.sp_model.encode(long_text.split("\n")[0], out_type=str)) + 2
per_call = [len(b) for b in cpu_engine.split(long_text, "en")[2]]
check(long_tokens > 40 and max(per_call) <= max(1, (40 * 32) // long_tokens) and sum(per_call) == 40,
      "long sentences make smaller calls: %d tokens each, at most %d per call" % (long_tokens, max(per_call)))
cpu_engine.cpu_speed = "standard"
speed_dialog = qt_app.PreferencesDialog(window, 3, False, True, False, cpu_speed="fastest")
check(speed_dialog.cpu_speed() == "fastest" and qt_app.PreferencesDialog(window, 3, False, True, False).cpu_speed() == "standard",
      "the Preferences show the speed on the CPU, Standard by default")
window.preferences.set("cpu_speed", "faster")
window.save_settings()
speed_window = qt_app.Window()
check(speed_window.engine.cpu_speed == "faster", "the speed on the CPU is restored at the next start")
speed_window.close()
window.preferences.set("cpu_speed", "standard")
window.save_settings()

# The Automatic speed: the calls grow when the computer is fast, and stay small when it is slow
import types

clock = types.SimpleNamespace(now=0.0)


class AutoResult:
    hypotheses = [["\u2581fra_Latn", "\u2581ok"]]


class TimedCpu:
    """A translator that takes a time in proportion to the tokens"""

    def __init__(self, tokens_per_second):
        self.rate = tokens_per_second

    def translate_batch(self, **kwargs):
        clock.now += sum(len(tokens) for tokens in kwargs["source"]) / self.rate
        return [AutoResult() for _ in kwargs["source"]]


def automatic_calls(rate, cancel_after=None):
    cpu_engine.cpu_speed = "automatic"
    cpu_engine.translator = TimedCpu(rate)
    batches = cpu_engine.split(text, "en")[2]
    seen = []
    real_time = engine_module.time
    engine_module.time = types.SimpleNamespace(perf_counter=lambda: clock.now)
    try:
        output = cpu_engine.translate(batches, 3, "fra_Latn", "eng_Latn", is_cancelled=lambda: cancel_after is not None and len(seen) >= cancel_after,
                                      on_batch=lambda done: seen.append(len(done) - sum(seen)))
    finally:
        engine_module.time = real_time
        cpu_engine.cpu_speed = "standard"
    return seen, output


seen, output = automatic_calls(20000)
check(sum(seen) == 300 and len(output) == 300 and max(seen) > seen[0] and max(seen) <= engine_module.AUTOMATIC_MAX_SENTENCES
      and all(seen[i] <= 2 * seen[i - 1] + 2 for i in range(1, len(seen))), "Automatic on a fast computer: the calls grow, at most twice each time: %s" % seen)
seen, output = automatic_calls(20)
check(sum(seen) == 300 and len(output) == 300 and max(seen[:-1]) - min(seen[:-1]) <= 3, "Automatic on a slow computer: the calls keep the first size, give or take the length of the numbers: %s" % seen[:6])
seen, output = automatic_calls(20000, cancel_after=1)
check(output is None and len(seen) == 1, "Automatic stops at once when it is cancelled")

# When the memory of the GPU runs out during a translation, the batches become smaller


class FakeResult:
    hypotheses = [["\u2581fra_Latn", "\u2581ok"]]


class TightGpu:
    def __init__(self):
        self.limits = []

    def translate_batch(self, **kwargs):
        self.limits.append(kwargs["max_batch_size"])
        if kwargs["max_batch_size"] > 1024:
            raise RuntimeError("CUDA failed with error out of memory")
        return [FakeResult() for _ in kwargs["source"]]


tight = TightGpu()
cpu_engine.translator, cpu_engine.device = tight, "cuda"
output = cpu_engine.translate_batch(["Hello."], 3, "fra_Latn", "eng_Latn")
check(tight.limits == [4096, 2048, 1024] and cpu_engine.limits()[2] == 1024 and len(output) == 1,
      "when the GPU runs out of memory, the batch limit is halved until the call works, and kept")


class FullGpu:
    def translate_batch(self, **kwargs):
        raise RuntimeError("CUDA failed with error out of memory")


cpu_engine.translator, cpu_engine.max_batch_tokens = FullGpu(), None
try:
    cpu_engine.translate_batch(["Hello."], 3, "fra_Latn", "eng_Latn")
    raised = None
except RuntimeError as error:
    raised = error
check(raised is not None and "out of memory" in str(raised), "a GPU that stays out of memory at the smallest batch fails with its message")


def no_cuda():
    raise RuntimeError("CUDA driver not found")


ct2.get_cuda_device_count = no_cuda
check(engine_module.gpu_count() == 0, "a missing CUDA driver means no GPU")
ct2.Translator, ct2.get_cuda_device_count, ct2.get_supported_compute_types = real

# Language detection says when it is unsure
scores = engine_module.Engine().detect_language_scores("Hello, how are you today?")
check(scores[0][0] == "en" and scores[0][1] > 0.9, "a sentence is detected with a high probability")
lid_window = qt_app.Window()
lid_window.load_model(NLLB)
lid_window.show()
lid_window.source_text.setPlainText("The weather is nice today, and we will go for a walk.")
lid_window.update_header()
check("detected: English," in lid_window.source_header.text() and not lid_window.detection_info.isVisible(), "a sure detection has no (i) sign")
lid_window.source_text.setPlainText("test")
lid_window.update_header()
check(lid_window.source_header.text() == "Source (detected: Hungarian, 1 word)" and lid_window.detection_info.isVisible()
      and "57% sure" in lid_window.detection_info.toolTip(), "an unsure detection of one word has an (i) sign with the confidence")
lid_window.close()

# The diagnostic info for a report of an issue
help_items = [a.text() for a in window.menuBar().actions()[-1].menu().actions()]
check("Copy Diagnostic Info..." in help_items, "the Help menu has Copy Diagnostic Info")
diag_window = qt_app.Window()
diag_window.load_model(NLLB)
diag_window.source_text.setPlainText("A very private sentence about SECRETWORD9917.")
home = os.path.expanduser("~")
messages.clear()
diag_window.show_error("Cannot open the file", "Cannot read " + home + "/Documents/private.txt")
check(diag_window.last_error == ("Cannot open the file", "Cannot read " + home + "/Documents/private.txt") and messages, "the last error is remembered and shown")
shown_dialogs = []
real_diag_exec = qt_app.DiagnosticsDialog.exec
qt_app.DiagnosticsDialog.exec = lambda dialog: shown_dialogs.append(dialog) or 0
diag_window.show_diagnostics()
qt_app.DiagnosticsDialog.exec = real_diag_exec
report = shown_dialogs[0].edit.toPlainText()
check("nllb-200-distilled-600M-int8" in report and "CTranslate2 " in report and "Running on: cpu" in report and "cpu_speed: standard" in report and "beam_size: " in report,
      "the diagnostic info has the versions, the model folder name, and the settings")
check(NLLB not in report and home not in report and "SECRETWORD9917" not in report and "private.txt" in report and "~/Documents/private.txt" in report,
      "the diagnostic info has no model path, home folder, or text")
shown_dialogs[0].copy()
check(qt_app.QApplication.clipboard().text() == report and shown_dialogs[0].edit.isReadOnly() is False, "the diagnostic info can be changed, and it is copied")
diag_window.close()

# Check for updates: asks a local server, only when the user chooses it
import gui.updates

check("Check for Updates..." in [a.text() for a in window.menuBar().actions()[-1].menu().actions()], "the Help menu has Check for Updates")
check(gui.updates.is_newer("v0.4.10", "0.4.9") and gui.updates.is_newer("v0.5.0", "0.4.9") and not gui.updates.is_newer("v0.4.2", "0.4.2")
      and not gui.updates.is_newer("v0.4.1", "0.4.2-dev"), "versions are compared by their numbers")
latest = {"tag_name": "v9.9.9", "html_url": "https://example.org/releases/v9.9.9"}


class LatestHandler(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        LatestHandler.seen.append(self.headers.get("User-Agent"))
        body = json.dumps(latest).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


latest_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LatestHandler)
threading.Thread(target=latest_server.serve_forever, daemon=True).start()
gui.updates.LATEST_URL = "http://127.0.0.1:%d/latest" % latest_server.server_port
update_window = qt_app.Window()


def check_updates_now():
    messages.clear()
    update_window.check_updates()
    deadline = time.time() + 20
    while update_window.update_worker is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


opened_pages = []
real_open_url = qt_app.QDesktopServices.openUrl
qt_app.QDesktopServices.openUrl = staticmethod(lambda url: opened_pages.append(url.toString()) or True)
real_question = QMessageBox.question
QMessageBox.question = staticmethod(lambda parent, title, text, *a: (messages.append((title, text)), QMessageBox.StandardButton.Yes)[1])
check(not LatestHandler.seen, "nothing asks for updates before the user chooses it")
check_updates_now()
check(messages and messages[-1][0] == "Update available" and "9.9.9" in messages[-1][1] and opened_pages == ["https://example.org/releases/v9.9.9"]
      and LatestHandler.seen == ["DesktopTranslator/" + qt_app.VERSION], "a newer version is offered, and the page opens when the user agrees")
latest["tag_name"] = "v" + qt_app.VERSION
current_boxes = []
real_box_exec = qt_app.QMessageBox.exec
qt_app.QMessageBox.exec = lambda box: current_boxes.append((box.windowTitle(), box.text(), box.informativeText())) or 0
check_updates_now()
qt_app.QMessageBox.exec = real_box_exec
check([box[1:] for box in current_boxes] == [("You have the latest version.", "Version " + qt_app.VERSION)], "the latest version is said to be the latest, with the version on its own line")
latest_server.shutdown()
latest_server.server_close()
check_updates_now()
check(update_window.last_error and update_window.last_error[0] == "Check for Updates" and "could not be found" in update_window.last_error[1],
      "an unreachable server is reported")
QMessageBox.question = real_question
qt_app.QDesktopServices.openUrl = real_open_url
update_window.close()

# The device in the Preferences
count_boxes = lambda dialog: len(dialog.findChildren(QComboBox))
check(count_boxes(qt_app.PreferencesDialog(window, 3, False, True, False)) == 2
      and qt_app.PreferencesDialog(window, 3, False, True, False, "cuda", False).device() == "cpu", "without a GPU, the Preferences offer no device")
with_gpu = qt_app.PreferencesDialog(window, 3, False, True, False, "cuda", True)
check(count_boxes(with_gpu) == 3 and with_gpu.device() == "cuda", "with a GPU, the Preferences show the device in use")
signs = with_gpu.findChildren(gui.widgets.InfoSign)
signs[0].enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
check(len(signs) == 7 and QToolTip.isVisible() and QToolTip.text() == signs[0].toolTip(), "an (i) sign shows its tooltip at once")
check(all(". " not in sign.toolTip() for sign in signs) and signs[0].toolTip().count("\n") == 1, "the tooltip of an (i) sign has a line for each sentence")
QToolTip.hideText()
with_gpu.device_box.setCurrentText("CPU")
check(with_gpu.device() == "cpu" and with_gpu.values()[0] == 3, "the device can be set to the CPU")

gpu_full.clear()
ct2.get_cuda_device_count = lambda: 1
ct2.get_supported_compute_types = lambda name: {"float16", "float32"}
device_window = qt_app.Window()
device_window.load_model(NLLB)
real_translator = device_window.engine.translator
ct2.Translator = fake_translator
device_window.change_device("cuda")
check(device_window.preferences.get("device", "cpu") == "cuda" and device_window.engine.device == "cuda"
      and device_window.model_label.text().endswith("(GPU)"), "choosing the GPU loads the model again on the GPU")
device_window.change_device("cpu")
check(device_window.engine.device == "cpu" and not device_window.model_label.text().endswith("(GPU)"), "choosing the CPU loads it on the CPU again")
gpu_full.append(True)
messages.clear()
device_window.change_device("cuda")
check(messages and "out of memory" in messages[-1][1] and device_window.preferences.get("device", "cpu") == "cpu"
      and device_window.engine.device == "cpu", "a model that does not fit on the GPU is explained, and the CPU stays")
ct2.Translator, ct2.get_cuda_device_count, ct2.get_supported_compute_types = real
device_window.close()

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
