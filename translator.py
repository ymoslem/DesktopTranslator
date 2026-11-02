import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename, askopenfile, askdirectory
from tkinter.filedialog import asksaveasfilename
from tkinter.messagebox import showinfo, showerror, askyesno
from tkinter.simpledialog import askstring
import Pmw
from datetime import datetime
import multiprocessing
import os
import queue
import threading
import webbrowser
from engine import (
    AUTO_DETECT,
    LONG_LINE_CHARS,
    Engine,
    EngineError,
    Preferences,
    REPETITION_PENALTY,
    format_duration,
    longest_line,
    read_text_file,
    write_text_file,
)
from utils.paragraph_splitter import paragraph_detokenizer
from utils.rtl import is_rtl_target, is_rtl_language, add_rtl_marks, strip_bidi_marks


TARGET_PLACEHOLDER = "Select a language..."


class TranslatorGUI:
    def __init__(self, window):
        self.window = window
        self.window.createcommand('tkAboutDialog', self.show_info)  # for macOS

        self.engine = Engine()
        self.preferences = Preferences()

        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(2, weight=1)

        self.model = tk.StringVar(self.main_frame)
        self.sp_model = tk.StringVar(self.main_frame)
        self.beam_size = tk.IntVar(self.main_frame)
        self.beam_size.set(3)

        self.remember_paths = tk.BooleanVar(
            self.main_frame, value=self.preferences.get("remember_model_paths", True)
        )
        self.join_lines_option = tk.BooleanVar(
            self.main_frame, value=self.preferences.get("join_lines", False)
        )
        self.rtl_view_option = tk.BooleanVar(
            self.main_frame, value=self.preferences.get("rtl_view", True)
        )
        self.repetition_option = tk.BooleanVar(
            self.main_frame, value=self.preferences.get("repetition_penalty", 1.0) > 1.0
        )
        self.translation = ""  # the translation without direction marks
        self.source_rtl = False
        self.file_name = ""
        self.target_is_rtl = False
        self.worker = None
        self.cancel_event = threading.Event()
        self.messages = queue.Queue()

        self.createWidgets()
        self.createMenu()
        self.restore_model_paths()

    # What the engine knows
    @property
    def translator(self):
        return self.engine.translator

    @property
    def sp_source_model(self):
        return self.engine.sp_model

    @property
    def model_type(self):
        return self.engine.model_type

    @property
    def model_vocabulary(self):
        return self.engine.vocabulary

    @property
    def language_codes(self):
        return self.engine.language_codes

    @property
    def language_lists(self):
        return self.engine.language_lists

    @property
    def lid_model(self):
        return self.engine.lid_model

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
            label="Avoid Repeated Words",
            variable=self.repetition_option,
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
        longest = longest_line(text)
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
            text, encoding = read_text_file(file_name, encoding)
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
            write_text_file(self.file, data)

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
            codes = self.engine.detect_language(text)
            self.set_source_direction(bool(codes) and is_rtl_language(codes[0]))
        else:
            self.set_source_direction(False)

    def show_info(self):
        showinfo(
            "About",
            "DesktopTranslator (0.3.2)\n\nDeveloped by: Yasmin Moslem\nwww.machinetranslation.io",
        )

    def store_settings(self):
        self.preferences.save(
            remember=self.remember_paths.get(),
            join_lines_option=self.join_lines_option.get(),
            rtl_view=self.rtl_view_option.get(),
            repetition_penalty=self.repetition_penalty(),
            ct2_model=self.model.get(),
            sp_model=self.sp_model.get(),
            model_type=self.model_type if self.model_type in self.language_lists else None,
            target=self.combobox.get() if self.combobox.get() in self.language_codes else None,
        )

    def repetition_penalty(self):
        return REPETITION_PENALTY if self.repetition_option.get() else 1.0

    def restore_model_paths(self):
        if self.remember_paths.get():
            ct2_model = self.preferences.get("ct2_model", "")
            sp_model = self.preferences.get("sp_model", "")
            if self.engine.is_model(ct2_model):
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
        """Read the kind of the model, and adapt the language selectors to it"""
        self.show_model_type(self.engine.inspect_model(model_dir))

    def show_model_type(self, changed):
        """Adapt the language selectors to the kind of model"""
        if self.model_type in self.language_lists:
            self.combobox.config(values=sorted(self.language_codes), state="readonly")
            self.source_combobox.config(values=[AUTO_DETECT] + sorted(self.language_codes), state="readonly")
            if changed:
                remembered = self.preferences.remembered_target(self.model_type, self.remember_paths.get())
                self.combobox.set(remembered if remembered in self.language_codes else TARGET_PLACEHOLDER)
                self.source_combobox.set(AUTO_DETECT)
        else:
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
        try:
            changed = self.engine.load_model(model_dir)
        except EngineError as error:
            showerror(error.title, error.message)
            return False

        self.model_dir = model_dir
        self.show_model_type(changed)
        self.model.set(model_dir)
        self.statusbar.config(text="CT2 Model path: " + model_dir)
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
        self.engine.load_sp_model(sp_model_path)
        self.sp_model.set(sp_model_path)
        self.statusbar.config(text="SP Model path: " + sp_model_path)
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
        try:
            self.target_lang_code = self.engine.target_language(self.combobox.get())
        except EngineError as error:
            showerror(error.title, error.message)
            return

        self.target_is_rtl = is_rtl_target(self.model_type, self.target_lang_code)

        # Source language
        self.source_lang_code, self.src_prefix = self.engine.source_language(
            self.source_text_string, self.source_combobox.get()
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

        self.source_sents, self.breaks, self.batches, self.total_words = self.engine.split(
            self.source_text_string, self.source_lang_code, self.join_lines_option.get()
        )

        self.start = datetime.now()

        self.progress.config(maximum=self.total_words, value=0)
        self.progress.pack(side=tk.RIGHT, padx=5)
        self.statusbar.config(text="Translating...")
        self.button_translate.config(text="Cancel", command=self.cancel_translation)
        self.cancel_event.clear()

        self.worker = threading.Thread(
            target=self.run_translation,
            args=(self.batches, self.beam_size.get(), self.target_lang_code, self.src_prefix, self.repetition_penalty()),
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

    def run_translation(self, batches, beam_size, target_lang_code, src_prefix, repetition_penalty):
        # Runs in a worker thread, so it must not touch the interface; it reports through a queue
        try:
            translations = self.engine.translate(
                batches,
                beam_size,
                target_lang_code,
                src_prefix,
                is_cancelled=self.cancel_event.is_set,
                on_progress=lambda words_done: self.messages.put(("progress", words_done)),
                repetition_penalty=repetition_penalty,
            )
            self.messages.put(("cancelled", None) if translations is None else ("done", translations))
        except Exception as error:
            self.messages.put(("error", error))

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
