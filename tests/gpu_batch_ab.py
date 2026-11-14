"""Compare the batch settings of the CPU and of the GPU on a GPU, in alternating runs.

Usage: python tests/gpu_batch_ab.py FLORES_DIR MODEL_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz). MODEL_DIR is a
NLLB-200 CTranslate2 folder with sentencepiece.model. The model is loaded once on the GPU. An English text of about
2,000 words (BATCH_AB_WORDS) is translated into French with a beam size of 3, alternately with the settings of the CPU
(8 sentences per call, 1,024 tokens per CTranslate2 batch, which version 0.4.1 also used on a GPU) and with the settings
of the GPU (128 sentences or 4,096 tokens per call, 4,096 tokens per batch). The rounds (BATCH_AB_ROUNDS, 5 by default)
alternate which setting goes first, after a warm-up run of each. The script records the words per second of every run,
the ratio of the medians, and whether the two settings gave the same translation.
"""
import json
import os
import platform
import statistics
import sys
import time

import ctranslate2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402
from utils.paragraph_splitter import paragraph_detokenizer  # noqa: E402

WORDS = int(os.environ.get("BATCH_AB_WORDS", 2000))
ROUNDS = int(os.environ.get("BATCH_AB_ROUNDS", 5))
SETTINGS = {
    "cpu settings": {"batch_sentences": engine.BATCH_SENTENCES, "call_tokens": 0, "max_batch_tokens": engine.MAX_BATCH_TOKENS},
    "gpu settings": {"batch_sentences": engine.GPU_BATCH_SENTENCES, "call_tokens": engine.GPU_BATCH_TOKENS, "max_batch_tokens": engine.GPU_BATCH_TOKENS},
}


def text_of(flores, words):
    """Consecutive devtest sentences, five to a line, with about this many words"""
    path = os.path.join(flores, "flores200_dataset", "devtest", "eng_Latn.devtest")
    with open(path, encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file][100:]
    chosen, count = [], 0
    for line in lines:
        chosen.append(line)
        count += len(line.split())
        if count >= words:
            break
    return "\n".join("  ".join(chosen[i : i + 5]) for i in range(0, len(chosen), 5))


def run(translator, text, name):
    for key, value in SETTINGS[name].items():
        setattr(translator, key, value)
    start = time.perf_counter()
    sentences, breaks, batches, _ = translator.split(text, "en")
    output = paragraph_detokenizer(translator.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks)
    return time.perf_counter() - start, output


def main(flores, model_dir, output):
    text = text_of(flores, WORDS)
    words = len(text.split())
    translator = engine.Engine()
    translator.load_model(model_dir, "cuda")
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    outputs = {name: run(translator, text, name)[1] for name in SETTINGS}  # warm-up of each setting
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cores": os.cpu_count(),
                    "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "device_used": translator.device, "compute_type": translator.compute_type, "words": words, "rounds": ROUNDS,
        "settings": SETTINGS, "words_per_second": {name: [] for name in SETTINGS}, "same_translation": outputs["cpu settings"] == outputs["gpu settings"],
    }
    for i in range(ROUNDS):
        for name in (SETTINGS if i % 2 == 0 else reversed(list(SETTINGS))):
            seconds, _ = run(translator, text, name)
            results["words_per_second"][name].append(words / seconds)
            print("round %d %-13s %7.0f words/s" % (i + 1, name, words / seconds), flush=True)
    medians = {name: statistics.median(values) for name, values in results["words_per_second"].items()}
    results["median_words_per_second"] = medians
    results["ratio"] = medians["gpu settings"] / medians["cpu settings"]
    print("median %.0f against %.0f words/s, ratio %.2f, same translation: %s" % (
        medians["gpu settings"], medians["cpu settings"], results["ratio"], results["same_translation"]), flush=True)
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
