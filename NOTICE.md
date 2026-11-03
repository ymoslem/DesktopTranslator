# Notices

DesktopTranslator is released under the [MIT License](LICENSE). It uses the software, the language identification model, and the translation models below, which have their own licenses.

## Software

The versions are in [requirements.txt](requirements.txt). The licenses are those listed on PyPI in November 2026.

| Component | License |
|---|---|
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT |
| [SentencePiece](https://github.com/google/sentencepiece) | Apache-2.0 |
| [fastText](https://github.com/facebookresearch/fastText) (as the fasttext-wheel package) | MIT |
| [NumPy](https://numpy.org) | BSD-3-Clause |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | MIT |
| [pysbd](https://github.com/nipunsadvilkar/pySBD) | MIT |
| [sentence-splitter](https://github.com/berkmancenter/mediacloud-sentence-splitter) | LGPL-3.0 |
| [indic-nlp-library](https://github.com/anoopkunchukuttan/indic_nlp_library) | MIT |
| [Qt for Python (PySide6)](https://pyside.org) | LGPL-3.0 |
| [pandas](https://pandas.pydata.org) | BSD-3-Clause |

[PyInstaller](https://pyinstaller.org), which builds the installers, is released under the GPL-2.0-or-later with a special exception that allows the programs it builds to use any license.

### The LGPL libraries

sentence-splitter and Qt for Python (PySide6, with Qt) are released under the [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html). The installers are folders of files, and these libraries are separate files in them, so you can replace them with a modified version of your own. Their source code is at the links in the table, and the source of Qt is at [code.qt.io](https://code.qt.io).

## Language identification model

`utils/lid.176.ftz` is the language identification model of fastText, distributed under the [Creative Commons Attribution-Share-Alike License 3.0](https://creativecommons.org/licenses/by-sa/3.0/). fastText says the models were trained on data from Wikipedia, Tatoeba, and SETimes, used under CC-BY-SA. If you use the model, please cite
[Bag of Tricks for Efficient Text Classification](https://arxiv.org/abs/1607.01759) and [FastText.zip: Compressing text classification models](https://arxiv.org/abs/1612.03651) (Joulin et al.).

## Translation models

DesktopTranslator does not include a translation model. The models that it links to have these licenses, according to their model cards on Hugging Face.

| Model | License |
|---|---|
| [NLLB-200](https://arxiv.org/abs/2207.04672) by Meta (distilled 600M, distilled 1.3B, 3.3B) | [CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), which does not allow commercial use |
| [M2M-100](https://arxiv.org/abs/2010.11125) by Meta (418M, 1.2B) | MIT |
| [OPUS-MT](https://github.com/Helsinki-NLP/Tatoeba-Challenge) by Helsinki-NLP | for example Apache-2.0 for opus-mt-en-fr; see the model card of each model |

The converted NLLB-200 and M2M-100 models in the releases of this repository are the original models changed to the CTranslate2 format with int8 quantization. Check the license of a model before you use it for anything other than personal and research use.
