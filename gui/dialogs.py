"""Dialogs for the download of a model, the first start, translating a document, and the preferences"""
import os
import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from engine import MODEL_DOWNLOAD, format_duration
from gui.constants import APP_NAME, CPU_SPEEDS, DEFAULT_QUALITY, DEVICES, QUALITY
from gui.widgets import InfoSign


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


def with_info(widget, text):
    """The widget followed by an (i) sign, which shows the text as a tooltip"""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(widget)
    row.addWidget(InfoSign(text))
    row.addStretch()
    holder = QWidget()
    holder.setLayout(row)
    return holder


class PreferencesDialog(QDialog):
    def __init__(self, parent, beam_size, join_lines, remember, repetition, device="cpu", gpu=False, load_at_start=True, cpu_speed="standard"):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.gpu = gpu  # an NVIDIA GPU is available, so the device can be chosen
        self.device_box = QComboBox()
        self.device_box.addItems(DEVICES)
        self.device_box.setCurrentText(DEVICES[1] if device == "cuda" and gpu else DEVICES[0])
        self.speed_box = QComboBox()
        self.speed_box.addItems(CPU_SPEEDS)
        self.speed_box.setCurrentText(next((name for name, key in CPU_SPEEDS.items() if key == cpu_speed), "Standard"))
        self.quality = QComboBox()
        self.quality.addItems(QUALITY)
        self.quality.setCurrentText(next((n for n, b in QUALITY.items() if b == beam_size), DEFAULT_QUALITY))
        self.repetition = QCheckBox("Avoid repeated words")
        self.repetition.setChecked(repetition)
        self.join_lines = QCheckBox("Join lines inside a paragraph")
        self.join_lines.setChecked(join_lines)
        self.remember = QCheckBox("Remember the last model and target language")
        self.remember.setChecked(remember)
        self.load_at_start = QCheckBox("Load the last model at start")
        self.load_at_start.setChecked(load_at_start)
        self.load_at_start.setEnabled(remember)  # only a remembered model can be loaded
        self.remember.toggled.connect(self.load_at_start.setEnabled)
        form = QFormLayout()
        form.addRow("Translation quality:", with_info(
            self.quality, "A larger beam size searches more candidate translations and takes longer. "
                          "In our tests, beam size 1 was clearly worse than 3, and beam size 5 was not clearly better."))
        form.addRow("Speed on the CPU:", with_info(
            self.speed_box, "Larger batches make translation on the CPU faster, and progress and Cancel update less often. "
                            "In our tests, Fastest was about 1.2 to 1.5 times as fast as Standard. "
                            "Automatic makes each batch as large as the speed of your computer allows in about 5 seconds, "
                            "so the same text can be translated a little differently from one run to another."))
        if gpu:
            form.addRow("Run on:", with_info(
                self.device_box, "GPU can be faster than the CPU, if its memory is large enough for the model. "
                "The model runs as float16 on the GPU, or as int8_float16 if float16 does not fit."))
        form.addRow(with_info(self.repetition, "Applies a repetition penalty of 1.2. It scored lower in our tests."))
        form.addRow(with_info(self.join_lines, "For text from PDF or OCR, where lines break inside a paragraph."))
        form.addRow(with_info(self.remember, "Opens the last model again at the next start, and selects its last target language."))
        form.addRow(with_info(self.load_at_start, "Loads the model when the app starts, so the first translation is not slower. "
                                                  "A model that may not fit in memory is loaded when you translate."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def device(self):
        """The device to use, cuda or cpu"""
        return "cuda" if self.gpu and self.device_box.currentText() == DEVICES[1] else "cpu"

    def cpu_speed(self):
        """The level of the speed on the CPU, a key of engine.CPU_SENTENCES"""
        return CPU_SPEEDS[self.speed_box.currentText()]

    def values(self):
        return QUALITY[self.quality.currentText()], self.join_lines.isChecked(), self.remember.isChecked(), self.repetition.isChecked()


class DiagnosticsDialog(QDialog):
    """Shows the information for a report of an issue, to check and change before it is copied"""

    def __init__(self, parent, text, issues_url):
        super().__init__(parent)
        self.setWindowTitle("Diagnostic Info")
        self.issues_url = issues_url
        note = QLabel("This report includes the versions, the hardware, the settings, the name of the model folder, and the last error message. "
                      "It does <b>not</b> include your text, file names, or paths. "
                      "Check it before you share it, and paste it into your report of the issue.")
        note.setWordWrap(True)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumSize(560, 360)
        self.status = QLabel("")
        copy = QPushButton("Copy")
        copy.setDefault(True)
        copy.clicked.connect(self.copy)
        report = QPushButton("Report an Issue...")
        report.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.issues_url + "/new")))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        for button in (copy, report, close):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.edit)
        layout.addLayout(row)

    def copy(self):
        QApplication.clipboard().setText(self.edit.toPlainText())
        self.status.setText("Copied.")
