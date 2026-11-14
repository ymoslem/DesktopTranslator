"""Compare the CPU and the GPU of one machine, with the same batch settings.

Usage: python tests/gpu_cpu_same_machine.py FLORES_DIR MODEL_DIR RESULTS.json [DEVICE]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz). MODEL_DIR is a
NLLB-200 CTranslate2 folder with sentencepiece.model. DEVICE is cuda (the default); cpu makes both engines run on the
CPU, which is only for testing the script.

The model is loaded twice in one process, once on the CPU and once on the GPU, and an English text of about 2,000 words
(SAME_MACHINE_WORDS) is translated into French with a beam size of 3. Four settings are timed in alternating rounds
(SAME_MACHINE_ROUNDS, 3 by default) after a warm-up run of each: 8 sentences per batch on the CPU and on the GPU, and
128 sentences or 4,096 tokens per batch on the GPU and on the CPU. The script also times a paragraph of about 100 words,
five times each, on the CPU and on the GPU with their own default settings. It records the cores that the process may use,
since the CPU threads of the app are half of the cores, and the words per second of every run.
A container can see the cores of its host, so the environment variable SAME_MACHINE_CORES gives the number of cores that the app assumes,
which sets its CPU threads (two batches at a time, each with half of the cores), to imitate a machine of that size.
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

WORDS = int(os.environ.get("SAME_MACHINE_WORDS", 2000))
ROUNDS = int(os.environ.get("SAME_MACHINE_ROUNDS", 3))
SMALL = {"batch_sentences": engine.BATCH_SENTENCES, "call_tokens": 0, "max_batch_tokens": engine.MAX_BATCH_TOKENS}
LARGE = {"batch_sentences": engine.GPU_BATCH_SENTENCES, "call_tokens": engine.GPU_BATCH_TOKENS, "max_batch_tokens": engine.GPU_BATCH_TOKENS}
CONFIGS = [("cpu, 8 sentences", "cpu", SMALL), ("gpu, 8 sentences", "gpu", SMALL),
           ("gpu, 128 sentences", "gpu", LARGE), ("cpu, 128 sentences", "cpu", LARGE)]


def text_of(flores, words, start=100):
    """Consecutive devtest sentences, five to a line, with about this many words"""
    path = os.path.join(flores, "flores200_dataset", "devtest", "eng_Latn.devtest")
    with open(path, encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file][start:]
    chosen, count = [], 0
    for line in lines:
        chosen.append(line)
        count += len(line.split())
        if count >= words:
            break
    return "\n".join("  ".join(chosen[i : i + 5]) for i in range(0, len(chosen), 5))


def run(translator, text, settings=None):
    for key, value in (settings or {"batch_sentences": None, "call_tokens": None, "max_batch_tokens": None}).items():
        setattr(translator, key, value)
    start = time.perf_counter()
    sentences, breaks, batches, _ = translator.split(text, "en")
    paragraph_detokenizer(translator.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks)
    return time.perf_counter() - start, len(batches)


def main(flores, model_dir, output, device="cuda"):
    text, paragraph = text_of(flores, WORDS), text_of(flores, 100, start=50)
    words, paragraph_words = len(text.split()), len(paragraph.split())
    available = len(os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else range(os.cpu_count()))
    cores = int(os.environ.get("SAME_MACHINE_CORES", 0)) or available  # the cores that the app assumes, for its CPU threads
    os.cpu_count = lambda: cores  # the app uses half of the cores for the CPU threads; a container reports the cores of its host
    engines = {}
    for name, where in (("cpu", "cpu"), ("gpu", device)):
        translator = engine.Engine()
        translator.load_model(model_dir, where)
        translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
        engines[name] = translator
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cores_visible": available,
                    "cores_assumed": cores, "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "devices": {name: translator.device for name, translator in engines.items()}, "words": words, "paragraph_words": paragraph_words,
        "rounds": ROUNDS, "batches": {}, "words_per_second": {name: [] for name, _, _ in CONFIGS}, "paragraph_seconds": {},
    }
    for name, which, settings in CONFIGS:  # warm-up
        run(engines[which], text[: len(text) // 4], settings)
    for i in range(ROUNDS):
        order = CONFIGS[i % len(CONFIGS):] + CONFIGS[: i % len(CONFIGS)]
        for name, which, settings in order:
            seconds, batches = run(engines[which], text, settings)
            results["words_per_second"][name].append(words / seconds)
            results["batches"][name] = batches
            print("round %d %-20s %7.1f words/s (%d batches)" % (i + 1, name, words / seconds, batches), flush=True)
    for which in ("cpu", "gpu"):
        times = [run(engines[which], paragraph)[0] for _ in range(5)]
        results["paragraph_seconds"][which] = {"median": statistics.median(times), "runs": times}
        print("paragraph of %d words on the %s: %.2f s (median of 5)" % (paragraph_words, which, statistics.median(times)), flush=True)
    medians = {name: statistics.median(values) for name, values in results["words_per_second"].items()}
    results["median_words_per_second"] = medians
    results["ratios"] = {
        "gpu 8 over cpu 8": medians["gpu, 8 sentences"] / medians["cpu, 8 sentences"],
        "gpu 128 over gpu 8": medians["gpu, 128 sentences"] / medians["gpu, 8 sentences"],
        "gpu 128 over cpu 8": medians["gpu, 128 sentences"] / medians["cpu, 8 sentences"],
        "cpu 128 over cpu 8": medians["cpu, 128 sentences"] / medians["cpu, 8 sentences"],
    }
    for name, value in medians.items():
        print("median %-20s %7.1f words/s" % (name, value))
    for name, value in results["ratios"].items():
        print("ratio %-20s %.2f" % (name, value))
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else "cuda")
