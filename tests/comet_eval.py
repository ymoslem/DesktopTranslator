"""Score the translations saved by tests/llm_eval.py with COMET.

Usage: python tests/comet_eval.py OUTPUT.json RESULTS.json [RESULTS.json ...]

Each RESULTS.json is an output of llm_eval.py. A system that appears in several files (such as NLLB-200,
which every run translates again) must have identical translations, and it is scored once. The system is
named NAME in the first file; for the other files pass NAME@SUFFIX through the environment variable
COMET_SUFFIXES as a comma-separated list, one suffix per file after the first, to tell variants apart
(for example "beam4" gives TranslateGemma-4B@beam4). The scores of every segment are saved to OUTPUT.json,
so that differences can be tested with a paired bootstrap.

The metric is Unbabel/wmt22-comet-da (COMET-22), run on the CPU, or on the GPU of a Mac if the
environment variable COMET_DEVICE is mps. It needs unbabel-comet. On a Mac, num_workers must be above 0,
because the library asks for a forked data loader.
"""
import json
import os
import sys
import time

from comet import download_model, load_from_checkpoint

MODEL = "Unbabel/wmt22-comet-da"
DEVICE = os.environ.get("COMET_DEVICE", "cpu")  # "mps" uses the GPU of a Mac


def main(output, files):
    suffixes = [""] + [s for s in os.environ.get("COMET_SUFFIXES", "").split(",") if s]
    assert len(suffixes) == len(files), "give one suffix in COMET_SUFFIXES for each file after the first"
    model = load_from_checkpoint(download_model(MODEL))
    scored = {"metric": MODEL, "device": DEVICE, "systems": {}}
    seen = {}
    for path, suffix in zip(files, suffixes):
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        for name, result in data["results"].items():
            key = name + ("@" + suffix if suffix and name != "NLLB-200" else "")
            if key in seen:
                assert seen[key] == result["translations"], "%s differs between files" % key
                continue
            seen[key] = result["translations"]
            scored["systems"][key] = {}
            for target, hypotheses in result["translations"].items():
                code = [c for c in data["references"] if c.startswith({"French": "fra", "Arabic": "arb", "Turkish": "tur", "Hindi": "hin"}[target])][0]
                samples = [{"src": s, "mt": h, "ref": r} for s, h, r in zip(data["sources"], hypotheses, data["references"][code])]
                start = time.time()
                out = model.predict(samples, batch_size=16, gpus=1 if DEVICE == "mps" else 0, accelerator=DEVICE, num_workers=2, progress_bar=False)
                scored["systems"][key][target] = {"system_score": out.system_score, "segment_scores": out.scores}
                print("%-28s %-8s COMET %.4f (%d s)" % (key, target, out.system_score, time.time() - start), flush=True)
                with open(output, "w", encoding="utf-8") as file:
                    json.dump(scored, file, indent=1)
    print("\n%-28s %s" % ("system", "".join("%-10s" % t for t in ("French", "Arabic", "Turkish", "Hindi"))))
    for key, targets in scored["systems"].items():
        print("%-28s %s" % (key, "".join("%-10.4f" % targets[t]["system_score"] for t in ("French", "Arabic", "Turkish", "Hindi"))))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), [os.path.abspath(p) for p in sys.argv[2:]])
