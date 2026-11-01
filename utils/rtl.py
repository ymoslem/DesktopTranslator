import re

# Languages of the M2M-100 model that are written from right to left
M2M_RTL_CODES = {"__ar__", "__fa__", "__ur__", "__he__", "__ps__", "__sd__", "__yi__"}

# Scripts of the NLLB-200 language codes, e.g. arb_Arab, that are written from right to left
NLLB_RTL_SCRIPTS = {"Arab", "Hebr"}

RLE = "‫"  # right-to-left embedding
PDF = "‬"  # pop directional formatting
BIDI_MARKS = re.compile("[‎‏‪-‮]")


def is_rtl_target(model_type, target_lang_code):
    """Tell if a target language is written from right to left

    Args:
        model_type (str): "m2m", "nllb", or any other value for models without language codes
        target_lang_code (str): Target language code of the model, e.g. "__ar__" or "arb_Arab"

    Returns:
        is_rtl (bool): True for right-to-left languages
    """
    if model_type == "m2m":
        return target_lang_code in M2M_RTL_CODES
    if model_type == "nllb":
        return target_lang_code.split("_")[-1] in NLLB_RTL_SCRIPTS
    return False


def add_rtl_marks(text):
    """Wrap each line in direction marks, so the punctuation shows on the correct side"""
    return "\n".join(RLE + line + PDF if line.strip() else line for line in text.split("\n"))


def strip_bidi_marks(text):
    """Remove the direction marks, e.g. before saving or copying the text"""
    return BIDI_MARKS.sub("", text)
