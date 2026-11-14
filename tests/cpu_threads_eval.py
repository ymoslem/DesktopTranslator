"""Measure how the layout of the CPU threads and the number of sentences per batch affect the speed of the CPU.

Usage: python tests/cpu_threads_eval.py FLORES_DIR MODEL_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz). MODEL_DIR is a
NLLB-200 CTranslate2 folder with sentencepiece.model. An English text of about 1,000 words (CPU_THREADS_WORDS) is translated
into French with a beam size of 3 on the CPU. The app runs two workers, each with half of the cores as threads, so that two
batches of a call can be translated at the same time. A call of 8 sentences is one batch, which leaves one worker idle. The script
times this layout and a layout with one worker that has all the cores, each with 8 and with 32 sentences per call, in
alternating rounds (CPU_THREADS_ROUNDS, 3 by default), each round in another order, after a warm-up run of each. It records the
words per second of every run, the medians, and the ratio of each median to the first one (the layout of the app with 8 sentences). The
machine is recorded without paths or names. The environment variable CPU_THREADS_CORES gives the cores to assume, for a container, and CPU_THREADS_LAYOUTS (such as 2x16,1x8)
replaces the layouts and the sentence counts by those layouts, with 8 sentences per call.
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

WORDS = int(os.environ.get("CPU_THREADS_WORDS", 1000))
ROUNDS = int(os.environ.get("CPU_THREADS_ROUNDS", 3))
VISIBLE = os.cpu_count()
CORES = int(os.environ.get("CPU_THREADS_CORES", 0)) or VISIBLE  # a container sees the cores of its host
os.cpu_count = lambda: CORES  # the engine takes the CPU threads of the app from it


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


def run(translator, text, sentences_per_call):
    translator.batch_sentences, translator.call_tokens, translator.max_batch_tokens = sentences_per_call, 0, engine.MAX_BATCH_TOKENS
    start = time.perf_counter()
    sentences, breaks, batches, _ = translator.split(text, "en")
    paragraph_detokenizer(translator.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks)
    return time.perf_counter() - start


def main(flores, model_dir, output):
    text = text_of(flores, WORDS)
    words = len(text.split())
    translator = engine.Engine()
    translator.load_model(model_dir, "cpu")  # the layout of the app: two workers, each with half of the cores
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    layouts = {
        "app: 2 workers, half of the cores each": translator.translator,
        "1 worker, all the cores": ctranslate2.Translator(model_dir, device="cpu", inter_threads=1, intra_threads=CORES),
    }
    spec = os.environ.get("CPU_THREADS_LAYOUTS")  # for example "2x16,1x8": workers times threads, with 8 sentences per call
    if spec:
        layouts = {}
        for item in spec.split(","):
            workers, threads = (int(n) for n in item.split("x"))
            layouts[item] = ctranslate2.Translator(model_dir, device="cpu", inter_threads=workers, intra_threads=threads)
    configs = [(layout, 8) for layout in layouts] if spec else [(layout, sentences) for sentences in (8, 32) for layout in layouts]
    names = ["%s, %d sentences" % config for config in configs]
    for layout, sentences in configs:  # warm-up
        translator.translator = layouts[layout]
        run(translator, text[: len(text) // 4], sentences)
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "machine": platform.machine(),
                    "cores": CORES, "cores_visible": VISIBLE, "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "words": words, "rounds": ROUNDS, "app_threads": {"workers": 2, "threads_each": int(CORES / 2)},
        "words_per_second": {name: [] for name in names},
    }
    for i in range(ROUNDS):
        shift = i % len(configs)
        for layout, sentences in configs[shift:] + configs[:shift]:
            translator.translator = layouts[layout]
            seconds = run(translator, text, sentences)
            name = "%s, %d sentences" % (layout, sentences)
            results["words_per_second"][name].append(words / seconds)
            print("round %d  %-45s %6.1f words/s" % (i + 1, name, words / seconds), flush=True)
    medians = {name: statistics.median(values) for name, values in results["words_per_second"].items()}
    results["median_words_per_second"] = medians
    base = medians[names[0]]
    results["ratio_to_first"] = {name: value / base for name, value in medians.items()}
    for name in names:
        print("median %-45s %6.1f words/s  ratio to the first: %.2f" % (name, medians[name], results["ratio_to_first"][name]))
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
