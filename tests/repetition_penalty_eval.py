"""Compare the translation scores with and without the repetition penalty, on the FLORES-200 test set.

Usage: python tests/repetition_penalty_eval.py FLORES_DIR FREN_DIR NLLB_600M_DIR NLLB_1.3B_DIR M2M_418M_DIR

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
It needs sacrebleu. The script fails if a penalty of 1.2 scores as well as no penalty (1.0) in chrF++.
"""
import os
import sys
import time

import ctranslate2
import sentencepiece as spm
from sacrebleu.metrics import CHRF, BLEU

FLORES, FREN, NLLB_600M, NLLB_13B, M2M = (os.path.abspath(a) for a in sys.argv[1:6])
SENTENCES, STEP, BEAM = 100, 10, 3
DEVTEST = os.path.join(FLORES, "flores200_dataset", "devtest")


def read(code):
    with open(os.path.join(DEVTEST, code + ".devtest"), encoding="utf-8") as file:
        return [line.rstrip("\n") for line in file][::STEP][:SENTENCES]


def score(translator, sp, source, reference, source_prefix, target_prefix, end, penalty):
    hypotheses = []
    for i in range(0, len(source), 8):
        batch = [([source_prefix] if source_prefix else []) + tokens + (["</s>"] if end else []) for tokens in sp.encode(source[i : i + 8], out_type=str)]
        results = translator.translate_batch(
            batch, target_prefix=[[target_prefix]] * len(batch) if target_prefix else None, beam_size=BEAM,
            repetition_penalty=penalty, max_batch_size=1024, batch_type="tokens", replace_unknowns=True,
        )
        for result in results:
            tokens = result.hypotheses[0][1:] if target_prefix else result.hypotheses[0]
            hypotheses.append("".join(tokens).replace("▁", " ").strip())
    return CHRF(word_order=2).corpus_score(hypotheses, [reference]).score, BLEU().corpus_score(hypotheses, [reference]).score


def translator_for(model):
    return ctranslate2.Translator(model, device="cpu", inter_threads=1, intra_threads=os.cpu_count() // 2)


nllb_sp = spm.SentencePieceProcessor(os.path.join(NLLB_600M, "sentencepiece.model"))
m2m_sp = spm.SentencePieceProcessor(os.path.join(M2M, "sentencepiece.model"))
fren_sp = spm.SentencePieceProcessor(os.path.join(FREN, "sp_model", "fr.model"))
english = read("eng_Latn")
cases = []  # name, translator, sp, source, reference, source prefix, target prefix, end of sentence token
for name, model in (("NLLB-200 600M", NLLB_600M), ("NLLB-200 1.3B", NLLB_13B)):
    translator = translator_for(model)
    for code, language in (("arb_Arab", "Arabic"), ("fra_Latn", "French")):
        cases.append((name + " English to " + language, translator, nllb_sp, english, read(code), "eng_Latn", code, True))
translator = translator_for(M2M)
for code, short, language in (("fra_Latn", "fr", "French"), ("arb_Arab", "ar", "Arabic")):
    cases.append(("M2M-100 418M English to " + language, translator, m2m_sp, english, read(code), "__en__", "__" + short + "__", False))
cases.append(("French to English model", translator_for(os.path.join(FREN, "ct2_model")), fren_sp, read("fra_Latn"), english, "", "", False))

failed = []
print("FLORES-200 devtest, %d sentences, beam %d (higher is better)" % (SENTENCES, BEAM))
for name, translator, sp, source, reference, source_prefix, target_prefix, end in cases:
    with_penalty = score(translator, sp, source, reference, source_prefix, target_prefix, end, 1.2)
    without = score(translator, sp, source, reference, source_prefix, target_prefix, end, 1.0)
    print("%-38s chrF++ %.1f -> %.1f | BLEU %.1f -> %.1f  (penalty 1.2 -> none)" % (name, with_penalty[0], without[0], with_penalty[1], without[1]), flush=True)
    if not without[0] > with_penalty[0]:
        failed.append(name)
print("\nNo penalty scored higher than 1.2 in chrF++ in %d of %d cases." % (len(cases) - len(failed), len(cases)))
sys.exit(1 if failed else 0)
