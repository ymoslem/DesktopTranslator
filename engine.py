"""The part of DesktopTranslator without interface code: models, languages, and translation."""
import codecs
import json
import os
import subprocess
import sys

import ctranslate2
import fasttext
import sentencepiece as spm
from charset_normalizer import from_path

from utils.model_info import read_vocabulary, detect_model_type
from utils.paragraph_splitter import paragraph_tokenizer, join_lines
from utils.settings import load_settings, save_settings

AUTO_DETECT = "Auto detect"
LONG_LINE_CHARS = 100000  # a text area takes minutes to display a single line much longer than this
REPETITION_PENALTY = 1.2  # the optional penalty for repeated words; a penalty of 1.0 is the default, as it scored better
BATCH_SENTENCES = 8  # sentences translated in one call, so that progress and cancelling stay quick

# The folder with the program files, also when the app is packaged
DATA_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


class EngineError(Exception):
    """An error to show to the user, with a title for the message box"""

    def __init__(self, title, message):
        super().__init__(message)
        self.title = title
        self.message = message


def format_duration(seconds):
    if seconds < 90:
        return str(max(int(round(seconds)), 1)) + " s"
    if seconds < 5400:
        return str(int(round(seconds / 60))) + " min"
    return str(round(seconds / 3600, 1)) + " h"


def longest_line(text):
    """Length of the longest line, in characters"""
    return max((len(line) for line in text.splitlines()), default=0)


def read_text_file(file_name, encoding=None):
    """Read a text file; the encoding is tried as UTF-8 first, then guessed, unless it is given

    Returns:
        text (str): The text of the file
        encoding (str): The encoding that was used

    Raises:
        OSError, LookupError (unknown encoding), or UnicodeError (wrong encoding)
    """
    if encoding:
        codecs.lookup(encoding)
        with open(file_name, encoding=encoding) as text_file:
            return text_file.read(), encoding
    try:
        with open(file_name, encoding="utf-8-sig") as text_file:
            return text_file.read(), "utf-8"
    except UnicodeDecodeError:
        match = from_path(file_name).best()
        if match is None:
            with open(file_name, encoding="cp1252", errors="replace") as text_file:
                return text_file.read(), "cp1252"
        return str(match), match.encoding


def write_text_file(file_name, text):
    """Save a translation as UTF-8, without a byte order mark and with one final newline"""
    with open(file_name, "w", encoding="utf-8") as output:
        output.write(text.rstrip() + "\n")


class Preferences:
    """The settings that are kept between sessions"""

    def __init__(self):
        self.data = load_settings()
        self.target_memory = dict(self.data.get("target_language", {}))

    def get(self, key, default):
        return self.data.get(key, default)

    def remembered_target(self, model_type, remember):
        return self.target_memory.get(model_type, "") if remember else ""

    def set(self, key, value):
        self.data[key] = value

    def write(self):
        save_settings(self.data)

    def save(self, remember, join_lines_option, rtl_view, ct2_model, sp_model, model_type=None, target=None, repetition_penalty=None):
        self.data["remember_model_paths"] = remember
        if repetition_penalty is not None:
            self.data["repetition_penalty"] = repetition_penalty
        self.data["join_lines"] = join_lines_option
        self.data["rtl_view"] = rtl_view
        if model_type and target:
            self.target_memory[model_type] = target
        if remember:
            self.data["ct2_model"] = ct2_model
            self.data["sp_model"] = sp_model
            self.data["target_language"] = self.target_memory
        else:
            for key in ("ct2_model", "sp_model", "target_language"):
                self.data.pop(key, None)
        save_settings(self.data)


def memory_info():
    """Total and available memory of the computer, in bytes; None if it cannot be read"""
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("available", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                            ("page_available", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                            ("virtual_available", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]

            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total, status.available
        if sys.platform == "darwin":
            import subprocess

            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            lines = subprocess.check_output(["vm_stat"], text=True).splitlines()
            page = int(lines[0].split("page size of")[1].split()[0])
            pages = {line.split(":")[0]: int(line.split(":")[1].strip().rstrip(".")) for line in lines[1:] if ":" in line}
            # Free, inactive, speculative, and purgeable pages can be used when needed
            free = sum(pages.get("Pages " + name, 0) for name in ("free", "inactive", "speculative", "purgeable"))
            return total, free * page
        with open("/proc/meminfo") as meminfo:
            values = {line.split(":")[0]: int(line.split(":")[1].split()[0]) * 1024 for line in meminfo}
        return values["MemTotal"], values["MemAvailable"]
    except (OSError, ValueError, KeyError, IndexError, AttributeError, subprocess.SubprocessError):
        return None


def memory_needed(model_dir):
    """Estimated memory to translate with a CTranslate2 model, in bytes

    It is 1.3 times the size of the model file plus 1 GB, which covers the sentences of a normal text.
    A very long sentence needs more, and a larger beam size slightly more."""
    size = os.path.getsize(os.path.join(model_dir, "model.bin")) if os.path.isfile(os.path.join(model_dir, "model.bin")) else 0
    return int(1.3 * size + 1e9)


def memory_warning(model_dir, info=None):
    """A warning for the user if the model may not fit in the memory of the computer, else ""."""
    info = info or memory_info()
    if info is None:
        return ""
    total, available = info
    needed = memory_needed(model_dir)
    if needed > 0.8 * total:
        return ("This model needs about %.1f GB of memory, and this computer has %.1f GB. "
                "It will probably be very slow or fail." % (needed / 1e9, total / 1e9))
    if needed > available:
        return ("This model needs about %.1f GB of memory, and %.1f GB is free now. "
                "Closing other applications may help." % (needed / 1e9, available / 1e9))
    return ""


SENTENCEPIECE_NAMES = ("sentencepiece.model", "sentencepiece.bpe.model", "source.spm", "source.spm.model")


def find_sentencepiece(model_dir):
    """Look for the SentencePiece model of a CTranslate2 model

    It is searched in the model folder, in the folder above it, and in a sp_model folder next to it.

    Returns:
        candidates (list): Paths of the files found in the first folder that has any; the file with a
            usual name comes alone, so one path means it can be used without asking
    """
    parent = os.path.dirname(os.path.normpath(model_dir))
    for folder in (model_dir, parent, os.path.join(parent, "sp_model")):
        if not os.path.isdir(folder):
            continue
        files = sorted(os.listdir(folder))
        for name in SENTENCEPIECE_NAMES:
            if name in files:
                return [os.path.join(folder, name)]
        found = [os.path.join(folder, f) for f in files if f.endswith((".model", ".spm"))]
        if found:
            return found
    return []


class Engine:
    """Loads a CTranslate2 model with its SentencePiece model, and translates with them"""

    def __init__(self):
        self.language_lists = {}
        for model_type in ("m2m", "nllb"):
            with open(os.path.join(DATA_DIR, "utils", model_type + "_languages.json"), encoding="utf-8") as file:
                self.language_lists[model_type] = json.load(file)
        with open(os.path.join(DATA_DIR, "utils", "fasttext_to_flores.json"), encoding="utf-8") as file:
            self.fasttext_to_flores = json.load(file)
        self.flores_to_fasttext = {v: k for k, v in self.fasttext_to_flores.items()}

        self.lid_model = None  # the fastText language identification model, loaded once
        self.translator = None
        self.sp_model = None
        self.model_dir = ""
        self.model_type = None  # "m2m", "nllb", "other", or None until a model is selected
        self.vocabulary = set()
        self.language_codes = {}  # names and codes of the languages of a multilingual model

    # Models

    def inspect_model(self, model_dir):
        """Read the vocabulary to tell the kind of model, without loading it

        Returns:
            changed (bool): True if this kind of model differs from the previous one
        """
        previous_type = self.model_type
        self.vocabulary = read_vocabulary(model_dir)
        self.model_type = detect_model_type(self.vocabulary)
        self.language_codes = self.language_lists.get(self.model_type, {})
        return previous_type != self.model_type

    def is_model(self, model_dir):
        return os.path.isdir(model_dir) and ctranslate2.contains_model(model_dir)

    def load_model(self, model_dir):
        """Load a CTranslate2 model; returns True if its kind differs from the previous model"""
        if not self.is_model(model_dir):
            raise EngineError(
                "Invalid CTranslate2 model",
                "Please make sure you select the direcotry of a valid CTranslate2 model!",
            )
        changed = self.inspect_model(model_dir)
        self.translator = ctranslate2.Translator(
            model_dir,
            device="cpu",
            inter_threads=2,
            intra_threads=int(os.cpu_count() / 2),
        )
        self.model_dir = model_dir
        return changed

    def load_sp_model(self, sp_model_path):
        self.sp_model = spm.SentencePieceProcessor(sp_model_path)

    # Languages

    def detect_language(self, text):
        """Languages of a text, the most likely first; none for text without letters"""
        if self.lid_model is None:
            self.lid_model = fasttext.load_model(os.path.join(DATA_DIR, "utils", "lid.176.ftz"))
        text = text[:200].lower() if len(text) > 200 else text.lower()
        # model.predict() fails with NumPy 2, so use the underlying call
        prediction = self.lid_model.f.predict(text.replace("\n", " "), 2, 0.0, "strict")
        return [label[9:] for _, label in prediction]

    def source_language(self, text, selected=AUTO_DETECT):
        """Return the source language code and the prefix token the model needs

        The language is the one selected, or else the one detected from the text.
        Both are None if the language is not supported by the model."""
        if selected != AUTO_DETECT and selected in self.language_codes:
            prefix = self.language_codes[selected]
            if self.model_type == "m2m":
                return prefix.strip("_"), prefix
            return self.flores_to_fasttext.get(prefix, "en"), prefix
        codes = self.detect_language(text)
        if self.model_type == "m2m":
            for code in codes:
                if "__" + code + "__" in self.language_codes.values():
                    return code, "__" + code + "__"
        elif self.model_type == "nllb":
            for code in codes:
                if code in self.fasttext_to_flores:
                    return code, self.fasttext_to_flores[code]
        else:
            return (codes[0] if codes else "en"), ""
        return None, None

    def target_language(self, name):
        """Return the target language code of a multilingual model, or "" for other models"""
        if self.model_type not in self.language_lists:
            return ""
        if name not in self.language_codes:
            raise EngineError("Target language", "Please select the target language.")
        code = self.language_codes[name]
        if code not in self.vocabulary:
            raise EngineError("Target language", "This model does not support the target language " + name + ".")
        return code

    # Translation

    def split(self, text, source_lang_code, join=False):
        """Split a text into sentences, and the batches to translate

        Returns:
            sentences (list), breaks (list): see paragraph_tokenizer
            batches (list): lists of sentences
            words (int): number of words
        """
        sentences, breaks = paragraph_tokenizer(join_lines(text) if join else text, source_lang_code)
        batches = [sentences[i : i + BATCH_SENTENCES] for i in range(0, len(sentences), BATCH_SENTENCES)]
        return sentences, breaks, batches, max(len(" ".join(sentences).split()), 1)

    def translate_batch(self, batch, beam_size, target_lang_code, src_prefix, repetition_penalty=1.0):
        source_tok = self.sp_model.encode(batch, out_type=str)
        if src_prefix != "":
            source_tok = [[src_prefix] + sent for sent in source_tok]
        if self.model_type == "nllb":
            source_tok = [sent + ["</s>"] for sent in source_tok]

        target_prefix = [[target_lang_code]] * len(batch) if target_lang_code else None
        results = self.translator.translate_batch(
            source=source_tok,
            beam_size=beam_size,
            batch_type="tokens",
            max_batch_size=1024 if target_prefix else 2048,
            replace_unknowns=True,
            repetition_penalty=repetition_penalty,
            target_prefix=target_prefix,
        )

        translations = []
        for result in results:
            tokens = result.hypotheses[0]
            if target_prefix:
                tokens = tokens[1:]  # the first token is the target language code
            translations.append("".join(tokens).replace("▁", " ").strip())
        return translations

    def translate(self, batches, beam_size, target_lang_code, src_prefix, is_cancelled=lambda: False, on_progress=None, repetition_penalty=1.0):
        """Translate the batches; returns the translated sentences, or None if cancelled"""
        translations = []
        words_done = 0
        for batch in batches:
            if is_cancelled():
                return None
            translations.extend(self.translate_batch(batch, beam_size, target_lang_code, src_prefix, repetition_penalty))
            words_done += len(" ".join(batch).split())
            if on_progress:
                on_progress(words_done)
        return translations
