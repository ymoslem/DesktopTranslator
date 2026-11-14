"""Background threads, so that translating, downloading and checking for updates do not freeze the window"""
from PySide6.QtCore import QThread, Signal

from engine import EngineError, download_model
from gui import updates


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


class UpdateWorker(QThread):
    """Asks GitHub for the latest version in the background"""

    found = Signal(str, str)  # the tag and the page of the latest release
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(*updates.fetch_latest())
        except Exception as error:
            self.failed.emit(str(error))
