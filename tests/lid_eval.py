"""Measure how reliable the language detection of the app is for short texts, with FLORES-200.

Usage: python tests/lid_eval.py FLORES_DIR RESULTS.json

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
The detector is the fastText model of the app (utils/lid.176.ftz), asked for its best language with its
probability. Evenly spaced devtest sentences (LID_SENTENCES per language, 100 by default) of 14 languages are cut to
their first 1, 2, 3, 5 and 10 words, and the full sentence. Per length it records the accuracy of the best guess,
and, for several probability thresholds, the share of texts that reach the threshold and the accuracy among them.
Fragments of FLORES sentences are not the same as what people type, so the numbers show the trend only.
"""
import json
import os
import sys

import fasttext

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTENCES = int(os.environ.get("LID_SENTENCES", 100))
LENGTHS = (1, 2, 3, 5, 10, None)  # words; None is the whole sentence
THRESHOLDS = (0.3, 0.5, 0.7, 0.9)
LANGUAGES = {  # fastText code: FLORES file; languages that separate words with spaces
    "en": "eng_Latn", "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "nl": "nld_Latn", "pl": "pol_Latn", "hu": "hun_Latn", "tr": "tur_Latn", "ru": "rus_Cyrl", "ar": "arb_Arab",
    "hi": "hin_Deva", "id": "ind_Latn",
}


def read(flores, code):
    with open(os.path.join(flores, "flores200_dataset", "devtest", code + ".devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    return lines[:: max(len(lines) // SENTENCES, 1)][:SENTENCES]


def main(flores, output):
    model = fasttext.load_model(os.path.join(ROOT, "utils", "lid.176.ftz"))
    texts = {code: read(flores, flores_code) for code, flores_code in LANGUAGES.items()}
    results = {"sentences_per_language": SENTENCES, "languages": list(LANGUAGES), "by_length": {}}
    for length in LENGTHS:
        guesses = []  # (correct, probability)
        wrong_examples = []
        for code, sentences in texts.items():
            for sentence in sentences:
                text = " ".join(sentence.split()[:length]) if length else sentence
                # The app's call: the text in lower case, at most 200 characters
                prediction = model.f.predict(text[:200].lower().replace("\n", " "), 1, 0.0, "strict")
                probability, guess = (prediction[0][0], prediction[0][1][9:]) if prediction else (0.0, "none")  # no letters
                guesses.append((guess == code, probability))
                if guess != code and len(wrong_examples) < 8:
                    wrong_examples.append((text, code, guess, round(probability, 2)))
        row = {"texts": len(guesses), "accuracy": sum(c for c, _ in guesses) / len(guesses), "thresholds": {}}
        for threshold in THRESHOLDS:
            accepted = [c for c, p in guesses if p >= threshold]
            row["thresholds"][str(threshold)] = {
                "share_reaching": len(accepted) / len(guesses),
                "accuracy_among_them": sum(accepted) / len(accepted) if accepted else None,
            }
        row["wrong_examples"] = wrong_examples
        results["by_length"][str(length or "all")] = row
        print("%-4s words  accuracy %.3f  " % (length or "all", row["accuracy"]) + "  ".join(
            "p>=%.1f: %3.0f%% reach, %s correct" % (t, 100 * v["share_reaching"],
                                                    "n/a" if v["accuracy_among_them"] is None else "%.0f%%" % (100 * v["accuracy_among_them"]))
            for t, v in ((float(k), v) for k, v in row["thresholds"].items())), flush=True)
    with open(output, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
