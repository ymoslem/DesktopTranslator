"""Measure how the number of sentences per call and the token limit of a call affect the speed on a GPU.

Usage: python tests/gpu_batch_eval.py FLORES_DIR MODEL_DIR RESULTS.json [DEVICE]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. DEVICE is cuda (the default) or cpu.
The environment variable BATCH_EVAL_WORDS sets the length of the text (2,000 words by default).

An English text of consecutive FLORES-200 devtest sentences is translated into French with the code path of
the app (splitting into sentences, batches, deduplication), with a beam size of 3. The app sends 8 sentences
per call (engine.BATCH_SENTENCES), and CTranslate2 splits a call into batches of at most 1,024 tokens
(engine.MAX_BATCH_TOKENS); the script sets both limits on the Engine and turns off the limit of tokens per call. For each pair of values the script records the median time of 3 runs after a warm-up
run, the words per second, the mean time of a call (which is how often the progress is updated and how long
Cancel can take), the use of the GPU sampled with nvidia-smi during the runs, and whether the translation
equals the one with the settings of the app.
"""
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time

import ctranslate2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402
from utils.paragraph_splitter import paragraph_detokenizer  # noqa: E402

WORDS = int(os.environ.get("BATCH_EVAL_WORDS", 2000))
BEAM, RUNS = 3, 3
SENTENCES_PER_CALL = (4, 8, 16, 32, 64, 128, 256)
TOKEN_LIMITS = (1024, 4096, 16384)
DEFAULT = (engine.BATCH_SENTENCES, engine.MAX_BATCH_TOKENS)  # the CPU settings, which v0.4.0 also used on a GPU


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


class GpuSampler(threading.Thread):
    """Samples the use and the memory of the first GPU with nvidia-smi until stopped"""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event, self.use, self.memory = threading.Event(), [], []

    def run(self):
        while not self.stop_event.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, check=True).stdout.splitlines()[0]
                use, memory = (int(v) for v in out.split(","))
                self.use.append(use)
                self.memory.append(memory)
            except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
                return
            self.stop_event.wait(0.2)


def translate_text(translator, text):
    sentences, breaks, batches, _ = translator.split(text, "en")
    translations = translator.translate(batches, BEAM, "fra_Latn", "eng_Latn")
    return paragraph_detokenizer(translations, breaks), len(batches)


def main(flores, model_dir, output, device="cuda"):
    text = text_of(flores, WORDS)
    words = len(text.split())
    translator = engine.Engine()
    translator.load_model(model_dir, device)
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cores": os.cpu_count(),
                    "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "device_used": translator.device, "model": os.path.basename(os.path.normpath(model_dir)),
        "words": words, "beam": BEAM, "runs": RUNS, "default": {"sentences_per_call": DEFAULT[0], "token_limit": DEFAULT[1]},
        "rows": [],
    }
    reference = None
    pairs = [DEFAULT] + [(s, t) for t in TOKEN_LIMITS for s in SENTENCES_PER_CALL if (s, t) != DEFAULT]
    for sentences, tokens in pairs:
        translator.batch_sentences, translator.max_batch_tokens, translator.call_tokens = sentences, tokens, 0  # 0: no limit in tokens
        translate_text(translator, text)  # warm-up
        sampler = GpuSampler()
        sampler.start()
        times, calls, output_text = [], 0, ""
        for _ in range(RUNS):
            start = time.perf_counter()
            output_text, calls = translate_text(translator, text)
            times.append(time.perf_counter() - start)
        sampler.stop_event.set()
        sampler.join()
        reference = reference or output_text
        seconds = statistics.median(times)
        row = {
            "sentences_per_call": sentences, "token_limit": tokens, "seconds": seconds, "words_per_second": words / seconds,
            "calls": calls, "seconds_per_call": seconds / calls,
            "gpu_use_mean": statistics.mean(sampler.use) if sampler.use else None,
            "gpu_use_max": max(sampler.use) if sampler.use else None,
            "gpu_memory_max_mb": max(sampler.memory) if sampler.memory else None,
            "same_as_default": output_text == reference,
        }
        results["rows"].append(row)
        print("sentences %3d tokens %5d  %7.1f words/s  %5.2f s/call  GPU use mean %s max %s  memory %s MB  same %s" % (
            sentences, tokens, row["words_per_second"], row["seconds_per_call"],
            "-" if row["gpu_use_mean"] is None else "%.0f%%" % row["gpu_use_mean"],
            "-" if row["gpu_use_max"] is None else "%d%%" % row["gpu_use_max"],
            row["gpu_memory_max_mb"], row["same_as_default"]), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else "cuda")
