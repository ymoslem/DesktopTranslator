"""Compare a GPU run of the int8 files of a model with a model converted straight to float16.

Usage: python tests/gpu_weights_eval.py FLORES_DIR INT8_DIR FLOAT16_DIR RESULTS.json [DEVICE]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
INT8_DIR is the NLLB-200 CTranslate2 folder that the app downloads (int8 weights), and FLOAT16_DIR is the same model
converted from the original weights with ct2-transformers-converter --quantization float16. Both folders have a
sentencepiece.model. DEVICE is cuda (the default) or cpu. On a GPU the app runs the int8 files as float16, so the
two models differ only in the weights: the int8 files hold the weights rounded to 8 bits.

Evenly spaced FLORES-200 devtest sentences (WEIGHTS_EVAL_SENTENCES, 600 by default) are translated from English
into French and Arabic with the settings of the app (beam size 3, 8 sentences per call). Per language the script
records chrF++ (sacrebleu, word order 2) for each model, the number of sentences whose translation differs, and
the paired bootstrap of the chrF++ difference (500 resamples, seed 1, 95% percentile interval).
"""
import json
import os
import platform
import random
import sys

import ctranslate2
from sacrebleu.metrics import CHRF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402

SENTENCES = int(os.environ.get("WEIGHTS_EVAL_SENTENCES", 600))
RESAMPLES = 500
TARGETS = {"French": "fra_Latn", "Arabic": "arb_Arab"}


def read(flores, code):
    with open(os.path.join(flores, "flores200_dataset", "devtest", code + ".devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    return lines[:: max(len(lines) // SENTENCES, 1)][:SENTENCES]


def bootstrap(hypotheses_a, hypotheses_b, references):
    """Difference in chrF++ (a minus b) with a 95% interval, over resampled sentences"""
    metric, rng, n = CHRF(word_order=2), random.Random(1), len(references)
    differences = []
    for _ in range(RESAMPLES):
        chosen = [rng.randrange(n) for _ in range(n)]
        refs = [[references[i] for i in chosen]]
        differences.append(metric.corpus_score([hypotheses_a[i] for i in chosen], refs).score
                           - metric.corpus_score([hypotheses_b[i] for i in chosen], refs).score)
    differences.sort()
    return differences[int(0.025 * RESAMPLES)], differences[int(0.975 * RESAMPLES) - 1]


def translate(model_dir, device, sources, code):
    translator = engine.Engine()
    translator.load_model(model_dir, device)
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    translations = []
    for i in range(0, len(sources), engine.BATCH_SENTENCES):
        translations.extend(translator.translate_batch(sources[i : i + engine.BATCH_SENTENCES], 3, code, "eng_Latn"))
    return translations, translator.device


def main(flores, int8_dir, float16_dir, output, device="cuda"):
    sources = read(flores, "eng_Latn")
    results = {
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "sentences": len(sources), "beam": 3, "batch": engine.BATCH_SENTENCES, "rows": {},
    }
    for name, code in TARGETS.items():
        references = read(flores, code)
        int8, used = translate(int8_dir, device, sources, code)
        float16, _ = translate(float16_dir, device, sources, code)
        score_int8 = CHRF(word_order=2).corpus_score(int8, [references]).score
        score_float16 = CHRF(word_order=2).corpus_score(float16, [references]).score
        low, high = bootstrap(float16, int8, references)
        results["device_used"] = used
        results["rows"][name] = {
            "chrf_int8_files": score_int8, "chrf_float16_files": score_float16, "difference": score_float16 - score_int8,
            "low": low, "high": high, "different_sentences": sum(a != b for a, b in zip(int8, float16)),
        }
        print("%-7s int8 files %.2f  float16 files %.2f  difference %+.2f [%+.2f, %+.2f]  different %d/%d" % (
            name, score_int8, score_float16, score_float16 - score_int8, low, high,
            results["rows"][name]["different_sentences"], len(sources)), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]), os.path.abspath(sys.argv[4]),
         sys.argv[5] if len(sys.argv) > 5 else "cuda")
