"""Score the translations saved by tests/beam_eval.py with COMET, and compare beam sizes.

Usage: python tests/comet_beam.py FLORES_DIR BEAM_RESULTS.json OUTPUT.json

FLORES_DIR holds flores200_dataset, from which the sources and the references are read in the same way as in
beam_eval.py (BEAM_SENTENCES, 200 by default, must be the same value). The metric is Unbabel/wmt22-comet-da
(COMET-22), run on the CPU, or on the GPU of a Mac if the environment variable COMET_DEVICE is mps. It needs
unbabel-comet. On a Mac, num_workers must be above 0, because the library asks for a forked data loader.

For every language and beam size it saves the system score and the score of every segment to OUTPUT.json, and
compares each beam size with the default (beam 3) by a paired bootstrap: 1,000 resamples of the sentences, seed 1,
the difference in the mean COMET score with a 95% percentile interval.
"""
import json
import os
import random
import sys
import time

from comet import download_model, load_from_checkpoint

MODEL = "Unbabel/wmt22-comet-da"
DEVICE = os.environ.get("COMET_DEVICE", "cpu")
SENTENCES = int(os.environ.get("BEAM_SENTENCES", 200))
DEFAULT_BEAM, RESAMPLES = "3", 1000
TARGETS = {"French": "fra_Latn", "Arabic": "arb_Arab", "Turkish": "tur_Latn", "Hindi": "hin_Deva"}


def read(flores, code):
    with open(os.path.join(flores, "flores200_dataset", "devtest", code + ".devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    return lines[:: max(len(lines) // SENTENCES, 1)][:SENTENCES]


def bootstrap(scores_a, scores_b):
    """Difference in mean score (a minus b) with a 95% interval, over resampled sentences"""
    rng, n = random.Random(1), len(scores_a)
    differences = []
    for _ in range(RESAMPLES):
        chosen = [rng.randrange(n) for _ in range(n)]
        differences.append(sum(scores_a[i] - scores_b[i] for i in chosen) / n)
    differences.sort()
    return differences[int(0.025 * RESAMPLES)], differences[int(0.975 * RESAMPLES) - 1]


def main(flores, results_path, output):
    with open(results_path, encoding="utf-8") as file:
        results = json.load(file)
    sources = read(flores, "eng_Latn")
    assert len(sources) == results["sentences"], "the number of sentences differs from the results of beam_eval.py"
    model = load_from_checkpoint(download_model(MODEL))
    scored = {"metric": MODEL, "device": DEVICE, "sentences": len(sources), "comet": {}, "segments": {}, "bootstrap_vs_beam_" + DEFAULT_BEAM: {}}
    for name, translations in results["translations"].items():
        references = read(flores, TARGETS[name])
        for beam, hypotheses in translations.items():
            samples = [{"src": s, "mt": h, "ref": r} for s, h, r in zip(sources, hypotheses, references)]
            start = time.time()
            out = model.predict(samples, batch_size=16, gpus=1 if DEVICE == "mps" else 0, accelerator=DEVICE, num_workers=2, progress_bar=False)
            scored["comet"].setdefault(name, {})[beam] = out.system_score
            scored["segments"].setdefault(name, {})[beam] = out.scores
            print("%-8s beam %s  COMET %.4f  (%d s)" % (name, beam, out.system_score, time.time() - start), flush=True)
        for beam in translations:
            if beam != DEFAULT_BEAM:
                low, high = bootstrap(scored["segments"][name][beam], scored["segments"][name][DEFAULT_BEAM])
                difference = scored["comet"][name][beam] - scored["comet"][name][DEFAULT_BEAM]
                scored["bootstrap_vs_beam_" + DEFAULT_BEAM].setdefault(name, {})[beam] = {"difference": difference, "low": low, "high": high}
                print("%-8s beam %s minus beam %s: %+.4f [%+.4f, %+.4f]" % (name, beam, DEFAULT_BEAM, difference, low, high), flush=True)
        with open(output, "w", encoding="utf-8") as file:
            json.dump(scored, file, indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3]))
