"""Check that a larger batch on a GPU does not change the quality of the translation.

Usage: python tests/gpu_batch_quality.py FLORES_DIR MODEL_DIR RESULTS.json [DEVICE]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. DEVICE is cuda (the default) or cpu.
Evenly spaced FLORES-200 devtest sentences (BATCH_QUALITY_SENTENCES, 600 by default) are translated from English
into French and Arabic, with a beam size of 3, for several pairs of the number of sentences per call and the token
limit of a call (see tests/gpu_batch_eval.py). The first pair is the setting of the app. Different batches pad the
sentences differently, which can change a few numbers inside the model, so the output can differ in some sentences.
Per pair and language the script records chrF++ (sacrebleu, word order 2), the number of sentences whose
translation differs from that of the setting of the app, and the paired bootstrap of the chrF++ difference
(500 resamples of the sentences, seed 1, 95% percentile interval).
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

SENTENCES = int(os.environ.get("BATCH_QUALITY_SENTENCES", 600))
RESAMPLES = 500
PAIRS = ((8, 1024), (64, 4096), (128, 4096), (128, 16384))
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


def main(flores, model_dir, output, device="cuda"):
    sources = read(flores, "eng_Latn")
    translator = engine.Engine()
    translator.load_model(model_dir, device)
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    results = {
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "ctranslate2": ctranslate2.__version__},
        "device_used": translator.device, "sentences": len(sources), "beam": 3, "pairs": [list(p) for p in PAIRS], "rows": {},
    }
    for name, code in TARGETS.items():
        references = read(flores, code)
        outputs = {}
        for sentences, tokens in PAIRS:
            translator.max_batch_tokens = tokens
            translations = []
            for i in range(0, len(sources), sentences):
                translations.extend(translator.translate_batch(sources[i : i + sentences], 3, code, "eng_Latn"))
            outputs[(sentences, tokens)] = translations
        default = outputs[PAIRS[0]]
        for pair, translations in outputs.items():
            row = {
                "chrf": CHRF(word_order=2).corpus_score(translations, [references]).score,
                "different_from_default": sum(a != b for a, b in zip(translations, default)),
            }
            if pair != PAIRS[0]:
                low, high = bootstrap(translations, default, references)
                row["difference_from_default"] = row["chrf"] - results["rows"][name]["%d,%d" % PAIRS[0]]["chrf"]
                row["low"], row["high"] = low, high
            results["rows"].setdefault(name, {})["%d,%d" % pair] = row
            print("%-7s sentences %3d tokens %5d  chrF++ %.2f  different %3d/%d%s" % (
                name, pair[0], pair[1], row["chrf"], row["different_from_default"], len(sources),
                "" if "low" not in row else "  difference %+.2f [%+.2f, %+.2f]" % (row["difference_from_default"], row["low"], row["high"])), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]),
         sys.argv[4] if len(sys.argv) > 4 else "cuda")
