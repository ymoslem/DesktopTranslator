import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename, askopenfile, askdirectory, asksaveasfile
from tkinter.messagebox import showinfo, showerror
import Pmw
from tqdm.tk import tqdm
from numpy import array, array_split
from datetime import datetime
import ctranslate2
import sentencepiece as spm
from charset_normalizer import from_path
import os
import webbrowser
from languages import langs


class TranslatorGUI:
    def __init__(self, window):
        self.window = window
        self.window.title("DesktopTranslator")

        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        self.model = tk.StringVar(self.main_frame)
        self.sp_model = tk.StringVar(self.main_frame)
        self.beam_size = tk.IntVar(self.main_frame)
        self.beam_size.set(3)

        self.createWidgets()
        self.createMenu()

    def createWidgets(self):
        # Create the toolbar
        self.toolbar = tk.Frame(self.main_frame, borderwidth=1, background="white smoke")
        self.toolbar.grid(row=0, column=0, columnspan=2, sticky="nsew")

        # Create the source text input
        self.source_text = tk.Text(self.main_frame, borderwidth=2, relief=tk.SUNKEN, padx=5, pady=5, font=("Arial", 14), undo=True, highlightcolor="white smoke", highlightbackground="white smoke")
        self.source_text.grid(row=1, column=0, sticky="nsew")
        self.source_text.focus_set()

        # Create the target text input
        self.target_text = tk.Text(self.main_frame, borderwidth=2, relief=tk.SUNKEN, padx=5, pady=5, font=("Arial", 14), undo=True, highlightcolor="white smoke", highlightbackground="white smoke")
        self.target_text.grid(row=1, column=1, sticky="nsew")

        # Create the statusbar
        self.statusbar = tk.Label(self.main_frame, borderwidth=1, relief=tk.SUNKEN, padx=5, pady=5, anchor=tk.W, bg="white smoke", fg="black", text="Select a model and enter text to translate!")
        self.statusbar.grid(row=2, column=0, columnspan=2, sticky="nsew")

        # Create the select CTranslate2 model button
        self.button_model = tk.Button(self.toolbar, text="CTranslate2 Model", width=20, highlightbackground="white smoke", command=self.open_model)
        self.button_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)        

        # Create the select SentencePiece model button
        self.button_sp_model = tk.Button(self.toolbar, text="SentencePiece Model", width=20, highlightbackground="white smoke", command=self.open_sp_model)
        self.button_sp_model.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)        

        # Create the translate button
        self.button_translate = tk.Button(self.toolbar, text="Translate", width=20, highlightbackground="white smoke", command=self.translate_input)
        self.button_translate.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.X)

        # Create the balloon object and bind it to the buttons
        Pmw.initialise(self.window)
        self.balloon = Pmw.Balloon(self.window)
        self.balloon.bind(self.button_model, "Select CTranslate2 model direcotry")
        self.balloon.bind(self.button_sp_model, "Select a SentencePiece source model")
        self.balloon.bind(self.button_translate, "Translate the source text")
        # Change the background colour of the balloon
        self.lbl = self.balloon.component("label")
        self.lbl.config(background="white", padx=1, pady=1)

        # Create the beam_size label and radio buttons
        self.labelframe = tk.LabelFrame(self.toolbar, borderwidth=0,  background="white smoke")
        self.labelframe.pack(side=tk.LEFT, padx=10)

        self.beam_size_label = tk.Label(self.labelframe, background="white smoke", text="Beam Size:")
        self.beam_size_label.pack(side=tk.LEFT, ipady=5)

        values = {"2":2, "3":3, "5":5}

        for (text, value) in values.items():
            tk.Radiobutton(self.labelframe, text=text, variable=self.beam_size, value=value,  background="white smoke").pack(side=tk.LEFT, ipady=2)

        # M2M widgets

        # Create a vertical separator
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', selectbackground="white smoke", selectforeground="black")

        separator = ttk.Separator(self.toolbar, orient='vertical', style='style.TSeparator')
        separator.pack(side=tk.LEFT, fill=tk.Y)

        self.m2m_label = tk.Label(self.toolbar, background="white smoke", text="M2M-100:")
        self.m2m_label.pack(side=tk.LEFT, padx=2, pady=10)

        languages = list(langs.keys())
        self.combobox = ttk.Combobox(self.toolbar, values=languages, style="TCombobox")
        self.combobox.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.BOTH)
        self.combobox.current(0)
        self.balloon.bind(self.combobox, "If you use M2M-100 model, select the language you want to translate to")

        # Create the download button
        self.download_label = tk.Label(self.toolbar, background="white smoke", text="Download:")
        self.download_label.pack(side=tk.LEFT, padx=2, pady=2)

        self.download_button_418m = tk.Button(self.toolbar, highlightbackground="white smoke", text="418M", cursor="hand2", command=self.download_m2m_418m)
        self.download_button_418m.pack(side=tk.LEFT, padx=2, pady=2)
        self.balloon.bind(self.download_button_418m, "Download M2M-100 418M-parameter model (faster, but less accurate)")

        self.download_button_12b = tk.Button(self.toolbar, highlightbackground="white smoke", text="1.2B", cursor="hand2", command=self.download_m2m_12b)
        self.download_button_12b.pack(side=tk.LEFT, padx=2, pady=2)
        self.balloon.bind(self.download_button_12b, "Download M2M-100 1.2B-parameter model (slower, but more accurate)")


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
        self.translatemenu.add_command(label="Select CTranslate2 Model", command=self.open_model)
        self.translatemenu.add_command(label="Select SentencePiece Model", command=self.open_sp_model)
        self.menubar.add_cascade(label="Translate", menu=self.translatemenu)

        # Create the Help menu and add the menu items
        self.helpmenu = tk.Menu(self.menubar, tearoff=0)
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

    def select_all(self):
        self.source_text.tag_add(tk.SEL, "1.0", tk.END)
        self.source_text.mark_set(tk.INSERT, "1.0")
        self.source_text.see(tk.INSERT)

    def open_file(self):
        self.file_name = askopenfilename(filetypes=[('Text Files', '*.txt')])
        if self.file_name:
            self.source_text.delete(1.0, tk.END)

            self.source_file_text = str(from_path(self.file_name).best())
            self.source_text.insert(tk.INSERT, self.source_file_text)

            self.line_count = len(self.source_text.get(1.0, tk.END).splitlines())
            self.statusbar.config(text="Lines: " + str(self.line_count) + " | Words: " + str(len(self.source_file_text.split())))

    def save_file(self):
        self.file = asksaveasfile(mode='w', defaultextension='.txt')
        if self.file is not None:
            self.data = self.target_text.get(1.0, tk.END)
            if len(self.data) > 0:
                self.file.write(self.data)
                self.file.close()
            else:
                showinfo("", "Nothing to save!")

    def clear(self):
        self.source_text.delete(1.0, tk.END)
        self.target_text.delete(1.0, tk.END)
        self.statusbar.config(text="")

    def show_info(self):
        showinfo("About", "DesktopTranslator\n\n\nDeveloped by: Yasmin Moslem\nwww.machinetranslation.io")

    def open_model(self):
        self.toolbar.update()  # for Mac
        self.model_dir = askdirectory()
        if self.model_dir != "":
            if os.path.exists(os.path.join(self.model_dir, "model.bin")):
                self.model.set(self.model_dir)
                self.statusbar.config(text="CT2 Model path: " + self.model_dir)

                self.cpu_num = os.cpu_count()
                self.inter_threads = 2
                self.intra_threads = int(self.cpu_num/2)

                self.translator = ctranslate2.Translator(self.model_dir, device="cpu", inter_threads=self.inter_threads, intra_threads=self.intra_threads)
            else:
                showerror("Invalid CTranslate2 model", "Please make sure you select the direcotry of a valid CTranslate2 model!")

    def open_sp_model(self):
        self.toolbar.update()  # for Mac
        self.model_file = askopenfile(filetypes=[('SentencePiece Model', '*.model')])
        if self.model_file:
            self.sp_model.set(self.model_file.name)
            self.statusbar.config(text="SP Model path: " + self.model_file.name)
            self.sp_source_model = spm.SentencePieceProcessor(self.model_file.name)

    def download_m2m_418m(self):
        self.toolbar.update()  # for Mac
        webbrowser.open_new("https://pretrained-nmt-models.s3.us-west-2.amazonaws.com/CTranslate2/m2m100/m2m100_ct2_418m.zip")

    def download_m2m_12b(self):
        self.toolbar.update()  # for Mac
        webbrowser.open_new("https://pretrained-nmt-models.s3.us-west-2.amazonaws.com/CTranslate2/m2m100/m2m100_ct2_12b.zip")

    def translate_input(self):
        self.target_text.delete(1.0, tk.END)
        self.source_text_string = self.source_text.get(1.0, tk.END)
        
        lang_option = self.combobox.get()
        lang_code = langs.get(lang_option)


        if len(self.source_text_string) > 1:
            self.statusbar.config(text="Translating...")
            self.source_sents = self.source_text_string.splitlines()

            self.start = datetime.now()
            max_batch_size = 2048
            beam_size_val = self.beam_size.get()

            if self.model.get() != "" and self.sp_model.get() != "":
                self.n_splits = round((len(self.source_sents)/16)+0.5)
                self.splits = array_split(array(self.source_sents), self.n_splits)
                self.splits = [split.tolist() for split in self.splits]

                with tqdm(total=len(self.source_text_string.split()), desc="Translation progress (words)", unit=" split", disable=(len(self.splits)<2), leave=False) as tq:
                    tq.refresh()
                    self.main_frame.update()

                    for split in self.splits:
                        if lang_code != "":
                            lang_prefix = [[lang_code]] * len(split)
                            start_pos = 7
                            max_batch_size = 1024
                        else:
                            lang_prefix = None

                        source_sents_tok = self.sp_source_model.encode(split, out_type=str)
                        translations_tok = self.translator.translate_batch(
                                                                        source=source_sents_tok,
                                                                        beam_size=beam_size_val,
                                                                        batch_type="tokens",
                                                                        max_batch_size=max_batch_size,
                                                                        replace_unknowns=True,
                                                                        repetition_penalty=1.2,
                                                                        target_prefix=lang_prefix)
                        
                        translations_so_far = [" ".join(translation[0]["tokens"]).replace(" ", "").replace("▁", " ")[start_pos:].strip() for translation in translations_tok]

                        self.target_text.insert(tk.END, "\n".join(translations_so_far)+"\n")

                        tq.update(len(" ".join(split).split()))
                        tq.refresh()
                        self.main_frame.update()

                    elapsed = str(datetime.now() - self.start)
                    self.statusbar.config(text="Congratulations! Translation completed. Time elapsed: " + elapsed)

            else:
                showinfo("No model selected", "Please select both CTranslate2 and SentencePiece models, and enter text to translate!")


# Create the root window
if __name__ == "__main__":
    window = tk.Tk()
    window.resizable(True, True)
    window.state('zoomed')

    # Get the current screen width and height (optional, for Mac)
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    window.geometry(str(screen_width)+'x'+str(screen_height))

    app = TranslatorGUI(window)
    window.mainloop()
