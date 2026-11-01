import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename, askopenfile, askdirectory
from tkinter.filedialog import asksaveasfilename
from tkinter.messagebox import showinfo, showerror
import Pmw
from datetime import datetime
import ctranslate2
import sentencepiece as spm
from charset_normalizer import from_path
import fasttext
import multiprocessing
import os
import queue
import threading
import webbrowser
import json
from utils.paragraph_splitter import paragraph_tokenizer, paragraph_detokenizer, join_lines
from utils.model_info import read_vocabulary, detect_model_type
from utils.rtl import is_rtl_target, add_rtl_marks, strip_bidi_marks
from utils.settings import load_settings, save_settings


class TranslatorGUI:
    def __init__(self, window):
        self.window = window
        self.window.createcommand('tkAboutDialog', self.show_info)  # for macOS

        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(2, weight=1)

        self.model = tk.StringVar(self.main_frame)
        self.sp_model = tk.StringVar(self.main_frame)
        self.beam_size = tk.IntVar(self.main_frame)
        self.beam_size.set(3)

        self.settings = load_settings()
        self.remember_paths = tk.BooleanVar(
            self.main_frame, value=self.settings.get("remember_model_paths", True)
        )
        self.join_lines_option = tk.BooleanVar(
            self.main_frame, value=self.settings.get("join_lines", False)
        )
        self.rtl_view_option = tk.BooleanVar(
            self.main_frame, value=self.settings.get("rtl_view", True)
        )
        self.translation = ""  # the translation without direction marks
        self.target_is_rtl = False
        self.translator = None
        self.sp_source_model = None
        self.model_type = None  # "m2m", "nllb", "other", or None until a model is selected
        self.model_vocabulary = set()
        self.worker = None
        self.cancel_event = threading.Event()
        self.messages = queue.Queue()

        self.createWidgets()
        self.createMenu()
        self.restore_model_paths()

    def createWidgets(self):
        # Create the toolbar
        self.toolbar = tk.Frame(self.main_frame, bd=1, bg="white smoke")
        self.toolbar.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # Create the source text input
        self.source_text = tk.Text(
            self.main_frame,
            wrap="word",
            font=("Arial", 14),
            undo=True,
            bd=2,
            relief=tk.SUNKEN,
            padx=5,
            pady=5,
            highlightcolor="white smoke",
            highlightbackground="white smoke",
        )
        self.source_text.grid(row=2, column=0, sticky="nsew")
        self.source_text.focus_set()

        # Create the headers above the text areas
        self.source_header = tk.Label(
            self.main_frame, text="Source", anchor=tk.W, padx=7, bg="white smoke"
        )
        self.source_header.grid(row=1, column=0, sticky="nsew")
        self.target_header = tk.Label(
            self.main_frame, text="Translation", anchor=tk.W, padx=7, bg="white smoke"
        )
        self.target_header.grid(row=1, column=1, sticky="nsew")

        # Create the target text input
        self.target_text = tk.Text(
            self.main_frame,
            wrap="word",
            font=("Arial", 14),
            undo=True,
            bd=2,
            relief=tk.SUNKEN,
            padx=5,
            pady=5,
            highlightcolor="white smoke",
            highlightbackground="white smoke",
        )
        self.target_text.grid(row=2, column=1, sticky="nsew")
        self.target_text.tag_configure("rtl", justify="right")
        self.target_text.bind("<<Copy>>", self.copy_translation)

        # Create the statusbar, the progress bar, and the loaded model label
        self.statusframe = tk.Frame(self.main_frame, bd=1, relief=tk.SUNKEN, bg="white smoke")
        self.statusframe.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.statusbar = tk.Label(
            self.statusframe,
            anchor=tk.W,
            padx=5,
            pady=5,
            bg="white smoke",
            fg="black",
            text="Select a model and enter text to translate!",
        )
        self.statusbar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.model_info = tk.Label(
            self.statusframe, anchor=tk.E, padx=5, pady=5, bg="white smoke", fg="gray30"
        )
        self.model_info.pack(side=tk.RIGHT)
        self.progress = ttk.Progressbar(self.statusframe, length=200, mode="determinate")

        # Create the select CTranslate2 model button
        self.button_model = tk.Button(
            self.toolbar,
            text="CTranslate2 Model",
            width=20,
            highlightbackground="white smoke",
            command=self.open_model,
        )
        self.button_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the select SentencePiece model button
        self.button_sp_model = tk.Button(
            self.toolbar,
            text="SentencePiece Model",
            width=20,
            highlightbackground="white smoke",
            command=self.open_sp_model,
        )
        self.button_sp_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the translate button
        self.button_translate = tk.Button(
            self.toolbar,
            text="Translate",
            width=20,
            highlightbackground="white smoke",
            command=self.translate_input,
        )
        self.button_translate.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the balloon object and bind it to the buttons
        Pmw.initialise(self.window)
        self.balloon = Pmw.Balloon(self.window)
        self.balloon.bind(self.button_model, "Select CTranslate2 model directory")
        self.balloon.bind(self.button_sp_model, "Select a SentencePiece source model")
        self.balloon.bind(self.button_translate, "Translate the source text")
        # Change the background colour of the balloon
        self.lbl = self.balloon.component("label")
        self.lbl.config(background="white", padx=1, pady=1)

        # Create the beam_size label and radio buttons
        self.labelframe = tk.LabelFrame(self.toolbar, bd=0, bg="white smoke")
        self.labelframe.pack(side=tk.LEFT, padx=10)

        self.beam_size_label = tk.Label(
            self.labelframe, text="Beam Size:", bg="white smoke"
        )
        self.beam_size_label.pack(side=tk.LEFT, ipady=5)

        values = {"2": 2, "3": 3, "5": 5}

        for (text, value) in values.items():
            tk.Radiobutton(
                self.labelframe,
                text=text,
                variable=self.beam_size,
                value=value,
                bg="white smoke",
            ).pack(side=tk.LEFT, ipady=2)

        # Target language widgets, used by the multilingual models

        # Create a vertical separator
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            padding=3,
            selectbackground="white smoke",
            selectforeground="black",
        )

        separator = ttk.Separator(self.toolbar, orient="vertical")
        separator.pack(side=tk.LEFT, fill=tk.Y)

        self.target_label = tk.Label(
            self.toolbar,
            text="Target language:",
            bg="white smoke",
        )
        self.target_label.pack(side=tk.LEFT, padx=2, pady=2)

        # Load the JSON files containing the languages supported by the multilingual models
        dir_path = os.path.dirname(os.path.realpath(__file__))
        self.language_lists = {}
        for model_type in ("m2m", "nllb"):
            json_file = os.path.join(dir_path, "utils", model_type + "_languages.json")
            with open(json_file, encoding="utf-8") as languages_file:
                self.language_lists[model_type] = json.load(languages_file)
        json_file = os.path.join(dir_path, "utils", "fasttext_to_flores.json")
        with open(json_file, encoding="utf-8") as codes_file:
            self.fasttext_to_flores = json.load(codes_file)
        self.language_codes = {}

        # Create the target language selection combobox
        self.combobox = ttk.Combobox(self.toolbar, values=["None"], state="disabled", width=24)
        self.combobox.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.BOTH)
        self.combobox.current(0)
        self.balloon.bind(
            self.combobox,
            "For the multilingual models (M2M-100 and NLLB-200), select the target language",
        )

    def createMenu(self):
        # Create the menu bar and add the menu items
        self.menubar = tk.Menu(self.window)
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Open File...", command=self.open_file)
        self.filemenu.add_command(label="Save Translation...", command=self.save_file)
        self.filemenu.add_separator()
        self.filemenu.add_command(label="Exit", command=window.quit)
        self.menubar.add_cascade(label="File", menu=self.filemenu)

        # Create the Edit menu and add the menu items
        self.editmenu = tk.Menu(self.menubar, tearoff=0)
        self.editmenu.add_command(label="Clear", command=self.clear)
        self.editmenu.add_separator()
        self.editmenu.add_command(label="Undo", command=self.source_text.edit_undo)
        self.editmenu.add_command(label="Redo", command=self.source_text.edit_redo)
        self.editmenu.add_separator()
        self.editmenu.add_command(label="Cut", command=self.cut)
        self.editmenu.add_command(label="Copy", command=self.copy)
        self.editmenu.add_command(label="Paste", command=self.paste)
        self.editmenu.add_command(label="Select All", command=self.select_all)
        self.menubar.add_cascade(label="Edit", menu=self.editmenu)

        # Create the Translate menu and add the menu items
        self.translatemenu = tk.Menu(self.menubar, tearoff=0)
        self.translatemenu.add_command(label="Translate", command=self.translate_input)
        self.translatemenu.add_separator()
        self.translatemenu.add_command(
            label="Select CTranslate2 Model Folder", command=self.open_model
        )
        self.translatemenu.add_command(
            label="Select SentencePiece Model", command=self.open_sp_model
        )
        self.translatemenu.add_separator()
        self.translatemenu.add_checkbutton(
            label="Join Lines",
            variable=self.join_lines_option,
            command=self.store_settings,
        )
        self.translatemenu.add_checkbutton(
            label="Right-to-Left View",
            variable=self.rtl_view_option,
            command=self.toggle_rtl_view,
        )
        self.translatemenu.add_checkbutton(
            label="Remember Model Paths",
            variable=self.remember_paths,
            command=self.store_settings,
        )
        self.menubar.add_cascade(label="Translate", menu=self.translatemenu)

        # Create the Help menu and add the menu items
        self.helpmenu = tk.Menu(self.menubar, tearoff=0)
        self.helpmenu.add_command(
            label="Download NLLB-200 600M Model", command=self.download_nllb_600m
        )
        self.helpmenu.add_command(
            label="Download M2M-100 418M Model", command=self.download_m2m_418m
        )
        self.helpmenu.add_command(
            label="Download M2M-100 1.2B Model", command=self.download_m2m_12b
        )
        self.helpmenu.add_separator()
        self.helpmenu.add_command(label="About", command=self.show_info)
        self.menubar.add_cascade(label="Help", menu=self.helpmenu)

        self.window.config(menu=self.menubar)

    # Menu functions

    def copy(self):
        self.source_text.clipboard_clear()
        self.source_text.clipboard_append(self.source_text.selection_get())

    def cut(self):
        self.source_text.clipboard_clear()

        try:
            self.source_text.clipboard_append(self.source_text.selection_get())
            self.source_text.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except:
            pass

    def paste(self):
        self.source_text.insert(tk.INSERT, self.source_text.clipboard_get())

        self.line_count = len(self.source_text.get(1.0, tk.END).splitlines())
        self.statusbar.config(text="Lines: " + str(self.line_count))

    def copy_translation(self, event=None):
        try:
            selected = self.target_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return "break"
        self.target_text.clipboard_clear()
        self.target_text.clipboard_append(strip_bidi_marks(selected))
        return "break"

    def select_all(self):
        self.source_text.tag_add(tk.SEL, "1.0", tk.END)
        self.source_text.mark_set(tk.INSERT, "1.0")
        self.source_text.see(tk.INSERT)

    def open_file(self):
        self.file_name = askopenfilename(filetypes=[("Text Files", "*.txt")])
        if self.file_name:
            self.source_text.delete(1.0, tk.END)

            self.source_file_text = str(from_path(self.file_name).best())
            self.source_text.insert(tk.INSERT, self.source_file_text)

            self.line_count = len(self.source_text.get(1.0, tk.END).splitlines())
            lines_count_str = "Lines: " + str(self.line_count)
            words_count_str = "Words: " + str(len(self.source_file_text.split()))
            self.statusbar.config(text=lines_count_str + " | " + words_count_str)

    def save_file(self):
        self.file = asksaveasfilename(
            filetypes=[("Text Files", "*.txt")], defaultextension=".txt"
        )
        if self.file is not None:
            self.data = strip_bidi_marks(self.target_text.get(1.0, tk.END))
            if len(self.data) > 0:
                with open(self.file, "w+", encoding="utf-8") as output:
                    output.write(self.data)
            else:
                showinfo("", "Nothing to save!")

    def clear(self):
        self.source_text.delete(1.0, tk.END)
        self.show_translation("")
        self.statusbar.config(text="")

    def show_info(self):
        showinfo(
            "About",
            "DesktopTranslator (0.3.0)\n\nDeveloped by: Yasmin Moslem\nwww.machinetranslation.io",
        )

    def store_settings(self):
        self.settings["remember_model_paths"] = self.remember_paths.get()
        self.settings["join_lines"] = self.join_lines_option.get()
        self.settings["rtl_view"] = self.rtl_view_option.get()
        if self.remember_paths.get():
            self.settings["ct2_model"] = self.model.get()
            self.settings["sp_model"] = self.sp_model.get()
        else:
            self.settings.pop("ct2_model", None)
            self.settings.pop("sp_model", None)
        save_settings(self.settings)

    def restore_model_paths(self):
        if self.remember_paths.get():
            ct2_model = self.settings.get("ct2_model", "")
            sp_model = self.settings.get("sp_model", "")
            if os.path.isdir(ct2_model) and ctranslate2.contains_model(ct2_model):
                self.model.set(ct2_model)
                self.set_model_type(ct2_model)
            if os.path.isfile(sp_model):
                self.sp_model.set(sp_model)
            if self.model.get() != "" or self.sp_model.get() != "":
                self.statusbar.config(
                    text="Remembered models: "
                    + os.path.basename(self.model.get())
                    + " | "
                    + os.path.basename(self.sp_model.get())
                    + " (loaded when you click Translate)"
                )
                self.show_model_info()

    def load_remembered_models(self):
        # Models restored from the settings are loaded on the first translation
        if self.translator is None and self.model.get() != "":
            if not self.load_model(self.model.get()):
                self.model.set("")
        if self.sp_source_model is None and self.sp_model.get() != "":
            self.load_sp_model(self.sp_model.get())

    def set_model_type(self, model_dir):
        """Adapt the target language selector to the kind of model"""
        previous_type = self.model_type
        self.model_vocabulary = read_vocabulary(model_dir)
        self.model_type = detect_model_type(self.model_vocabulary)
        if self.model_type in self.language_lists:
            self.language_codes = self.language_lists[self.model_type]
            self.combobox.config(values=["None"] + sorted(self.language_codes), state="readonly")
            if previous_type != self.model_type:
                self.combobox.set("None")
        else:
            self.language_codes = {}
            self.combobox.config(values=["Not needed"], state="disabled")
            self.combobox.set("Not needed")

    def show_model_info(self):
        names = [os.path.basename(self.model.get()), os.path.basename(self.sp_model.get())]
        self.model_info.config(text="Model: " + " | ".join(n for n in names if n))

    def initial_dir(self, directory):
        # The dialogs start in the folder of the last selected model, if it still exists
        return directory if os.path.isdir(directory) else None

    def open_model(self):
        self.toolbar.update()  # for macOS
        model_dir = askdirectory(
            title="Select the CTranslate2 model folder",
            message="Select the CTranslate2 model folder",  # shown by macOS instead of the title
            initialdir=self.initial_dir(os.path.dirname(self.model.get())),
        )
        if model_dir != "":
            self.load_model(model_dir)

    def load_model(self, model_dir):
        self.model_dir = model_dir
        # Check if the model is a valid CTranslate2 model
        if not ctranslate2.contains_model(self.model_dir):
            showerror(
                "Invalid CTranslate2 model",
                "Please make sure you select the direcotry of a valid CTranslate2 model!",
            )
            return False

        self.set_model_type(self.model_dir)

        self.model.set(self.model_dir)
        self.statusbar.config(text="CT2 Model path: " + self.model_dir)

        self.cpu_num = os.cpu_count()
        self.inter_threads = 2
        self.intra_threads = int(self.cpu_num / 2)

        self.translator = ctranslate2.Translator(
            self.model_dir,
            device="cpu",
            inter_threads=self.inter_threads,
            intra_threads=self.intra_threads,
        )
        self.show_model_info()
        self.store_settings()
        return True

    def open_sp_model(self):
        self.toolbar.update()  # for macOS
        self.model_file = askopenfile(
            title="Select the SentencePiece model file",
            filetypes=[("SentencePiece Model", "*.model")],
            initialdir=self.initial_dir(os.path.dirname(self.sp_model.get())),
        )
        if self.model_file:
            self.load_sp_model(self.model_file.name)

    def load_sp_model(self, sp_model_path):
        self.sp_model.set(sp_model_path)
        self.statusbar.config(text="SP Model path: " + sp_model_path)
        self.sp_source_model = spm.SentencePieceProcessor(sp_model_path)
        self.show_model_info()
        self.store_settings()

    def download_nllb_600m(self):
        self.toolbar.update()  # for macOS
        webbrowser.open_new(
            "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.3.0/NLLB-200_distilled_600M_int8_ct2.zip"
        )

    def download_m2m_418m(self):
        self.toolbar.update()  # for macOS
        webbrowser.open_new(
            "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_418m_parameter_model_ct2.zip"
        )

    def download_m2m_12b(self):
        self.toolbar.update()  # for macOS
        webbrowser.open_new(
            "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_12b_parameter_model_ct2.zip"
        )

    def detect_language(self, text):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        fasttext_model = os.path.join(dir_path, "utils", "lid.176.ftz")
        model = fasttext.load_model(fasttext_model)
        text = text[:200].lower() if len(text) > 200 else text.lower()
        # model.predict() fails with NumPy 2, so use the underlying call
        prediction = model.f.predict(text.replace("\n", " "), 2, 0.0, "strict")
        self.detected_lang_code = prediction[0][1][9:]
        self.detected_lang_code_alt = prediction[1][1][9:]
        return self.detected_lang_code, self.detected_lang_code_alt

    def find_source_language(self, text):
        """Detect the source language; return its code and the prefix token the model needs"""
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
            return codes[0], ""
        return None, None

    def translate_input(self):
        if self.worker is not None:
            return

        self.show_translation("")
        self.source_text_string = self.source_text.get(1.0, tk.END)

        if len(self.source_text_string) > 1:
            self.load_remembered_models()

        if not (
            len(self.source_text_string) > 1
            and self.model.get() != ""
            and self.sp_model.get() != ""
        ):
            showerror(
                "No model selected",
                "Please select both CTranslate2 and SentencePiece models, and enter text to translate.",
            )
            return

        # Target language, for the multilingual models
        self.target_lang_code = ""
        if self.model_type in self.language_lists:
            lang_option = self.combobox.get()
            if lang_option == "None":
                showerror("Target language", "Please select the target language.")
                return
            self.target_lang_code = self.language_codes[lang_option]
            if self.target_lang_code not in self.model_vocabulary:
                showerror(
                    "Target language",
                    "This model does not support the target language " + lang_option + ".",
                )
                return

        self.target_is_rtl = is_rtl_target(self.model_type, self.target_lang_code)

        # Source language
        self.source_lang_code, self.src_prefix = self.find_source_language(
            self.source_text_string
        )
        if self.source_lang_code is None:
            showerror("", "Source language not supported or not recognized! Try to add more text.")
            return
        self.source_header.config(text="Source (detected: " + self.source_lang_code + ")")

        source_text = self.source_text_string
        if self.join_lines_option.get():
            source_text = join_lines(source_text)
        self.source_sents, self.breaks = paragraph_tokenizer(
            source_text, self.source_lang_code
        )

        self.start = datetime.now()
        self.batches = [
            self.source_sents[i : i + 8] for i in range(0, len(self.source_sents), 8)
        ]
        self.total_words = max(len(" ".join(self.source_sents).split()), 1)

        self.progress.config(maximum=self.total_words, value=0)
        self.progress.pack(side=tk.RIGHT, padx=5)
        self.statusbar.config(text="Translating...")
        self.button_translate.config(text="Cancel", command=self.cancel_translation)
        self.cancel_event.clear()

        self.worker = threading.Thread(
            target=self.run_translation,
            args=(self.batches, self.beam_size.get(), self.target_lang_code, self.src_prefix),
            daemon=True,
        )
        self.worker.start()
        self.window.after(100, self.poll_translation)

    def show_translation(self, text):
        """Show the translation; right-to-left languages get direction marks and a read-only pane"""
        self.translation = text
        self.target_text.config(state=tk.NORMAL)
        self.target_text.delete(1.0, tk.END)
        if text == "":
            self.target_text.config(insertwidth=2)
        elif self.target_is_rtl and self.rtl_view_option.get():
            self.target_text.insert(tk.END, add_rtl_marks(text) + "\n", "rtl")
            # The cursor is hidden because Tk splits a line at the cursor and changes its direction
            self.target_text.config(state=tk.DISABLED, insertwidth=0)
        else:
            self.target_text.insert(tk.END, text + "\n")
            self.target_text.config(insertwidth=2)

    def toggle_rtl_view(self):
        if str(self.target_text.cget("state")) == tk.NORMAL:
            # Keep the edits made in the editable pane
            self.translation = strip_bidi_marks(self.target_text.get(1.0, tk.END)).rstrip("\n")
        if self.translation != "":
            self.show_translation(self.translation)
        self.store_settings()

    def cancel_translation(self):
        self.cancel_event.set()
        self.statusbar.config(text="Cancelling...")

    def run_translation(self, batches, beam_size, target_lang_code, src_prefix):
        # Runs in a worker thread, so it must not touch the interface; it reports through a queue
        try:
            translations = []
            words_done = 0
            for batch in batches:
                if self.cancel_event.is_set():
                    self.messages.put(("cancelled", None))
                    return
                translations.extend(
                    self.translate_batch(batch, beam_size, target_lang_code, src_prefix)
                )
                words_done += len(" ".join(batch).split())
                self.messages.put(("progress", words_done))
            self.messages.put(("done", translations))
        except Exception as error:
            self.messages.put(("error", error))

    def translate_batch(self, batch, beam_size, target_lang_code, src_prefix):
        source_tok = self.sp_source_model.encode(batch, out_type=str)
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
            repetition_penalty=1.2,
            target_prefix=target_prefix,
        )

        translations = []
        for result in results:
            tokens = result.hypotheses[0]
            if target_prefix:
                tokens = tokens[1:]  # the first token is the target language code
            translations.append("".join(tokens).replace("\u2581", " ").strip())
        return translations

    def poll_translation(self):
        finished = False
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    self.progress.config(value=payload)
                    percent = int(100 * payload / self.total_words)
                    self.statusbar.config(text="Translating... " + str(percent) + "%")
                elif kind == "done":
                    translations_formatted = paragraph_detokenizer(payload, self.breaks)
                    self.show_translation(translations_formatted)
                    elapsed = str(datetime.now() - self.start)
                    self.statusbar.config(
                        text="Congratulations! Translation completed. Time elapsed: " + elapsed
                    )
                    finished = True
                elif kind == "cancelled":
                    self.statusbar.config(text="Translation cancelled.")
                    finished = True
                elif kind == "error":
                    self.statusbar.config(text="Translation failed.")
                    showerror("Translation failed", str(payload))
                    finished = True
        except queue.Empty:
            pass

        if finished:
            self.worker = None
            self.progress.pack_forget()
            self.button_translate.config(text="Translate", command=self.translate_input)
        else:
            self.window.after(100, self.poll_translation)


# Create the root window
if __name__ == "__main__":
    # Needed in the stand-alone app, otherwise helper processes start new windows
    multiprocessing.freeze_support()

    window = tk.Tk()
    window.title("DesktopTranslator")
    window.resizable(True, True)
    window.state("zoomed")   

    # Get the current screen width and height (optional, for macOS)
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    window.geometry(str(screen_width) + "x" + str(screen_height))

    app = TranslatorGUI(window)
    window.mainloop()
