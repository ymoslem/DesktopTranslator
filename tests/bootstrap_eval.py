"""Paired bootstrap of the differences between systems, for chrF++ and COMET.

Usage: python tests/bootstrap_eval.py OUTPUT.json COMET.json RESULTS.json [RESULTS.json ...]

COMET.json is an output of tests/comet_eval.py and the RESULTS.json files are outputs of tests/llm_eval.py,
given in the same order as for comet_eval.py (with COMET_SUFFIXES, the system of the second file is named
NAME@beam4 and so on; pass the same suffixes again). Each comparison resamples the sentences with
replacement, the same sentences for both systems, and recomputes the metric. The difference is the first
system minus the second. It reports the mean difference, the 95% percentile interval, and the share of
resamples in which the first system scores higher. Needs sacrebleu and numpy.
"""
import json
import os
import sys

import numpy as np
from sacrebleu.metrics import CHRF

RESAMPLES, SEED = 1000, 1
COMPARISONS = [("TranslateGemma-4B", "NLLB-200"), ("TranslateGemma-4B@beam4", "TranslateGemma-4B"), ("TranslateGemma-4B@beam4", "NLLB-200")]
CODES = {"French": "fra_Latn", "Arabic": "arb_Arab", "Turkish": "tur_Latn", "Hindi": "hin_Deva"}


def main(output, comet_path, files):
    suffixes = [""] + [s for s in os.environ.get("COMET_SUFFIXES", "").split(",") if s]
    assert len(suffixes) == len(files)
    with open(comet_path, encoding="utf-8") as file:
        comet = json.load(file)
    translations, references = {}, None
    for path, suffix in zip(files, suffixes):
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        references = references or data["references"]
        for name, result in data["results"].items():
            key = name + ("@" + suffix if suffix and name != "NLLB-200" else "")
            translations.setdefault(key, result["translations"])
    chrf = CHRF(word_order=2)
    stats = {key: {t: np.array(chrf._extract_corpus_statistics(translations[key][t], [references[CODES[t]]])) for t in CODES} for key in translations}
    rng = np.random.default_rng(SEED)
    n = len(references["fra_Latn"])
    samples = rng.integers(0, n, size=(RESAMPLES, n))  # the same resamples for every comparison
    out, rows = {}, []
    for a, b in COMPARISONS:
        for target in CODES:
            row = {}
            for metric in ("chrF++", "COMET"):
                if metric == "chrF++":
                    def value(key, idx):
                        return chrf._compute_score_from_stats(list(stats[key][target][idx].sum(axis=0))).score
                    diffs = np.array([value(a, i) - value(b, i) for i in samples])
                    observed = value(a, np.arange(n)) - value(b, np.arange(n))
                else:
                    sa, sb = np.array(comet["systems"][a][target]["segment_scores"]), np.array(comet["systems"][b][target]["segment_scores"])
                    diffs = np.array([sa[i].mean() - sb[i].mean() for i in samples]) * 100
                    observed = (sa.mean() - sb.mean()) * 100
                low, high = np.percentile(diffs, [2.5, 97.5])
                row[metric] = {"difference": round(float(observed), 2), "low": round(float(low), 2), "high": round(float(high), 2), "share_first_higher": round(float((diffs > 0).mean()), 3)}
            out["%s minus %s, %s" % (a, b, target)] = row
            rows.append((a, b, target, row))
    with open(output, "w", encoding="utf-8") as file:
        json.dump({"resamples": RESAMPLES, "seed": SEED, "sentences": n, "comparisons": out}, file, indent=1)
    print("%-26s %-26s %-8s %-30s %s" % ("first", "second", "language", "chrF++ difference [95%]", "COMET difference x100 [95%]"))
    for a, b, target, row in rows:
        f = lambda r: "%+.2f [%+.2f, %+.2f]" % (r["difference"], r["low"], r["high"])
        print("%-26s %-26s %-8s %-30s %s" % (a, b, target, f(row["chrF++"]), f(row["COMET"])))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), [os.path.abspath(p) for p in sys.argv[3:]])
