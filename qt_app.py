"""DesktopTranslator, a translation app with a Qt interface; the translation itself is in engine.py.

Usage: python qt_app.py
       python qt_app.py --demo MODEL_DIR SP_MODEL TARGET_LANGUAGE TEXT_FILE OUTPUT.png
       (OUTPUT.png can be - to keep the window open; --dark shows the dark appearance)
"""
import os
import sys
import time

from PySide6.QtCore import QByteArray, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from engine import (
    AUTO_DETECT,
    DATA_DIR,
    LONG_LINE_CHARS,
    MODEL_DOWNLOAD,
    REPETITION_PENALTY,
    WORD_LIMIT,
    Engine,
    EngineError,
    Preferences,
    download_model,
    downloaded_model,
    find_sentencepiece,
    format_duration,
    longest_line,
    memory_warning,
    read_text_file,
    write_text_file,
)
from utils.paragraph_splitter import TextBuilder, paragraph_detokenizer

APP_NAME = "DesktopTranslator"
VERSION = "0.4.0"
TARGET_PLACEHOLDER = "Select a language..."
DEFAULT_TEXT_SIZE = 14
QUALITY = {"Fast": 2, "Balanced": 3, "Accurate": 5}  # beam sizes
REPOSITORY_URL = "https://github.com/ymoslem/DesktopTranslator"  # shown in About; a website can be added later
NOTICE_URL = REPOSITORY_URL + "/blob/main/NOTICE.md"
RELEASES_URL = REPOSITORY_URL + "/releases"
DOWNLOADS = [
    ("NLLB-200 distilled 600M", "200 languages; the smallest and fastest",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.3.0/NLLB-200_distilled_600M_int8_ct2.zip"),
    ("NLLB-200 distilled 1.3B", "200 languages; slower, needs more memory, sometimes more accurate",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.3.0/NLLB-200_distilled_1.3B_int8_ct2.zip"),
    ("M2M-100 418M", "100 languages; small",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_418m_parameter_model_ct2.zip"),
    ("M2M-100 1.2B", "100 languages; larger",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_12b_parameter_model_ct2.zip"),
    ("French to English", "A small model to try the app",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.3/fren.zip"),
]


def short_text(text, limit):
    """Shorten a long text, such as a path, by leaving out the middle"""
    if len(text) <= limit:
        return text
    head = (limit - 3) // 3
    return text[:head] + "..." + text[-(limit - 3 - head):]


class Worker(QThread):
    """Translates in the background, and reports with signals"""

    progress = Signal(int)
    batch_done = Signal(list)
    done = Signal(list)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, engine, batches, beam_size, target_lang_code, src_prefix, repetition_penalty):
        super().__init__()
        self.engine, self.batches = engine, batches
        self.beam_size, self.target_lang_code, self.src_prefix = beam_size, target_lang_code, src_prefix
        self.repetition_penalty = repetition_penalty
        self.cancel = False

    def run(self):
        try:
            translations = self.engine.translate(
                self.batches, self.beam_size, self.target_lang_code, self.src_prefix,
                is_cancelled=lambda: self.cancel, on_progress=self.progress.emit,
                repetition_penalty=self.repetition_penalty, on_batch=lambda sentences: self.batch_done.emit(list(sentences)),
            )
            self.cancelled.emit() if translations is None else self.done.emit(translations)
        except Exception as error:
            self.failed.emit(str(error))


class DocumentWorker(QThread):
    """Translates a file into another file in the background"""

    progress = Signal(int, int)
    finished_ok = Signal(int, int)
    failed = Signal(str)

    def __init__(self, engine, input_path, output_path, target, source_name, beam_size, join, penalty):
        super().__init__()
        self.engine, self.input_path, self.output_path = engine, input_path, output_path
        self.options = (target, source_name, beam_size, join, penalty)
        self.cancel = False

    def run(self):
        target, source_name, beam_size, join, penalty = self.options
        try:
            done, total = self.engine.translate_file(
                self.input_path, self.output_path, target, source_name, beam_size, join, penalty,
                is_cancelled=lambda: self.cancel, on_progress=self.progress.emit,
            )
            self.finished_ok.emit(done, total)
        except Exception as error:
            self.failed.emit(str(error))


class ModelDownloadWorker(QThread):
    """Downloads the model that the app offers, in the background"""

    progress = Signal(float, float)
    finished_ok = Signal(object)  # the model folder, or None if cancelled
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.cancel = False

    def run(self):
        try:
            folder = download_model(is_cancelled=lambda: self.cancel, on_progress=self.progress.emit)
            self.finished_ok.emit(folder)
        except EngineError as error:
            self.failed.emit(error.title, error.message)
        except Exception as error:
            self.failed.emit("Download failed", str(error))


class DownloadDialog(QDialog):
    """Shows the progress of the download of a model, which can be cancelled"""

    def __init__(self, parent, worker):
        super().__init__(parent)
        self.setWindowTitle("Download a Model")
        self.worker = worker
        self.folder = None  # the model folder when it is downloaded
        self.error = None  # title and message of a failure
        self.label = QLabel("Downloading " + MODEL_DOWNLOAD["name"] + "...")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # until the download starts
        self.detail = QLabel("")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        layout = QVBoxLayout(self)
        for widget in (self.label, self.bar, self.detail, self.cancel_button):
            layout.addWidget(widget)
        self.setMinimumWidth(420)
        worker.progress.connect(self.on_progress)
        worker.finished_ok.connect(self.on_finished)
        worker.failed.connect(self.on_failed)

    def exec(self):
        self.start_time = time.time()
        self.worker.start()
        return super().exec()

    def cancel(self):
        self.worker.cancel = True
        self.cancel_button.setEnabled(False)
        self.detail.setText("Cancelling...")

    def on_progress(self, done, total):
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(1000 * done / total))
        detail = "%d of %d MB" % (done / 1048576, total / 1048576)
        elapsed = time.time() - self.start_time
        if elapsed > 3 and done:
            detail += " (about " + format_duration(elapsed * (total - done) / done) + " left)"
        self.detail.setText(detail)

    def on_finished(self, folder):
        self.folder = folder
        self.worker.wait()
        self.accept()

    def on_failed(self, title, message):
        self.error = (title, message)
        self.worker.wait()
        self.accept()

    def reject(self):  # closing the window cancels the download
        if self.worker.isRunning():
            self.cancel()
        else:
            super().reject()


class WelcomeDialog(QDialog):
    """Offers a model at the first start, because the app cannot translate without one"""

    def __init__(self, parent, downloaded):
        super().__init__(parent)
        self.setWindowTitle("Welcome to " + APP_NAME)
        self.choice = ""  # download, open, or later
        size = "%d MB" % (MODEL_DOWNLOAD["size"] / 1048576)
        text = QLabel(
            "<h3>Welcome to " + APP_NAME + "</h3>"
            "<p>" + APP_NAME + " needs a translation model to work. The " + MODEL_DOWNLOAD["name"] + " model translates between 200 languages."
            + ("" if downloaded else " It is a download of " + size + ".") + "</p>"
            "<p>It is released under the <a href='https://creativecommons.org/licenses/by-nc/4.0/'>CC-BY-NC 4.0</a> license, "
            "which does not allow commercial use. You can find other models in Help &gt; Get Models.</p>"
        )
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        self.skip = QCheckBox("Do not show this again")
        buttons = QDialogButtonBox()
        use = buttons.addButton("Use " + MODEL_DOWNLOAD["name"] if downloaded else "Download " + MODEL_DOWNLOAD["name"], QDialogButtonBox.ButtonRole.AcceptRole)
        other = buttons.addButton("Open a model I have...", QDialogButtonBox.ButtonRole.ActionRole)
        later = buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        use.setDefault(True)
        use.clicked.connect(lambda: self.finish("download"))
        other.clicked.connect(lambda: self.finish("open"))
        later.clicked.connect(lambda: self.finish("later"))
        layout = QVBoxLayout(self)
        for widget in (text, self.skip, buttons):
            layout.addWidget(widget)
        self.setMinimumWidth(460)

    def finish(self, choice):
        self.choice = choice
        self.accept()

    def reject(self):
        self.choice = "later"
        super().reject()


class DocumentDialog(QDialog):
    """Shows the progress of the translation of a file, which can be cancelled"""

    def __init__(self, parent, worker, input_path):
        super().__init__(parent)
        self.setWindowTitle("Translate Document")
        self.worker = worker
        self.outcome = ""  # done, cancelled, or the error
        self.label = QLabel("Translating " + os.path.basename(input_path) + "...")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # until the first part is translated
        self.detail = QLabel("")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        layout = QVBoxLayout(self)
        for widget in (self.label, self.bar, self.detail, self.cancel_button):
            layout.addWidget(widget)
        self.setMinimumWidth(420)
        worker.progress.connect(self.on_progress)
        worker.finished_ok.connect(self.on_finished)
        worker.failed.connect(self.on_failed)

    def start(self):
        self.start_time = time.time()
        self.worker.start()

    def exec(self):
        self.start()
        return super().exec()

    def cancel(self):
        self.worker.cancel = True
        self.cancel_button.setEnabled(False)
        self.detail.setText("Cancelling...")

    def on_progress(self, done, total):
        self.bar.setRange(0, total)
        self.bar.setValue(min(done, total))
        detail = str(int(100 * done / total)) + "%"
        elapsed = time.time() - self.start_time
        if elapsed > 3 and done:
            detail += " (about " + format_duration(elapsed * (total - done) / done) + " left)"
        self.detail.setText(detail)

    def on_finished(self, done, total):
        self.outcome = "done" if done >= total or not self.worker.cancel else "cancelled"
        self.worker.wait()
        self.accept()

    def on_failed(self, message):
        self.outcome = message
        self.worker.wait()
        self.accept()

    def reject(self):  # closing the window cancels, and the translated part is kept
        if self.worker.isRunning():
            self.cancel()
        else:
            super().reject()


class SourceEdit(QTextEdit):
    """The source text; a text file can be dropped on it"""

    file_dropped = Signal(str)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls() and source.urls()[0].isLocalFile():
            self.file_dropped.emit(source.urls()[0].toLocalFile())
        else:
            super().insertFromMimeData(source)


class LanguageBox(QComboBox):
    """A language list that can be searched by typing"""

    def __init__(self):
        super().__init__()
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(16)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

    def set_languages(self, items, searchable):
        self.blockSignals(True)
        self.clear()
        self.addItems(items)
        self.setEditable(searchable)
        if searchable:
            completer = QCompleter(items, self)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.setCompleter(completer)
        # The list is as wide as its longest name, even if the box is narrower
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 40)
        self.blockSignals(False)

    def choose(self, text):
        """Select an entry by its name; returns False if there is no such entry"""
        index = self.findText(text, Qt.MatchFlag.MatchFixedString)
        if index < 0:
            return False
        self.setCurrentIndex(index)
        return True


class PreferencesDialog(QDialog):
    def __init__(self, parent, beam_size, join_lines, remember, repetition):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.quality = QComboBox()
        self.quality.addItems(QUALITY)
        self.quality.setCurrentText(next((n for n, b in QUALITY.items() if b == beam_size), "Balanced"))
        self.quality.setToolTip("Fast takes less time; Accurate searches more candidate translations (a larger beam size)")
        self.repetition = QCheckBox("Avoid repeated words (a repetition penalty of 1.2; it scored lower in our tests)")
        self.repetition.setChecked(repetition)
        self.join_lines = QCheckBox("Join lines inside a paragraph (for text from PDF or OCR)")
        self.join_lines.setChecked(join_lines)
        self.remember = QCheckBox("Remember the last model and target language")
        self.remember.setChecked(remember)
        form = QFormLayout()
        form.addRow("Translation quality:", self.quality)
        form.addRow(self.repetition)
        form.addRow(self.join_lines)
        form.addRow(self.remember)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self):
        return QUALITY[self.quality.currentText()], self.join_lines.isChecked(), self.remember.isChecked(), self.repetition.isChecked()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.engine = Engine()
        self.preferences = Preferences()
        self.worker = None
        self.translation = ""
        self.file_name = ""
        self.pending_model = ""  # the models of the last session are loaded when translating
        self.pending_sp = ""
        self.sp_path = ""
        self.detected_name = ""

        self.build_widgets()
        self.build_menus()
        self.restore_session()
        self.source_text.setFocus()

    # Interface

    def build_widgets(self):
        self.model_button = QPushButton("Open Model...")
        self.model_button.setToolTip("Open a CTranslate2 model folder (Ctrl+M)")
        self.translate_button = QPushButton("Translate")
        self.translate_button.setDefault(True)
        self.translate_button.setToolTip("Translate the source text (Ctrl+Return)")
        self.translate_button.setMinimumWidth(self.translate_button.sizeHint().width() + 8)  # also fits "Cancel"
        self.source_combo, self.target_combo = LanguageBox(), LanguageBox()
        self.swap_button = QPushButton("⇄")
        self.swap_button.setFixedWidth(40)
        self.swap_button.setToolTip("Swap the source and target languages (Ctrl+Shift+S)")
        self.source_header = QLabel("Source")
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the translation (Ctrl+Shift+C)")
        self.source_text = SourceEdit()
        self.target_text = QTextEdit()
        self.source_text.setPlaceholderText("Type or paste text, or drop a text file here")
        self.target_text.setPlaceholderText("Open a model to start (Ctrl+M)")
        for pane in (self.source_text, self.target_text):
            pane.setAcceptRichText(False)
            # Each paragraph takes its direction from its first strong character
            option = pane.document().defaultTextOption()
            option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
            pane.document().setDefaultTextOption(option)
        self.set_text_size(self.preferences.get("text_size", DEFAULT_TEXT_SIZE))
        self.set_languages(None)

        top = QHBoxLayout()
        top.addWidget(self.model_button)
        top.addWidget(self.translate_button)
        top.addSpacing(16)
        top.addWidget(QLabel("From:"))
        top.addWidget(self.source_combo)
        top.addWidget(self.swap_button)
        top.addWidget(QLabel("To:"))
        top.addWidget(self.target_combo)
        top.addStretch()

        header_height = self.copy_button.sizeHint().height()

        def pane_with_header(header, pane, button=None):
            header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(header, 1)
            if button:
                row.addWidget(button)
            bar = QWidget()
            bar.setLayout(row)
            bar.setFixedHeight(header_height)  # both headers have the same height, so the panes line up
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(4)
            column.addWidget(bar)
            column.addWidget(pane)
            holder = QWidget()
            holder.setLayout(column)
            return holder

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(pane_with_header(self.source_header, self.source_text))
        self.target_header = QLabel("Translation")
        self.splitter.addWidget(pane_with_header(self.target_header, self.target_text, self.copy_button))
        self.splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(10, 8, 10, 4)
        layout.addLayout(top)
        layout.addWidget(self.splitter)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.model_label = QLabel()
        self.count_timer = QTimer(self)  # counts a moment after the last change, so typing stays quick
        self.count_timer.setSingleShot(True)
        self.count_timer.setInterval(300)
        self.count_timer.timeout.connect(self.update_header)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.hide()
        # Labels with margins keep the text away from the window edges
        self.status_label = QLabel()
        self.status_label.setContentsMargins(12, 2, 12, 2)
        self.model_label.setContentsMargins(12, 2, 12, 2)
        status = QWidget()  # the progress bar sits right after the status text
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.progress_bar)
        status_row.addStretch()
        self.statusBar().addWidget(status, 1)
        self.statusBar().addPermanentWidget(self.model_label)
        self.say("Open a model to start, or choose Help > Get Models.")

        self.model_button.clicked.connect(self.open_model)
        self.translate_button.clicked.connect(self.translate_or_cancel)
        self.swap_button.clicked.connect(self.swap_languages)
        self.copy_button.clicked.connect(self.copy_translation)
        self.source_text.file_dropped.connect(self.open_text_file)
        self.source_text.textChanged.connect(self.count_timer.start)
        self.source_combo.activated.connect(lambda _: self.update_header())
        self.target_combo.activated.connect(lambda _: self.remember_target())

    def say(self, message):
        self.status_label.setText(message)

    def action(self, menu, text, slot, shortcut=None, enabled=True):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        action.setEnabled(enabled)
        menu.addAction(action)
        return action

    def build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self.action(file_menu, "Open Text...", self.open_text, QKeySequence.StandardKey.Open)
        self.action(file_menu, "Reopen Text with Encoding...", self.reopen_with_encoding)
        self.action(file_menu, "Translate Document...", lambda: self.translate_document(), "Ctrl+Shift+O")
        self.action(file_menu, "Save Translation...", self.save_translation, QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        self.action(file_menu, "Quit", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = bar.addMenu("&Edit")
        self.action(edit_menu, "Undo", lambda: self.focused_pane().undo(), QKeySequence.StandardKey.Undo)
        self.action(edit_menu, "Redo", lambda: self.focused_pane().redo(), QKeySequence.StandardKey.Redo)
        edit_menu.addSeparator()
        self.action(edit_menu, "Cut", lambda: self.focused_pane().cut(), QKeySequence.StandardKey.Cut)
        self.action(edit_menu, "Copy", lambda: self.focused_pane().copy(), QKeySequence.StandardKey.Copy)
        self.action(edit_menu, "Paste", lambda: self.focused_pane().paste(), QKeySequence.StandardKey.Paste)
        self.action(edit_menu, "Select All", lambda: self.focused_pane().selectAll(), QKeySequence.StandardKey.SelectAll)
        edit_menu.addSeparator()
        self.action(edit_menu, "Clear", self.clear)
        edit_menu.addSeparator()
        self.action(edit_menu, "Preferences...", self.show_preferences, QKeySequence.StandardKey.Preferences)

        translate_menu = bar.addMenu("&Translate")
        self.action(translate_menu, "Translate", self.translate_or_cancel, "Ctrl+Return")
        self.cancel_action = self.action(translate_menu, "Cancel", self.cancel, "Esc", enabled=False)
        translate_menu.addSeparator()
        self.action(translate_menu, "Open Model...", self.open_model, "Ctrl+M")
        self.action(translate_menu, "Choose SentencePiece Model...", self.choose_sp_model)
        translate_menu.addSeparator()
        self.action(translate_menu, "Swap Languages", self.swap_languages, "Ctrl+Shift+S")
        self.action(translate_menu, "Copy Translation", self.copy_translation, "Ctrl+Shift+C")

        view_menu = bar.addMenu("&View")
        larger = self.action(view_menu, "Larger Text", lambda: self.zoom(1), QKeySequence.StandardKey.ZoomIn)
        larger.setShortcuts([QKeySequence.StandardKey.ZoomIn, QKeySequence("Ctrl+=")])  # = is + without Shift
        self.action(view_menu, "Smaller Text", lambda: self.zoom(-1), QKeySequence.StandardKey.ZoomOut)
        self.action(view_menu, "Actual Size", lambda: self.zoom(0), "Ctrl+0")

        help_menu = bar.addMenu("&Help")
        self.action(help_menu, "Download " + MODEL_DOWNLOAD["name"] + "...", self.download_first_model)
        self.action(help_menu, "Get Models...", self.show_models)
        about = self.action(help_menu, "About " + APP_NAME, self.show_about)
        about.setMenuRole(QAction.MenuRole.NoRole)  # stays in the Help menu, also on macOS

    def focused_pane(self):
        return self.target_text if self.target_text.hasFocus() else self.source_text

    def set_text_size(self, size):
        self.text_size = max(8, min(48, size))
        for pane in (self.source_text, self.target_text):
            font = pane.font()
            font.setPointSize(self.text_size)
            pane.setFont(font)

    def zoom(self, step):
        """Make the text larger or smaller; 0 sets the usual size"""
        self.set_text_size(self.text_size + step if step else DEFAULT_TEXT_SIZE)
        self.preferences.set("text_size", self.text_size)
        self.say("Text size: %d" % self.text_size)

    # Languages

    def set_languages(self, model_type):
        """Fill the language lists for the kind of model"""
        if model_type in self.engine.language_lists:
            names = sorted(self.engine.language_codes)
            self.source_combo.set_languages([AUTO_DETECT] + names, True)
            self.target_combo.set_languages(names, True)
            self.target_combo.setCurrentIndex(-1)
            self.target_combo.lineEdit().setPlaceholderText(TARGET_PLACEHOLDER)
            for widget in (self.source_combo, self.target_combo, self.swap_button):
                widget.setEnabled(True)
        else:
            self.source_combo.set_languages([AUTO_DETECT], False)
            self.target_combo.set_languages(["Not needed" if model_type else "Open a model first"], False)
            for widget in (self.source_combo, self.target_combo, self.swap_button):
                widget.setEnabled(False)

    def selected_source(self):
        text = self.source_combo.currentText()
        return text if text in self.engine.language_codes else AUTO_DETECT

    def selected_target(self):
        text = self.target_combo.currentText()
        return text if text in self.engine.language_codes else ""

    def remember_target(self):
        if self.selected_target():
            self.preferences.target_memory[self.engine.model_type] = self.selected_target()
            self.save_settings()

    def swap_languages(self):
        source = self.selected_source()
        if source == AUTO_DETECT:
            source = self.detected_name
        target = self.selected_target()
        if not source or not target:
            self.say("Choose the two languages, or translate once, to swap them.")
            return
        self.source_combo.choose(target)
        self.target_combo.choose(source)
        self.update_header()
        self.remember_target()

    def update_header(self):
        """Source header: the language, when it is detected, and the number of words"""
        text = self.source_text.toPlainText()
        words = len(text.split())
        notes = []
        if self.selected_source() == AUTO_DETECT and text.strip():
            code, prefix = self.engine.source_language(text[:2000])
            if code:
                reverse = {v: k for k, v in self.engine.language_codes.items()}
                self.detected_name = reverse.get(prefix, "")  # a name the language lists know, for swapping
                notes.append("detected: " + (self.detected_name or code))
        if words:
            notes.append(format(words, ",") + (" word" if words == 1 else " words"))
        self.source_header.setText("Source (" + ", ".join(notes) + ")" if notes else "Source")

    # Models

    def open_model(self):
        start = os.path.dirname(self.engine.model_dir or self.pending_model or "")
        model_dir = QFileDialog.getExistingDirectory(self, "Open a CTranslate2 model folder", start)
        if model_dir:
            self.open_model_folder(model_dir)

    def open_model_folder(self, model_dir):
        if not self.load_model(model_dir):
            return
        candidates = find_sentencepiece(model_dir)
        if len(candidates) == 1:
            self.use_sp_model(candidates[0])
        else:
            self.choose_sp_model(os.path.dirname(candidates[0]) if candidates else model_dir, many=bool(candidates))

    def choose_sp_model(self, start=None, many=False):
        if not isinstance(start, str):
            start = os.path.dirname(self.sp_path or self.pending_sp or self.engine.model_dir or "")
        title = "Choose the SentencePiece model of the source language" if many else "Choose the SentencePiece model"
        path, _ = QFileDialog.getOpenFileName(self, title, start, "SentencePiece model (*.model *.spm);;All files (*)")
        if path:
            self.use_sp_model(path)

    def use_sp_model(self, path):
        self.engine.load_sp_model(path)
        self.sp_path = path
        self.pending_sp = ""
        self.say("Model loaded: " + short_text(self.engine.model_dir, 70))
        self.save_settings()

    def load_model(self, model_dir):
        warning = memory_warning(model_dir)
        if warning:
            answer = QMessageBox.question(self, "Large model", warning + "\n\nOpen the model anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            changed = self.engine.load_model(model_dir)
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.pending_model = ""
        if changed:
            self.set_languages(self.engine.model_type)
            self.restore_target()
        self.show_model_name(model_dir)
        self.source_text.setFocus()
        self.save_settings()
        return True

    def show_model_name(self, model_dir):
        self.target_text.setPlaceholderText("Translation")
        self.model_label.setText("Model: " + short_text(os.path.basename(os.path.normpath(model_dir)), 40))
        self.model_label.setToolTip(model_dir)

    def restore_target(self):
        remember = self.preferences.get("remember_model_paths", True)
        remembered = self.preferences.remembered_target(self.engine.model_type, remember)
        if remembered and self.engine.model_type in self.engine.language_lists:
            self.target_combo.choose(remembered)

    def restore_session(self):
        geometry = self.preferences.get("geometry", "")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        else:
            self.resize(1200, 640)
        state = self.preferences.get("splitter", "")
        if state:
            self.splitter.restoreState(QByteArray.fromBase64(state.encode()))
        if not self.preferences.get("remember_model_paths", True):
            return
        model_dir, sp_path = self.preferences.get("ct2_model", ""), self.preferences.get("sp_model", "")
        if self.engine.is_model(model_dir):
            self.engine.inspect_model(model_dir)
            self.set_languages(self.engine.model_type)
            self.restore_target()
            self.pending_model = model_dir
            self.show_model_name(model_dir)
            self.say("Last used model: " + short_text(os.path.basename(model_dir), 50) + " (loaded when you click Translate)")
        if os.path.isfile(sp_path):
            self.pending_sp = sp_path

    def offer_first_model(self):
        """At the first start, offer the model that is easiest to begin with"""
        if self.engine.translator is not None or self.pending_model or self.preferences.get("skip_welcome", False):
            return
        dialog = WelcomeDialog(self, downloaded_model() is not None)
        dialog.exec()
        if dialog.skip.isChecked():
            self.preferences.set("skip_welcome", True)
            self.preferences.write()
        if dialog.choice == "download":
            self.download_first_model()
        elif dialog.choice == "open":
            self.open_model()

    def download_first_model(self):
        """Download the model of the welcome dialog, unless it is there, and open it"""
        folder = downloaded_model()
        if folder is None:
            dialog = DownloadDialog(self, ModelDownloadWorker())
            dialog.exec()
            if dialog.error:
                QMessageBox.critical(self, dialog.error[0], dialog.error[1])
                self.say("The model could not be downloaded.")
                return
            if dialog.folder is None:
                self.say("Download cancelled.")
                return
            folder = dialog.folder
        self.open_model_folder(folder)

    def ensure_loaded(self):
        """Load the models of the last session, when they are needed"""
        if self.pending_model and not self.load_model(self.pending_model):
            self.pending_model = ""
            return False
        if self.pending_sp:
            self.use_sp_model(self.pending_sp)
        return self.engine.translator is not None and self.engine.sp_model is not None

    def save_settings(self):
        self.preferences.save(
            remember=self.preferences.get("remember_model_paths", True),
            join_lines_option=self.preferences.get("join_lines", False),
            rtl_view=True,
            ct2_model=self.engine.model_dir or self.pending_model,
            sp_model=self.sp_path or self.pending_sp,
            model_type=self.engine.model_type if self.engine.model_type in self.engine.language_lists else None,
            target=self.selected_target() or None,
        )

    # Text files

    def confirm_long_lines(self, text):
        longest = longest_line(text)
        if longest <= LONG_LINE_CHARS:
            return True
        answer = QMessageBox.question(
            self, "Very long line",
            "The text has a line of " + format(longest, ",") + " characters. Showing it can be slow. Show it anyway?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def open_text(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a text file", os.path.dirname(self.file_name), "Text files (*.txt);;All files (*)")
        if path:
            self.open_text_file(path)

    def open_text_file(self, path, encoding=None):
        try:
            text, encoding = read_text_file(path, encoding)
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return
        except (LookupError, UnicodeError, OSError) as error:
            QMessageBox.critical(self, "Cannot open the file", str(error))
            return
        words = len(text.split())
        if words > WORD_LIMIT:
            self.offer_document(words, path)
            return
        if not self.confirm_long_lines(text):
            return
        self.file_name = path
        self.source_text.setPlainText(text)
        self.say("%d lines, %d words, encoding %s" % (text.count("\n") + 1, len(text.split()), encoding))

    def reopen_with_encoding(self):
        if not self.file_name:
            QMessageBox.information(self, "Reopen Text with Encoding", "Please open a text file first.")
            return
        encoding, accepted = QInputDialog.getText(self, "Reopen Text with Encoding", "Encoding, e.g. utf-8, utf-16, latin-1, cp1252:")
        if accepted and encoding.strip():
            self.open_text_file(self.file_name, encoding.strip())

    def save_translation(self):
        if not self.translation.strip():
            QMessageBox.information(self, "Save Translation", "There is nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save the translation", os.path.dirname(self.file_name), "Text files (*.txt)")
        if path:
            write_text_file(path, self.target_text.toPlainText())

    def copy_translation(self):
        if self.worker is not None:
            self.say("Copy is available when the translation is done.")
            return
        text = self.target_text.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)
            self.say("Translation copied to the clipboard.")
        else:
            self.say("Nothing to copy.")

    def clear(self):
        self.source_text.clear()
        self.target_text.clear()
        self.translation = ""
        self.update_header()

    # Translation

    def translate_or_cancel(self):
        if self.worker is not None:
            self.cancel()
            return
        text = self.source_text.toPlainText()
        if not text.strip():
            self.say("Enter some text to translate.")
            return
        words = len(text.split())
        if words > WORD_LIMIT:
            self.offer_document(words)
            return
        if not self.ensure_loaded():
            QMessageBox.critical(self, "No model", "Please open a model first (Translate > Open Model).")
            return
        try:
            target = self.engine.target_language(self.selected_target())
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return
        source = self.selected_source()
        source_code, prefix = self.engine.source_language(text, source)
        if source_code is None:
            QMessageBox.critical(
                self, "Source language",
                "The source language is not supported or not recognized. Add more text, or select the source language.",
            )
            return
        reverse = {v: k for k, v in self.engine.language_codes.items()}
        self.detected_name = reverse.get(prefix, "")
        self.update_header()
        self.sentences, self.breaks, batches, self.total_words = self.engine.split(
            text, source_code, self.preferences.get("join_lines", False)
        )
        self.start = time.time()
        self.builder, self.partial_text = TextBuilder(self.breaks), ""
        self.target_text.clear()
        self.target_text.setReadOnly(True)  # while the translation is added to it
        penalty = REPETITION_PENALTY if self.preferences.get("repetition_penalty", 1.0) > 1.0 else 1.0
        self.worker = Worker(self.engine, batches, self.preferences.get("beam_size", 3), target, prefix, penalty)
        self.worker.progress.connect(self.on_progress)
        self.worker.batch_done.connect(self.on_batch)
        self.worker.done.connect(self.on_done)
        self.worker.cancelled.connect(lambda: self.finish("Translation cancelled. The translated part is kept."))
        self.worker.failed.connect(lambda message: self.finish("Translation failed: " + message))
        self.progress_bar.setRange(0, self.total_words)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.translate_button.setText("Cancel")
        self.copy_button.setEnabled(False)
        self.copy_button.setToolTip("Available when the translation is done")
        self.cancel_action.setEnabled(True)
        self.worker.start()

    def cancel(self):
        if self.worker is not None:
            self.worker.cancel = True
            self.say("Cancelling...")

    def on_progress(self, words_done):
        self.progress_bar.setValue(words_done)
        status = "Translating... " + str(int(100 * words_done / self.total_words)) + "%"
        elapsed = time.time() - self.start
        if elapsed > 3 and words_done:
            status += " (about " + format_duration(elapsed * (self.total_words - words_done) / words_done) + " left)"
        self.say(status)

    def on_batch(self, translations):
        """Add the sentences that were just translated to the translation"""
        added = self.builder.add(translations)
        if not added:
            return
        bar = self.target_text.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4  # follow the text, unless the user scrolled up
        cursor = self.target_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(added)
        self.partial_text += added
        if at_end:
            bar.setValue(bar.maximum())

    def on_done(self, translations):
        self.translation = paragraph_detokenizer(translations, self.breaks)
        if self.partial_text.rstrip() != self.translation:
            self.target_text.setPlainText(self.translation)
        self.finish("Translation completed in %.1f s." % (time.time() - self.start))

    def finish(self, message):
        self.worker.wait()
        if self.worker.cancel or message.startswith("Translation failed"):
            self.translation = self.partial_text.rstrip()  # what was translated is kept
        self.target_text.setReadOnly(False)
        self.worker = None
        self.progress_bar.hide()
        self.translate_button.setText("Translate")
        self.copy_button.setEnabled(True)
        self.copy_button.setToolTip("Copy the translation (Ctrl+Shift+C)")
        self.cancel_action.setEnabled(False)
        self.say(message)

    # Documents

    def offer_document(self, words, path=None):
        """The text is too long for the window, so offer to translate it as a document"""
        box = QMessageBox(self)
        box.setWindowTitle("Long text")
        box.setText(
            "The text has " + format(words, ",") + " words, and the window translates up to " + format(WORD_LIMIT, ",")
            + " words at a time.\n\nDocument mode translates a text file into another file, of any length, "
            "and shows the progress."
        )
        translate = box.addButton("Translate Document...", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is translate:
            self.translate_document(path)
            return True
        return False

    def translate_document(self, path=None):
        """Translate a text file into another file, with the languages and models of the window"""
        if self.worker is not None:
            return
        if not self.ensure_loaded():
            QMessageBox.critical(self, "No model", "Please open a model first (Translate > Open Model).")
            return
        try:
            target = self.engine.target_language(self.selected_target())
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open the text file to translate", os.path.dirname(self.file_name), "Text files (*.txt);;All files (*)")
            if not path:
                return
        language = "".join(c for c in self.selected_target() if c.isalnum()) or "translated"
        output, _ = QFileDialog.getSaveFileName(self, "Save the translated document", os.path.splitext(path)[0] + "." + language + ".txt", "Text files (*.txt)")
        if not output:
            return
        if os.path.abspath(output) == os.path.abspath(path):
            QMessageBox.critical(self, "Translate Document", "Please choose a different file for the translation.")
            return
        penalty = REPETITION_PENALTY if self.preferences.get("repetition_penalty", 1.0) > 1.0 else 1.0
        worker = DocumentWorker(
            self.engine, path, output, target, self.selected_source(), self.preferences.get("beam_size", 3),
            self.preferences.get("join_lines", False), penalty,
        )
        dialog = DocumentDialog(self, worker, path)
        dialog.exec()
        if dialog.outcome == "done":
            self.say("Document translated: " + output)
        elif dialog.outcome == "cancelled":
            self.say("Cancelled. The translated part is saved in " + output)
        else:
            QMessageBox.critical(self, "Translate Document", dialog.outcome)
            self.say("Translating the document failed.")

    # Windows

    def show_preferences(self):
        dialog = PreferencesDialog(
            self, self.preferences.get("beam_size", 3), self.preferences.get("join_lines", False),
            self.preferences.get("remember_model_paths", True), self.preferences.get("repetition_penalty", 1.0) > 1.0,
        )
        if dialog.exec():
            beam_size, join_lines, remember, repetition = dialog.values()
            self.preferences.set("repetition_penalty", REPETITION_PENALTY if repetition else 1.0)
            self.preferences.set("beam_size", beam_size)
            self.preferences.set("join_lines", join_lines)
            self.preferences.set("remember_model_paths", remember)
            self.save_settings()

    def show_models(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Get Models")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Download a model, extract the archive, and open its folder with Translate > Open Model."))
        for name, description, url in DOWNLOADS:
            row = QHBoxLayout()
            button = QPushButton("Download")
            button.clicked.connect(lambda _=False, url=url: QDesktopServices.openUrl(QUrl(url)))
            row.addWidget(QLabel("<b>" + name + "</b><br>" + description), 1)
            row.addWidget(button)
            layout.addLayout(row)
        more = QPushButton("More releases...")
        more.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        layout.addWidget(more)
        dialog.exec()

    def show_about(self):
        QMessageBox.about(
            self, "About " + APP_NAME,
            "<h3>" + APP_NAME + "</h3>Version " + VERSION + "<br>Developed by Yasmin Moslem<br>"
            "<a href='" + REPOSITORY_URL + "'>github.com/ymoslem/DesktopTranslator</a>"
            "<p>Translation with CTranslate2 and SentencePiece. Released under the MIT license.</p>"
            "<p>Built with Qt for Python (LGPL v3). "
            "The licenses of all the components are in <a href='" + NOTICE_URL + "'>NOTICE</a>.</p>",
        )

    def closeEvent(self, event):
        self.preferences.set("geometry", bytes(self.saveGeometry().toBase64()).decode())
        self.preferences.set("splitter", bytes(self.splitter.saveState().toBase64()).decode())
        self.preferences.write()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = os.path.join(DATA_DIR, "img", "icon.png")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    if "--dark" in sys.argv:  # to test the dark appearance; by default the system setting is used
        sys.argv.remove("--dark")
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    window = Window()
    window.show()
    if "--demo" not in sys.argv:
        QTimer.singleShot(0, window.offer_first_model)
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        model_dir, sp_model, target, text_file, output = sys.argv[2:7]

        def start():
            window.load_model(model_dir)
            window.use_sp_model(sp_model)
            window.source_text.setPlainText(open(text_file, encoding="utf-8").read())
            window.target_combo.choose(target)
            window.translate_or_cancel()

        def grab_when_done():
            if window.worker is None and window.translation:
                window.grab().save(output)
                app.quit()
            else:
                QTimer.singleShot(300, grab_when_done)

        QTimer.singleShot(300, start)
        if output != "-":  # with "-", the window stays open
            QTimer.singleShot(1500, grab_when_done)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
