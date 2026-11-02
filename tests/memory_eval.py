"""Measure the memory that NLLB-200 models need, and check it against the estimate of the app.

Usage: python tests/memory_eval.py FLORES_DIR RESULTS.json MODEL_DIR [MODEL_DIR ...]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
Each MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. Every model is measured in
its own process: the peak memory after loading it, and after translating 100 sentences with beam
sizes 3 and 5. The script fails if the peak is higher than the estimate of engine.memory_needed.

Peaks measured on a Mac with Apple silicon, in GB, as beam 3 and beam 5 (the estimate is 1.3 times the model file plus 1.7 GB)
  NLLB-200 distilled 600M  2.03, 2.23  (estimate 2.50)
  NLLB-200 distilled 1.3B  2.89, 3.33  (estimate 3.49)
  NLLB-200 3.3B            5.74, 5.99  (estimate 6.07)
"""
import json
import os
import resource
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTENCES, STEP = 100, 10


def peak_bytes():
    """Peak memory of this process; macOS reports bytes, Linux kilobytes"""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def measure(model_dir, flores):
    sys.path.insert(0, ROOT)
    import engine

    with open(os.path.join(flores, "flores200_dataset", "devtest", "eng_Latn.devtest"), encoding="utf-8") as file:
        sentences = [line.rstrip("\n") for line in file][::STEP][:SENTENCES]
    translator = engine.Engine()
    translator.load_model(model_dir)
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    result = {"loaded": peak_bytes()}
    for beam in (3, 5):
        for i in range(0, len(sentences), engine.BATCH_SENTENCES):
            translator.translate_batch(sentences[i : i + engine.BATCH_SENTENCES], beam, "fra_Latn", "eng_Latn")
        result["beam%d" % beam] = peak_bytes()
    result["model_bin"] = os.path.getsize(os.path.join(model_dir, "model.bin"))
    result["estimate"] = engine.memory_needed(model_dir)
    return result


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        print(json.dumps(measure(sys.argv[2], sys.argv[3])))
        sys.exit(0)
    flores, output, models = os.path.abspath(sys.argv[1]), sys.argv[2], [os.path.abspath(m) for m in sys.argv[3:]]
    results, failures = {}, []
    for model in models:
        out = subprocess.run([sys.executable, __file__, "--child", model, flores], capture_output=True, text=True, check=True)
        results[os.path.basename(model)] = json.loads(out.stdout.strip().splitlines()[-1])
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=2)
    print("%-34s %9s %9s %9s %9s %9s" % ("model", "model.bin", "loaded", "beam 3", "beam 5", "estimate"))
    for name, r in results.items():
        print("%-34s %8.2f %8.2f %8.2f %8.2f %8.2f  (GB)" % (name, r["model_bin"] / 1e9, r["loaded"] / 1e9, r["beam3"] / 1e9, r["beam5"] / 1e9, r["estimate"] / 1e9))
        if max(r["beam3"], r["beam5"]) > r["estimate"]:
            failures.append(name)
    print("The estimate covers every measured peak." if not failures else "The estimate is too low for: " + ", ".join(failures))
    sys.exit(1 if failures else 0)
