"""Measure how the number of sentences per batch affects the speed of the CPU.

Usage: python tests/cpu_batch_eval.py FLORES_DIR MODEL_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz). MODEL_DIR is a
NLLB-200 CTranslate2 folder with sentencepiece.model. The model is loaded on the CPU as the app loads it. An English
text of about 1,000 words (CPU_BATCH_WORDS) is translated into French with a beam size of 3 and batches of 8, 16, 32, 64
and 128 sentences. The app uses 8 on the CPU. The batches of 128 sentences also use the limits of the GPU (4,096 tokens per
batch). The settings are timed in alternating rounds (CPU_BATCH_ROUNDS, 3 by default), each round in another order, after a
warm-up run of each. The script records the words per second of every run, the medians, and the ratio of each median to
that of 8 sentences, with the machine (system, processor and cores; no paths or names).
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

WORDS = int(os.environ.get("CPU_BATCH_WORDS", 1000))
ROUNDS = int(os.environ.get("CPU_BATCH_ROUNDS", 3))
SETTINGS = [(8, 0, 1024), (16, 0, 1024), (32, 0, 1024), (64, 0, 4096), (128, 4096, 4096)]  # sentences, tokens per call (0: no limit), tokens per batch


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


def run(translator, text, setting):
    translator.batch_sentences, translator.call_tokens, translator.max_batch_tokens = setting
    start = time.perf_counter()
    sentences, breaks, batches, _ = translator.split(text, "en")
    paragraph_detokenizer(translator.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks)
    return time.perf_counter() - start, len(sentences), len(batches)


def main(flores, model_dir, output):
    text = text_of(flores, WORDS)
    words = len(text.split())
    translator = engine.Engine()
    translator.load_model(model_dir, "cpu")
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    for setting in SETTINGS:  # warm-up
        run(translator, text[: len(text) // 5], setting)
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "machine": platform.machine(),
                    "cores": os.cpu_count(), "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "words": words, "rounds": ROUNDS, "device_used": translator.device,
        "words_per_second": {str(s[0]): [] for s in SETTINGS},
    }
    for i in range(ROUNDS):
        order = SETTINGS[i % len(SETTINGS):] + SETTINGS[: i % len(SETTINGS)]
        for setting in order:
            seconds, sentences, batches = run(translator, text, setting)
            results["words_per_second"][str(setting[0])].append(words / seconds)
            results["sentences"], results.setdefault("batches", {})[str(setting[0])] = sentences, batches
            print("round %d  %3d sentences per batch  %6.1f words/s  (%d batches)" % (i + 1, setting[0], words / seconds, batches), flush=True)
    medians = {name: statistics.median(values) for name, values in results["words_per_second"].items()}
    results["median_words_per_second"] = medians
    results["ratio_to_8"] = {name: value / medians["8"] for name, value in medians.items()}
    for name, value in medians.items():
        print("median %3s sentences  %6.1f words/s  ratio to 8: %.2f" % (name, value, results["ratio_to_8"][name]))
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
