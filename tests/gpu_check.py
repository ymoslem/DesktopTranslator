"""Check that DesktopTranslator translates on a GPU, and compare the compute types.

Usage: python tests/gpu_check.py FLORES_DIR MODEL_DIR RESULTS.json [DEVICE [COMPUTE_TYPE ...]]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. DEVICE is cuda (the default) or cpu.
The environment variable GPU_CHECK_SENTENCES sets the number of sentences (200 by default).

English sentences of the FLORES-200 devtest set are translated into French with the settings of the app
(beam size 3, batches of 8 sentences). The first row, "app", loads the model as the app does, with the compute
type it chooses. The other rows load the same files with each COMPUTE_TYPE, by default every type that the
device supports. Per row it records the load time, the speed in words per second, chrF++ against the
references, the memory used on the GPU after the run (nvidia-smi), and how many translations equal those
of the first row. The results, with every translation, are saved to RESULTS.json.

Run it on an idle machine. The results are for comparing compute types on one machine; speeds from
different machines are comparable only with the same model and library versions, which are saved too.
"""
import gc
import json
import os
import platform
import subprocess
import sys
import time

import ctranslate2
from sacrebleu.metrics import CHRF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402

SENTENCES = int(os.environ.get("GPU_CHECK_SENTENCES", 200))
BEAM, BATCH = 3, 8
ALL_TYPES = ("float16", "int8_float16", "int8", "float32")


def read(flores, code):
    """Evenly spaced devtest sentences"""
    with open(os.path.join(flores, "flores200_dataset", "devtest", code + ".devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    return lines[:: max(len(lines) // SENTENCES, 1)][:SENTENCES]


def gpu_info():
    """Name, driver, memory and compute capability of the GPUs, from nvidia-smi; empty without it"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in out.splitlines()]


def gpu_memory_mb():
    """Memory in use on the first GPU, in MB; None without nvidia-smi"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        ).stdout
        return int(out.splitlines()[0])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def load(model_dir, device, compute_type):
    """An Engine with the model; compute_type "app" loads it as the app does"""
    translator = engine.Engine()
    start = time.perf_counter()
    if compute_type == "app":
        translator.load_model(model_dir, device)
    else:
        translator.inspect_model(model_dir)
        options = {"inter_threads": 2, "intra_threads": os.cpu_count() // 2} if device == "cpu" else {}
        translator.translator = ctranslate2.Translator(model_dir, device=device, compute_type=compute_type, **options)
        translator.device = device
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    return translator, time.perf_counter() - start


def translate_all(translator, sources):
    translations = []
    for i in range(0, len(sources), BATCH):
        translations.extend(translator.translate_batch(sources[i : i + BATCH], BEAM, "fra_Latn", "eng_Latn"))
    return translations


def main(flores, model_dir, output, device="cuda", types=()):
    sources, references = read(flores, "eng_Latn"), read(flores, "fra_Latn")
    if device == "cuda":
        assert ctranslate2.get_cuda_device_count() > 0, "CTranslate2 sees no GPU"
        supported = ctranslate2.get_supported_compute_types("cuda")
    else:
        supported = ctranslate2.get_supported_compute_types("cpu")
    chosen = list(types) or [t for t in ALL_TYPES if t in supported]
    for kind in chosen:
        assert kind in supported, "%s is not supported on %s (supported: %s)" % (kind, device, sorted(supported))
    words = sum(len(s.split()) for s in sources)
    results = {
        "machine": {
            "platform": platform.platform(), "processor": platform.processor(), "cores": os.cpu_count(),
            "python": platform.python_version(), "ctranslate2": ctranslate2.__version__,
            "gpus": gpu_info(), "supported_compute_types": sorted(supported),
        },
        "device": device, "model": os.path.basename(os.path.normpath(model_dir)),
        "sentences": len(sources), "words": words, "beam": BEAM, "batch": BATCH, "rows": {},
    }
    first = None
    for kind in ["app"] + chosen:
        translator, load_seconds = load(model_dir, device, kind)
        translate_all(translator, sources[:BATCH])  # warm-up, so that the timing leaves out the first call
        start = time.perf_counter()
        translations = translate_all(translator, sources)
        seconds = time.perf_counter() - start
        first = first or translations
        row = {
            "load_seconds": load_seconds, "seconds": seconds, "words_per_second": words / seconds,
            "chrf": CHRF(word_order=2).corpus_score(translations, [references]).score,
            "gpu_memory_mb": gpu_memory_mb() if device == "cuda" else None,
            "same_as_first": sum(a == b for a, b in zip(translations, first)),
            "device_used": translator.device, "translations": translations,
        }
        results["rows"][kind] = row
        print("%-13s %-5s load %5.1f s, %6.1f words/s, chrF++ %5.2f, GPU memory %s MB, same as first %d/%d" % (
            kind, row["device_used"], load_seconds, row["words_per_second"], row["chrf"], row["gpu_memory_mb"],
            row["same_as_first"], len(sources)), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1, ensure_ascii=False)
        del translator
        gc.collect()
    assert results["rows"]["app"]["device_used"] == device, "the app code path did not use %s" % device


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else "cuda", sys.argv[5:])
