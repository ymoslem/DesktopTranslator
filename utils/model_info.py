import json
import os


def read_vocabulary(model_dir):
    """Read the shared vocabulary of a CTranslate2 model

    Args:
        model_dir (str): Directory of the CTranslate2 model

    Returns:
        vocabulary (set): Tokens of the shared vocabulary, empty if the model has none
    """
    json_path = os.path.join(model_dir, "shared_vocabulary.json")
    txt_path = os.path.join(model_dir, "shared_vocabulary.txt")

    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as vocab_file:
            return set(json.load(vocab_file))
    if os.path.exists(txt_path):
        with open(txt_path, encoding="utf-8") as vocab_file:
            return {line.rstrip("\n") for line in vocab_file}
    return set()


def detect_model_type(vocabulary):
    """Tell which kind of model a vocabulary belongs to

    Args:
        vocabulary (set): Tokens of the shared vocabulary

    Returns:
        model_type (str): "nllb", "m2m", or "other" for models without language codes
    """
    if {"eng_Latn", "fra_Latn"} <= vocabulary:
        return "nllb"
    if "madeupwordforbt" in vocabulary or {"__en__", "__fr__"} <= vocabulary:
        return "m2m"
    return "other"
