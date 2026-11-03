# Changelog


## v0.4.0

### Changed

- A new interface built with Qt (PySide6), replacing Tkinter. The Tkinter interface stays available in the `tk` branch
- Right-to-left text, such as Arabic, is edited and selected right to left, and each paragraph follows its own direction
- The app follows the dark mode of the system, and the text size can be changed in the View menu
- The model is opened with one folder selection; its SentencePiece model is found automatically
- Translation quality (Fast, Balanced, Accurate) and the other options are in Edit > Preferences
- The translation appears as it is made, and Cancel keeps the part that is done
- The source header shows the detected language and the number of words
- A sentence that repeats in a text is translated once, so it is translated the same way everywhere
- The Windows installer and the macOS app have a new icon

### Added

- File > Translate Document translates a plain text file into another file in the background, with progress, time left, and Cancel. The translated part is kept if you cancel
- Texts over 20,000 words are not translated in the window; the app offers File > Translate Document instead
- A warning when the computer may not have enough memory free for the model
- A message when a PDF or Word file is opened, because only plain text files are supported
- Search in the language lists, and a button to swap the source and target languages
- Dropping a text file on the source pane opens it


## v0.3.2

### Added

- Translate > Avoid Repeated Words, which turns on a repetition penalty of 1.2

### Changed

- The repetition penalty is off by default, because the translations scored higher without it in tests with NLLB-200, M2M-100, and the French-to-English model (`tests/repetition_penalty_eval.py`)


## v0.3.1

### Changed

- The language selectors are on a second toolbar row, so every control fits narrow windows
- Added space around the toolbar and the Copy button

### Fixed

- Translated lines no longer end with a space


## v0.3.0

### Added

- Support for NLLB-200 models (NLLB Team et al., 2022), with packages of the 600M and 1.3B models and their SentencePiece model
- Translation runs in the background, with a progress bar and a Cancel button
- Right-to-left view for right-to-left target languages, with an option to switch it off
- Copy button above the translation
- Source language selector, "Auto detect" by default, for M2M-100 and NLLB-200; right-to-left source text is right-aligned
- File > Reopen File with Encoding, and the encoding of an opened file in the status bar
- The last target language is remembered for each multilingual model type
- Estimated time left while translating
- A question before showing a line longer than 100,000 characters, which the text area displays very slowly
- Source and translation headers, and the loaded model name in the status bar
- Model selection dialogs open in the folder of the last selected model
- Model downloads moved to the Help menu

### Changed

- The target language selector is shared by M2M-100 and NLLB-200; it asks for a language, and is disabled with "Not needed" for other models
- NLLB-200 language varieties are listed together, e.g. "Arabic (Modern Standard)"
- Replaced the progress pop-up window and the `tqdm` dependency

### Fixed

- Detection of M2M-100 models whose vocabulary is stored as `shared_vocabulary.json`
- Opening a text file tries UTF-8 first, instead of guessing the encoding
- Cancelling the Save dialog no longer raises an error
- The language detection model is loaded once
- Language detection no longer fails on text without letters, such as numbers


## v0.2.6

### Changed

- Status bar shows the remembered model paths at startup
- Clearer titles and menu label for selecting the CTranslate2 model folder

### Fixed

- Extra windows opening in the stand-alone app when translating


## v0.2.5

### Added

- Windows and macOS installers, built with GitHub Actions

### Fixed

- Installing dependencies on Windows, Linux, and Intel Macs


## v0.2.4

### Added

- Option to remember the CTranslate2 and SentencePiece model paths
- Option to join single line breaks within paragraphs

### Fixed

- Stray token at the start of translations for models without a language prefix


## v0.2.3

### Changed

- Updated dependencies, including CTranslate2 4.8.4 and NumPy 2.x; Python 3.11 or later is required

### Fixed

- Source language detection with NumPy 2
- Deprecated CTranslate2 result access
- Broken model download links


## v0.2.2 (2023-01-18, pre-release)

### Added

- NLLB-200 600M CTranslate2 model file (replaced by a package with its SentencePiece model in v0.3.0)


## v0.2.1

### Added

- Source language detection
- macOS executable app

### Fixed

- Source language code as source prefix token
- Sentence splitting for non-Latin languages


## v0.2.0 (2022-02-07)

### Added

- Support for `M2M-100 models` (Fan et al., 2020)

### Fixed

- Save translation as UTF-8
- Respect paragraph format


## v0.1.0 (2022-01-04)

- First release of `DesktopTranslator`
