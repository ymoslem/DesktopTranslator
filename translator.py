import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename, askopenfile, askdirectory
from tkinter.filedialog import asksaveasfilename
from tkinter.messagebox import showinfo, showerror, askyesno
from tkinter.simpledialog import askstring
import Pmw
from datetime import datetime
import ctranslate2
import sentencepiece as spm
from charset_normalizer import from_path
import fasttext
import codecs
import multiprocessing
import os
import queue
import threading
import webbrowser
import json
from utils.paragraph_splitter import paragraph_tokenizer, paragraph_detokenizer, join_lines
from utils.model_info import read_vocabulary, detect_model_type
from utils.rtl import is_rtl_target, is_rtl_language, add_rtl_marks, strip_bidi_marks
from utils.settings import load_settings, save_settings


AUTO_DETECT = "Auto detect"
TARGET_PLACEHOLDER = "Select a language..."
LONG_LINE_CHARS = 100000  # Tk takes minutes to display a single line much longer than this


def format_duration(seconds):
    if seconds < 90:
        return str(max(int(round(seconds)), 1)) + " s"
    if seconds < 5400:
        return str(int(round(seconds / 60))) + " min"
    return str(round(seconds / 3600, 1)) + " h"


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
        self.target_memory = dict(self.settings.get("target_language", {}))
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
        self.lid_model = None  # the fastText language identification model, loaded once
        self.source_rtl = False
        self.file_name = ""
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

    def text_size(self, points=14):
        """Size of the text font; Tk 8.6 on macOS counts a point as one pixel, Tk 9 as 4/3 pixels"""
        scaling = float(self.window.tk.call("tk", "scaling"))
        return round(points * 4 / 3 / scaling) if scaling < 1.2 else points

    def createWidgets(self):
        # Create the toolbar
        self.toolbar = tk.Frame(self.main_frame, bd=1, bg="white smoke")
        self.toolbar.grid(row=0, column=0, columnspan=2, sticky="nsew")
        # Two rows keep every control visible on narrow windows
        self.toolbar_top = tk.Frame(self.toolbar, bg="white smoke")
        self.toolbar_top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4, 0))
        self.toolbar_bottom = tk.Frame(self.toolbar, bg="white smoke")
        self.toolbar_bottom.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 4))

        # Create the source text input
        self.source_text = tk.Text(
            self.main_frame,
            wrap="word",
            font=("Arial", self.text_size()),
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
        self.source_text.tag_configure("rtl", justify="right")
        self.source_text.bind("<KeyRelease>", self.keep_source_direction)

        # Create the headers above the text areas
        self.source_header = tk.Label(
            self.main_frame, text="Source", anchor=tk.W, padx=7, bg="white smoke"
        )
        self.source_header.grid(row=1, column=0, sticky="nsew")
        self.target_header_frame = tk.Frame(self.main_frame, bg="white smoke")
        self.target_header_frame.grid(row=1, column=1, sticky="nsew")
        self.target_header = tk.Label(
            self.target_header_frame, text="Translation", anchor=tk.W, padx=7, bg="white smoke"
        )
        self.target_header.pack(side=tk.LEFT)
        self.button_copy = tk.Button(
            self.target_header_frame,
            text="Copy",
            highlightbackground="white smoke",
            command=self.copy_all_translation,
        )
        self.button_copy.pack(side=tk.RIGHT, padx=(2, 6))

        # Create the target text input
        self.target_text = tk.Text(
            self.main_frame,
            wrap="word",
            font=("Arial", self.text_size()),
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
        # Clicks and selections make Tk re-flow a right-to-left line, so they are blocked in that view
        self.target_locked = False
        for sequence in ("<Button-1>", "<B1-Motion>", "<Double-Button-1>", "<Triple-Button-1>",
                         "<Shift-Button-1>", "<ButtonRelease-1>", "<<SelectAll>>"):
            self.target_text.bind(sequence, self.block_if_locked)

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
            self.toolbar_top,
            text="CTranslate2 Model",
            width=20,
            highlightbackground="white smoke",
            command=self.open_model,
        )
        self.button_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the select SentencePiece model button
        self.button_sp_model = tk.Button(
            self.toolbar_top,
            text="SentencePiece Model",
            width=20,
            highlightbackground="white smoke",
            command=self.open_sp_model,
        )
        self.button_sp_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the translate button
        self.button_translate = tk.Button(
            self.toolbar_top,
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
        self.labelframe = tk.LabelFrame(self.toolbar_top, bd=0, bg="white smoke")
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

        self.source_label = tk.Label(
            self.toolbar_bottom,
            text="Source language:",
            bg="white smoke",
        )
        self.source_label.pack(side=tk.LEFT, padx=2, pady=2)

        # Create the source language selection combobox
        self.source_combobox = ttk.Combobox(
            self.toolbar_bottom, values=[AUTO_DETECT], state="disabled", width=20
        )
        self.source_combobox.set(AUTO_DETECT)
        self.source_combobox.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.BOTH)
        self.source_combobox.bind("<<ComboboxSelected>>", self.on_source_selected)

        self.target_label = tk.Label(
            self.toolbar_bottom,
            text="Target language:",
            bg="white smoke",
        )
        self.target_label.pack(side=tk.LEFT, padx=(10, 2), pady=2)

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
        self.flores_to_fasttext = {v: k for k, v in self.fasttext_to_flores.items()}
        self.language_codes = {}

        # Create the target language selection combobox
        self.combobox = ttk.Combobox(
            self.toolbar_bottom, values=["Load a model first"], state="disabled", width=20
        )
        self.combobox.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.BOTH)
        self.combobox.current(0)
        self.combobox.bind("<<ComboboxSelected>>", self.on_target_selected)
        self.balloon.bind(
            self.combobox,
            "For the multilingual models (M2M-100 and NLLB-200), select the target language",
        )
        self.balloon.bind(
            self.source_combobox,
            "For the multilingual models, select the source language, or keep Auto detect",
        )

    def createMenu(self):
        # Create the menu bar and add the menu items
        self.menubar = tk.Menu(self.window)
        self.filemenu = tk.Menu(self.menubar, tearoff=0)
        self.filemenu.add_command(label="Open File...", command=self.open_file)
        self.filemenu.add_command(
            label="Reopen File with Encoding...", command=self.reopen_with_encoding
        )
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
            label="Remember Last Model and Language",
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

    def confirm_long_lines(self, text):
        """Ask before showing a very long line, which can freeze the text area for minutes"""
        longest = max((len(line) for line in text.splitlines()), default=0)
        if longest <= LONG_LINE_CHARS:
            return True
        return askyesno(
            "Very long line",
            "The text has a line of " + format(longest, ",") + " characters. "
            "Showing it can take minutes, and the window may not respond meanwhile. "
            "Adding line breaks, for example after sentences, makes it much faster.\n\n"
            "Show it anyway?",
        )

    def paste(self):
        text = self.source_text.clipboard_get()
        if not self.confirm_long_lines(text):
            return
        self.source_text.insert(tk.INSERT, text)

        self.line_count = len(self.source_text.get(1.0, tk.END).splitlines())
        self.statusbar.config(text="Lines: " + str(self.line_count))
        self.update_source_direction()

    def block_if_locked(self, event=None):
        return "break" if self.target_locked else None

    def copy_all_translation(self):
        if self.translation == "":
            self.statusbar.config(text="Nothing to copy.")
            return
        self.target_text.clipboard_clear()
        self.target_text.clipboard_append(self.translation)
        self.statusbar.config(text="Translation copied to the clipboard.")

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
        file_name = askopenfilename(filetypes=[("Text Files", "*.txt")])
        if file_name:
            self.read_file(file_name)

    def reopen_with_encoding(self):
        if self.file_name == "":
            showinfo("Reopen File with Encoding", "Please open a file first.")
            return
        encoding = askstring(
            "Reopen File with Encoding",
            "Encoding of the file, e.g. utf-8, utf-16, latin-1, cp1252:",
        )
        if encoding:
            self.read_file(self.file_name, encoding.strip())

    def read_file(self, file_name, encoding=None):
        """Show a text file in the source pane; the encoding is guessed unless it is given"""
        try:
            if encoding:
                codecs.lookup(encoding)
                with open(file_name, encoding=encoding) as text_file:
                    text = text_file.read()
            else:
                try:
                    with open(file_name, encoding="utf-8-sig") as text_file:
                        text = text_file.read()
                    encoding = "utf-8"
                except UnicodeDecodeError:
                    match = from_path(file_name).best()
                    if match is None:
                        encoding = "cp1252"
                        with open(file_name, encoding=encoding, errors="replace") as text_file:
                            text = text_file.read()
                    else:
                        text, encoding = str(match), match.encoding
        except (LookupError, UnicodeError, OSError) as error:
            showerror("Cannot open the file", str(error))
            return

        if not self.confirm_long_lines(text):
            return
        self.file_name = file_name
        self.source_text.delete(1.0, tk.END)
        self.source_text.insert(tk.INSERT, text)
        self.update_source_direction()

        self.line_count = len(self.source_text.get(1.0, tk.END).splitlines())
        lines_count_str = "Lines: " + str(self.line_count)
        words_count_str = "Words: " + str(len(text.split()))
        self.statusbar.config(
            text=lines_count_str + " | " + words_count_str + " | Encoding: " + encoding
        )

    def save_file(self):
        data = strip_bidi_marks(self.target_text.get(1.0, tk.END))
        if data.strip() == "":
            showinfo("", "Nothing to save!")
            return
        self.file = asksaveasfilename(
            filetypes=[("Text Files", "*.txt")], defaultextension=".txt"
        )
        if self.file:
            with open(self.file, "w", encoding="utf-8") as output:
                output.write(data.rstrip() + "\n")

    def clear(self):
        self.source_text.delete(1.0, tk.END)
        self.set_source_direction(False)
        self.source_header.config(text="Source")
        self.show_translation("")
        self.statusbar.config(text="")

    def set_source_direction(self, rtl):
        self.source_rtl = rtl
        self.source_text.tag_remove("rtl", "1.0", tk.END)
        if rtl:
            self.source_text.tag_add("rtl", "1.0", tk.END)

    def keep_source_direction(self, event=None):
        # Lines typed after the first one need the alignment too
        if self.source_rtl:
            if self.source_combobox.get() == AUTO_DETECT and self.source_text.get(1.0, tk.END).strip() == "":
                self.set_source_direction(False)
            else:
                self.source_text.tag_add("rtl", "1.0", tk.END)

    def on_source_selected(self, event=None):
        if self.source_combobox.get() == AUTO_DETECT:
            self.update_source_direction()
        else:
            prefix = self.language_codes[self.source_combobox.get()]
            self.set_source_direction(is_rtl_target(self.model_type, prefix))

    def update_source_direction(self):
        """Align the source pane from the detected language, when the language is not selected"""
        text = self.source_text.get(1.0, tk.END)
        if self.source_combobox.get() != AUTO_DETECT:
            return
        if len(text.strip()) > 1:
            codes = self.detect_language(text)
            self.set_source_direction(bool(codes) and is_rtl_language(codes[0]))
        else:
            self.set_source_direction(False)

    def show_info(self):
        showinfo(
            "About",
            "DesktopTranslator (0.3.1)\n\nDeveloped by: Yasmin Moslem\nwww.machinetranslation.io",
        )

    def store_settings(self):
        self.settings["remember_model_paths"] = self.remember_paths.get()
        self.settings["join_lines"] = self.join_lines_option.get()
        self.settings["rtl_view"] = self.rtl_view_option.get()
        if self.model_type in self.language_lists and self.combobox.get() in self.language_codes:
            self.target_memory[self.model_type] = self.combobox.get()
        if self.remember_paths.get():
            self.settings["ct2_model"] = self.model.get()
            self.settings["sp_model"] = self.sp_model.get()
            self.settings["target_language"] = self.target_memory
        else:
            self.settings.pop("ct2_model", None)
            self.settings.pop("sp_model", None)
            self.settings.pop("target_language", None)
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
                    text="Last used model: "
                    + os.path.basename(self.model.get())
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
            self.combobox.config(values=sorted(self.language_codes), state="readonly")
            self.source_combobox.config(values=[AUTO_DETECT] + sorted(self.language_codes), state="readonly")
            if previous_type != self.model_type:
                remembered = self.target_memory.get(self.model_type, "") if self.remember_paths.get() else ""
                self.combobox.set(remembered if remembered in self.language_codes else TARGET_PLACEHOLDER)
                self.source_combobox.set(AUTO_DETECT)
        else:
            self.language_codes = {}
            self.combobox.config(values=["Not needed"], state="disabled")
            self.combobox.set("Not needed")
            self.source_combobox.config(values=[AUTO_DETECT], state="disabled")
            self.source_combobox.set(AUTO_DETECT)

    def on_target_selected(self, event=None):
        self.store_settings()

    def show_model_info(self):
        # The SentencePiece model belongs to the CTranslate2 model, so only one name is shown
        self.model_info.config(text="Model: " + os.path.basename(self.model.get()))

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
        if self.lid_model is None:
            dir_path = os.path.dirname(os.path.realpath(__file__))
            self.lid_model = fasttext.load_model(os.path.join(dir_path, "utils", "lid.176.ftz"))
        model = self.lid_model
        text = text[:200].lower() if len(text) > 200 else text.lower()
        # model.predict() fails with NumPy 2, so use the underlying call
        prediction = model.f.predict(text.replace("\n", " "), 2, 0.0, "strict")
        # Text with no letters, such as numbers, can give fewer than two languages, or none
        return [label[9:] for _, label in prediction]

    def find_source_language(self, text):
        """Return the source language code and the prefix token the model needs

        The language is the one selected, or else the one detected from the text."""
        selected = self.source_combobox.get()
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
            if lang_option not in self.language_codes:
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
            showerror(
                "Source language",
                "The source language is not supported or not recognized. Add more text, or select the source language.",
            )
            return
        if self.source_combobox.get() == AUTO_DETECT:
            self.source_header.config(text="Source (detected: " + self.source_lang_code + ")")
            self.set_source_direction(is_rtl_language(self.source_lang_code))
        else:
            self.source_header.config(text="Source")
            self.set_source_direction(is_rtl_target(self.model_type, self.src_prefix))

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
        self.target_locked = False
        self.target_text.config(state=tk.NORMAL, cursor="xterm")
        self.target_text.delete(1.0, tk.END)
        if text == "":
            self.target_text.config(insertwidth=2)
        elif self.target_is_rtl and self.rtl_view_option.get():
            self.target_text.insert(tk.END, add_rtl_marks(text) + "\n", "rtl")
            # Tk splits a line at the cursor or at a selection and changes its direction,
            # so the pane is read-only, with no cursor, and clicks are blocked
            self.target_locked = True
            self.target_text.config(state=tk.DISABLED, insertwidth=0, cursor="arrow")
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
                    status = "Translating... " + str(percent) + "%"
                    elapsed = (datetime.now() - self.start).total_seconds()
                    if payload > 0 and elapsed > 3:
                        remaining = elapsed * (self.total_words - payload) / payload
                        status += " (about " + format_duration(remaining) + " left)"
                    self.statusbar.config(text=status)
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
