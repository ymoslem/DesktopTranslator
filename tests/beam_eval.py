"""Compare beam sizes for NLLB-200 on FLORES-200, with the settings of the app.

Usage: python tests/beam_eval.py FLORES_DIR MODEL_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. English sentences of the devtest set
(BEAM_SENTENCES, 200 by default, evenly spaced) are translated into French, Arabic, Turkish and Hindi with
beam sizes 1, 2, 3 and 5, in batches of 8 as in the app. Per beam size and language it records chrF++
(sacrebleu, word order 2), the time, and the translations. Beam 3 is the default of the app, and the other beam
sizes are compared with it by a paired bootstrap (1,000 resamples of the sentences, seed 1): the difference in
chrF++ with a 95% percentile interval.

Run it on an idle machine; the times of a busy machine are not comparable.
"""
import json
import os
import platform
import random
import sys
import time

import ctranslate2
from sacrebleu.metrics import CHRF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine  # noqa: E402

SENTENCES = int(os.environ.get("BEAM_SENTENCES", 200))
BEAMS, DEFAULT_BEAM, BATCH, RESAMPLES = (1, 2, 3, 5), 3, 8, 1000
TARGETS = {"French": "fra_Latn", "Arabic": "arb_Arab", "Turkish": "tur_Latn", "Hindi": "hin_Deva"}


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


def main(flores, model_dir, output):
    sources = read(flores, "eng_Latn")
    translator = engine.Engine()
    translator.load_model(model_dir)
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    results = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cores": os.cpu_count(),
                    "python": platform.python_version(), "ctranslate2": ctranslate2.__version__,
                    "load_average": os.getloadavg()[0]},
        "model": os.path.basename(os.path.normpath(model_dir)), "sentences": len(sources), "batch": BATCH,
        "scores": {}, "translations": {}, "seconds": {}, "bootstrap_vs_beam_%d" % DEFAULT_BEAM: {},
    }
    references = {name: read(flores, code) for name, code in TARGETS.items()}
    for name, code in TARGETS.items():
        for beam in BEAMS:
            start = time.perf_counter()
            translations = []
            for i in range(0, len(sources), BATCH):
                translations.extend(translator.translate_batch(sources[i : i + BATCH], beam, code, "eng_Latn"))
            seconds = time.perf_counter() - start
            score = CHRF(word_order=2).corpus_score(translations, [references[name]]).score
            results["scores"].setdefault(name, {})[str(beam)] = score
            results["seconds"].setdefault(name, {})[str(beam)] = seconds
            results["translations"].setdefault(name, {})[str(beam)] = translations
            print("%-8s beam %d  chrF++ %5.2f  %6.1f s" % (name, beam, score, seconds), flush=True)
        for beam in BEAMS:
            if beam != DEFAULT_BEAM:
                low, high = bootstrap(results["translations"][name][str(beam)], results["translations"][name][str(DEFAULT_BEAM)], references[name])
                difference = results["scores"][name][str(beam)] - results["scores"][name][str(DEFAULT_BEAM)]
                results["bootstrap_vs_beam_%d" % DEFAULT_BEAM].setdefault(name, {})[str(beam)] = {"difference": difference, "low": low, "high": high}
                print("%-8s beam %d minus beam %d: %+.2f [%+.2f, %+.2f]" % (name, beam, DEFAULT_BEAM, difference, low, high), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
