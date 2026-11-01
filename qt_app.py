"""A prototype of DesktopTranslator with a Qt interface, using the same engine as translator.py.

Usage: python qt_app.py
       python qt_app.py --demo MODEL_DIR SP_MODEL TARGET_LANGUAGE TEXT_FILE OUTPUT.png (OUTPUT.png can be - to keep the window open)
"""
import os
import sys
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from engine import AUTO_DETECT, Engine, EngineError, format_duration
from utils.paragraph_splitter import paragraph_detokenizer
from utils.rtl import is_rtl_language, is_rtl_target

PLACEHOLDER = "Select a language..."


class Worker(QThread):
    progress = Signal(int)
    done = Signal(list)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, engine, batches, beam_size, target_lang_code, src_prefix):
        super().__init__()
        self.engine, self.batches = engine, batches
        self.beam_size, self.target_lang_code, self.src_prefix = beam_size, target_lang_code, src_prefix
        self.cancel = False

    def run(self):
        try:
            translations = self.engine.translate(
                self.batches, self.beam_size, self.target_lang_code, self.src_prefix,
                is_cancelled=lambda: self.cancel, on_progress=self.progress.emit,
            )
            self.cancelled.emit() if translations is None else self.done.emit(translations)
        except Exception as error:
            self.failed.emit(str(error))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DesktopTranslator (Qt prototype)")
        self.engine = Engine()
        self.worker = None
        self.translation = ""

        self.model_button = QPushButton("CTranslate2 Model")
        self.sp_button = QPushButton("SentencePiece Model")
        self.translate_button = QPushButton("Translate")
        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        self.source_combo.addItem(AUTO_DETECT)
        self.target_combo.addItem("Load a model first")
        self.source_combo.setEnabled(False)
        self.target_combo.setEnabled(False)
        self.source_header = QLabel("Source")
        self.copy_button = QPushButton("Copy")
        self.source_text = QTextEdit()
        self.target_text = QTextEdit()
        for pane in (self.source_text, self.target_text):
            pane.setFontPointSize(14)
            pane.setAcceptRichText(False)
            # Each paragraph takes its direction from its first strong character
            option = pane.document().defaultTextOption()
            option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
            pane.document().setDefaultTextOption(option)

        top = QHBoxLayout()
        for widget in (self.model_button, self.sp_button, self.translate_button):
            top.addWidget(widget)
        top.addStretch()
        second = QHBoxLayout()
        for widget in (QLabel("Source language:"), self.source_combo, QLabel("Target language:"), self.target_combo):
            second.addWidget(widget)
        second.addStretch()
        headers = QHBoxLayout()
        headers.addWidget(self.source_header, 1)
        headers.addWidget(QLabel("Translation"), 1)
        headers.addWidget(self.copy_button)
        panes = QHBoxLayout()
        panes.addWidget(self.source_text)
        panes.addWidget(self.target_text)
        layout = QVBoxLayout()
        for part in (top, second, headers, panes):
            layout.addLayout(part)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Select a model and enter text to translate!")

        self.model_button.clicked.connect(self.choose_model)
        self.sp_button.clicked.connect(self.choose_sp_model)
        self.translate_button.clicked.connect(self.translate_or_cancel)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.translation))
        self.source_combo.currentTextChanged.connect(lambda _: self.update_direction())

    # Models

    def choose_model(self):
        model_dir = QFileDialog.getExistingDirectory(self, "Select the CTranslate2 model folder")
        if model_dir:
            self.load_model(model_dir)

    def load_model(self, model_dir):
        try:
            changed = self.engine.load_model(model_dir)
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return
        if self.engine.model_type in self.engine.language_lists:
            names = sorted(self.engine.language_codes)
            if changed:
                self.target_combo.clear()
                self.target_combo.addItem(PLACEHOLDER)
                self.target_combo.addItems(names)
                self.source_combo.clear()
                self.source_combo.addItem(AUTO_DETECT)
                self.source_combo.addItems(names)
            self.target_combo.setEnabled(True)
            self.source_combo.setEnabled(True)
        else:
            self.target_combo.clear()
            self.target_combo.addItem("Not needed")
            self.source_combo.clear()
            self.source_combo.addItem(AUTO_DETECT)
            self.target_combo.setEnabled(False)
            self.source_combo.setEnabled(False)
        self.statusBar().showMessage("Model: " + os.path.basename(model_dir))

    def choose_sp_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select the SentencePiece model file", "", "SentencePiece Model (*.model)")
        if path:
            self.engine.load_sp_model(path)

    # Direction of the source pane

    def update_direction(self):
        text = self.source_text.toPlainText()
        selected = self.source_combo.currentText()
        if selected != AUTO_DETECT and selected in self.engine.language_codes:
            rtl = is_rtl_target(self.engine.model_type, self.engine.language_codes[selected])
        elif len(text.strip()) > 1:
            codes = self.engine.detect_language(text)
            rtl = bool(codes) and is_rtl_language(codes[0])
        else:
            rtl = False
        return rtl

    # Translation

    def translate_or_cancel(self):
        if self.worker is not None:
            self.worker.cancel = True
            return
        text = self.source_text.toPlainText()
        if self.engine.translator is None or self.engine.sp_model is None or not text.strip():
            QMessageBox.critical(self, "No model selected", "Please select both models, and enter text to translate.")
            return
        try:
            target = self.engine.target_language(self.target_combo.currentText())
        except EngineError as error:
            QMessageBox.critical(self, error.title, error.message)
            return
        source_code, prefix = self.engine.source_language(text, self.source_combo.currentText())
        if source_code is None:
            QMessageBox.critical(self, "Source language", "The source language is not supported or not recognized.")
            return
        if self.source_combo.currentText() == AUTO_DETECT:
            self.source_header.setText("Source (detected: " + source_code + ")")
        self.sentences, self.breaks, batches, self.total_words = self.engine.split(text, source_code)
        self.start = time.time()
        self.worker = Worker(self.engine, batches, 3, target, prefix)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.cancelled.connect(lambda: self.finish("Translation cancelled."))
        self.worker.failed.connect(lambda message: self.finish("Translation failed: " + message))
        self.translate_button.setText("Cancel")
        self.target_is_rtl = is_rtl_target(self.engine.model_type, target)
        self.worker.start()

    def on_progress(self, words_done):
        status = "Translating... " + str(int(100 * words_done / self.total_words)) + "%"
        elapsed = time.time() - self.start
        if elapsed > 3:
            status += " (about " + format_duration(elapsed * (self.total_words - words_done) / words_done) + " left)"
        self.statusBar().showMessage(status)

    def on_done(self, translations):
        self.translation = paragraph_detokenizer(translations, self.breaks)
        self.target_text.setPlainText(self.translation)
        self.finish("Translation completed in %.1f s." % (time.time() - self.start))

    def finish(self, message):
        self.worker.wait()
        self.worker = None
        self.translate_button.setText("Translate")
        self.statusBar().showMessage(message)


def main():
    app = QApplication(sys.argv)
    if "--dark" in sys.argv:  # to test the dark appearance; by default the system setting is used
        sys.argv.remove("--dark")
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    window = Window()
    window.resize(1200, 640)
    window.show()
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        model_dir, sp_model, target, text_file, output = sys.argv[2:7]

        def start():
            window.load_model(model_dir)
            window.engine.load_sp_model(sp_model)
            window.source_text.setPlainText(open(text_file, encoding="utf-8").read())
            window.target_combo.setCurrentText(target)
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
