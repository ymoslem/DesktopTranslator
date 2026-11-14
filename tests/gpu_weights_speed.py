"""Compare the speed and the GPU memory of the int8 files of a model with a model converted straight to float16.

Usage: python tests/gpu_weights_speed.py FLORES_DIR INT8_DIR FLOAT16_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz). INT8_DIR is the
NLLB-200 CTranslate2 folder that the app downloads, and FLOAT16_DIR is the same model converted from the original
weights with ct2-transformers-converter --quantization float16 (see tests/gpu_weights_eval.py). On a GPU the app runs
both as float16, so the computation is the same, and they differ in the weights and in the conversion at load.

Each model is loaded on the GPU twice, in the order int8, float16, int8, float16, so that the first load of a file
(cold disk cache) and the second can be told apart. Per load the script records the load time and the memory used on the
GPU. After the second load of a model it translates an English text of about 2,000 words (BATCH_SPEED_WORDS) into
French with the settings of the app on a GPU, three times after a warm-up run, and records the median words per second.
"""
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time

import ctranslate2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402
from utils.paragraph_splitter import paragraph_detokenizer  # noqa: E402

WORDS = int(os.environ.get("BATCH_SPEED_WORDS", 2000))
RUNS = 3


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


def gpu_memory_mb():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True).stdout
    return int(out.splitlines()[0])


def load(model_dir):
    translator = engine.Engine()
    start = time.perf_counter()
    translator.load_model(model_dir, "cuda")
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    return translator, time.perf_counter() - start


def main(flores, int8_dir, float16_dir, output):
    text = text_of(flores, WORDS)
    words = len(text.split())
    load(int8_dir)  # the first load of the process starts CUDA, which is not what is compared
    gc.collect()
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cores": os.cpu_count(),
                    "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "words": words, "beam": 3, "runs": RUNS, "loads": [], "speed": {},
    }
    for name, model_dir in (("int8 files", int8_dir), ("float16 files", float16_dir), ("int8 files", int8_dir), ("float16 files", float16_dir)):
        gc.collect()
        time.sleep(1)
        before = gpu_memory_mb()
        translator, seconds = load(model_dir)
        loaded = gpu_memory_mb()
        row = {"model": name, "load_seconds": seconds, "gpu_memory_after_load_mb": loaded - before, "compute_type": translator.compute_type}
        results["loads"].append(row)
        print("%-14s load %5.2f s  GPU memory %d MB  compute type %s" % (name, seconds, row["gpu_memory_after_load_mb"], row["compute_type"]), flush=True)
        if len([r for r in results["loads"] if r["model"] == name]) == 2:  # the second load of each model is timed for speed
            def run(translator=translator):
                sentences, breaks, batches, _ = translator.split(text, "en")
                return paragraph_detokenizer(translator.translate(batches, 3, "fra_Latn", "eng_Latn"), breaks)
            run()  # warm-up
            times = []
            for _ in range(RUNS):
                start = time.perf_counter()
                run()
                times.append(time.perf_counter() - start)
            results["speed"][name] = {"seconds": statistics.median(times), "words_per_second": words / statistics.median(times)}
            print("%-14s %7.0f words/s (median of %d runs, %d words)" % (name, results["speed"][name]["words_per_second"], RUNS, words), flush=True)
        del translator
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]), os.path.abspath(sys.argv[4]))
