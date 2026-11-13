"""Measure the speed and memory of DesktopTranslator on this machine.

Usage: python tests/benchmark.py FLORES_DIR RESULTS.json MODEL_DIR [MODEL_DIR ...]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
Each MODEL_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model. Texts are English sentences of
the FLORES-200 devtest set, translated into French with the code path of the app (splitting into
sentences, batches, deduplication, and joining the translation).

For each model, a default configuration (the settings of the app) and variations of one setting at a time
are measured, each in its own process, so the memory peaks do not mix. Per configuration it records
  load_seconds      loading the model and the SentencePiece model
  first_seconds     the first translation of one sentence after loading
  sentence_seconds  one sentence, median of the later translations
  paragraph_seconds a paragraph of about 100 words, from text to translated text, median
  words_per_second  a text of about 2,000 words, median of the runs
  peak_bytes        peak resident memory of the process
The default configuration also times a text in which paragraphs repeat, with and without deduplication.

Set the environment variable BENCHMARK_ONLY_DEFAULT to measure only the default configuration.

Run it on an idle machine, with nothing else converting or evaluating. The load average before each
run is saved with the results. Libraries and the machine are saved too, so results of several machines
can be compared.
"""
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORES = os.cpu_count()
DEFAULT = {"inter": 2, "intra": CORES // 2, "beam": 3, "batch": 8}
VARIATIONS = {
    "intra": [1, 2, CORES // 2, CORES],
    "batch": [1, 4, 8, 16],
    "beam": [1, 3, 5],
}
PARAGRAPH_WORDS, TEXT_WORDS, REPEATS_OF_TEXT = 100, 2000, 8
RUNS = 3


def peak_bytes():
    """Peak memory of this process; macOS reports bytes, Linux kilobytes"""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def sentences_up_to(flores, words, start=0):
    """Consecutive devtest sentences, grouped into lines of about 5 sentences, with the given number of words"""
    with open(os.path.join(flores, "flores200_dataset", "devtest", "eng_Latn.devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    chosen, count = [], 0
    for line in lines[start:]:
        chosen.append(line)
        count += len(line.split())
        if count >= words:
            break
    return ["  ".join(chosen[i : i + 5]) for i in range(0, len(chosen), 5)]


def run_text(engine_module, translator, text, config, deduplicate=True):
    """Translate a text as the app does; returns the translated text"""
    from utils.paragraph_splitter import paragraph_detokenizer

    engine_module.BATCH_SENTENCES = config["batch"]
    sentences, breaks, batches, _ = translator.split(text, "en")
    if deduplicate:
        translations = translator.translate(batches, config["beam"], "fra_Latn", "eng_Latn")
    else:
        translations = []
        for batch in batches:
            translations.extend(translator.translate_batch(batch, config["beam"], "fra_Latn", "eng_Latn"))
    return paragraph_detokenizer(translations, breaks)


def timed(function, runs):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        function()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def measure(model_dir, flores, config, repeated):
    sys.path.insert(0, ROOT)
    import ctranslate2

    import engine

    result = {"load_average": os.getloadavg()[0]}
    translator = engine.Engine()
    start = time.perf_counter()
    translator.load_model(model_dir)
    translator.translator = ctranslate2.Translator(model_dir, device="cpu", inter_threads=config["inter"], intra_threads=config["intra"])
    translator.load_sp_model(os.path.join(model_dir, "sentencepiece.model"))
    result["load_seconds"] = time.perf_counter() - start

    unit = sentences_up_to(flores, 1)[0].split("  ")[0]  # one sentence
    start = time.perf_counter()
    translator.translate_batch([unit], config["beam"], "fra_Latn", "eng_Latn")
    result["first_seconds"] = time.perf_counter() - start
    result["sentence_seconds"] = timed(lambda: translator.translate_batch([unit], config["beam"], "fra_Latn", "eng_Latn"), 5)

    paragraph = "\n".join(sentences_up_to(flores, PARAGRAPH_WORDS, start=50))
    result["paragraph_words"] = len(paragraph.split())
    result["paragraph_seconds"] = timed(lambda: run_text(engine, translator, paragraph, config), 5)

    text = "\n".join(sentences_up_to(flores, TEXT_WORDS, start=100))
    result["text_words"] = len(text.split())
    seconds = timed(lambda: run_text(engine, translator, text, config), RUNS)
    result["words_per_second"] = result["text_words"] / seconds

    if repeated:
        part = "\n".join(sentences_up_to(flores, TEXT_WORDS // REPEATS_OF_TEXT, start=100))
        text = "\n".join([part] * REPEATS_OF_TEXT)
        result["repeated_words"] = len(text.split())
        for name, deduplicate in (("deduplicated", True), ("not_deduplicated", False)):
            result["repeated_seconds_" + name] = timed(lambda: run_text(engine, translator, text, config, deduplicate), RUNS)
        same = run_text(engine, translator, text, config, True) == run_text(engine, translator, text, config, False)
        result["repeated_output_equal"] = same

    result["peak_bytes"] = peak_bytes()
    return result


def machine():
    import ctranslate2
    import sentencepiece

    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cores": CORES,
        "python": platform.python_version(),
        "ctranslate2": ctranslate2.__version__,
        "sentencepiece": sentencepiece.__version__,
    }


def configurations():
    """The default, then the default with one setting changed"""
    configs = [("default", dict(DEFAULT))]
    for key, values in ({} if os.environ.get("BENCHMARK_ONLY_DEFAULT") else VARIATIONS).items():
        for value in values:
            if value != DEFAULT[key]:
                configs.append(("%s=%s" % (key, value), dict(DEFAULT, **{key: value})))
    return configs


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        print(json.dumps(measure(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), sys.argv[5] == "repeated")))
        sys.exit(0)
    flores, output, models = os.path.abspath(sys.argv[1]), sys.argv[2], [os.path.abspath(m) for m in sys.argv[3:]]
    sys.path.insert(0, ROOT)
    results = {"machine": machine(), "models": {}}
    for model in models:
        name = os.path.basename(model)
        results["models"][name] = {}
        for label, config in configurations():
            args = [sys.executable, __file__, "--child", model, flores, json.dumps(config), "repeated" if label == "default" else "plain"]
            out = subprocess.run(args, capture_output=True, text=True, check=True)
            r = json.loads(out.stdout.strip().splitlines()[-1])
            r["config"] = config
            results["models"][name][label] = r
            print("%-28s %-10s load %5.1f s, sentence %5.2f s, paragraph %5.1f s, %6.1f words/s, peak %.2f GB" % (
                name, label, r["load_seconds"], r["sentence_seconds"], r["paragraph_seconds"], r["words_per_second"], r["peak_bytes"] / 1e9), flush=True)
            with open(output, "w", encoding="utf-8") as file:
                json.dump(results, file, indent=2)
        r = results["models"][name]["default"]
        print("Repeated text: %.1f s deduplicated, %.1f s without; same output: %s" % (
            r["repeated_seconds_deduplicated"], r["repeated_seconds_not_deduplicated"], r["repeated_output_equal"]))
    print("Default: %s. Seconds are medians of %d runs for the text, 5 for sentences and paragraphs." % (DEFAULT, RUNS))
