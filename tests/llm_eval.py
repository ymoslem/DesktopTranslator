"""Compare translation with large language models (as CTranslate2 int8 models) and NLLB-200, on FLORES-200.

Usage: python tests/llm_eval.py FLORES_DIR NLLB_DIR RESULTS.json [NAME=CT2_DIR=KIND[=TOKENIZER] ...]

FLORES_DIR holds flores200_dataset (https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz).
NLLB_DIR is a NLLB-200 CTranslate2 folder with sentencepiece.model, translated with a beam size of 3 as in the app.
Each NAME=CT2_DIR=KIND is a language model converted with ct2-transformers-converter. Its tokenizer is read from
CT2_DIR (copy the tokenizer files there when converting), or from TOKENIZER, a folder or a Hugging Face name. KIND is "generic" for a short instruction, "tgprompt" for the longer instruction of TranslateGemma as a
plain message (both work with any chat model), or "translategemma" for the format that TranslateGemma was trained with. The language models translate one sentence at a time, with greedy decoding,
or with beam search if the environment variable LLM_EVAL_BEAM is set to a beam size above 1. LLM_EVAL_SENTENCES sets the number of sentences (50 by default).
It needs transformers and sacrebleu. The results, with every translation, are saved to RESULTS.json.
"""
import json
import os
import sys
import time

import ctranslate2
import sentencepiece as spm
from sacrebleu.metrics import CHRF

SENTENCES, BATCH = int(os.environ.get("LLM_EVAL_SENTENCES", 50)), 8
BEAM = int(os.environ.get("LLM_EVAL_BEAM", 1))
SOURCE = ("eng_Latn", "en", "English")
TARGETS = [("fra_Latn", "fr", "French"), ("arb_Arab", "ar", "Arabic"), ("tur_Latn", "tr", "Turkish"), ("hin_Deva", "hi", "Hindi")]
PROMPT = "Translate the following text from {source} to {target}. Output only the translation.\n\n{text}"
# The instruction of the chat template of TranslateGemma, as a plain message for other models
TRANSLATEGEMMA_PROMPT = (
    "You are a professional {source} ({source_code}) to {target} ({target_code}) translator. Your goal is to accurately convey the "
    "meaning and nuances of the original {source} text while adhering to {target} grammar, vocabulary, and cultural sensitivities.\n"
    "Produce only the {target} translation, without any additional explanations or commentary. "
    "Please translate the following {source} text into {target}:\n\n\n{text}"
)


def read(flores, code):
    with open(os.path.join(flores, "flores200_dataset", "devtest", code + ".devtest"), encoding="utf-8") as file:
        lines = [line.rstrip("\n") for line in file]
    return lines[:: max(len(lines) // SENTENCES, 1)][:SENTENCES]  # evenly spaced; every 20th line for 50 sentences


def load_nllb(model_dir):
    sp = spm.SentencePieceProcessor(os.path.join(model_dir, "sentencepiece.model"))
    translator = ctranslate2.Translator(model_dir, device="cpu", inter_threads=2, intra_threads=os.cpu_count() // 2)
    return sp, translator


def translate_nllb(sp, translator, sources, target_code):
    outputs = []
    for i in range(0, len(sources), BATCH):
        batch = [[SOURCE[0]] + tokens + ["</s>"] for tokens in sp.encode(sources[i : i + BATCH], out_type=str)]
        results = translator.translate_batch(batch, beam_size=3, target_prefix=[[target_code]] * len(batch), replace_unknowns=True)
        outputs += ["".join(r.hypotheses[0][1:]).replace("▁", " ").strip() for r in results]
    return outputs


def build_prompt(tokenizer, kind, text, target):
    if kind == "translategemma":
        messages = [{"role": "user", "content": [{"type": "text", "source_lang_code": SOURCE[1], "target_lang_code": target[1], "text": text}]}]
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    template = TRANSLATEGEMMA_PROMPT if kind == "tgprompt" else PROMPT
    messages = [{"role": "user", "content": template.format(source=SOURCE[2], source_code=SOURCE[1], target=target[2], target_code=target[1], text=text)}]
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def translate_llm(generator, tokenizer, kind, sources, target):
    outputs = []
    for i in range(0, len(sources), BATCH):
        prompts = [build_prompt(tokenizer, kind, text, target) for text in sources[i : i + BATCH]]
        tokens = [tokenizer.convert_ids_to_tokens(tokenizer.encode(p, add_special_tokens=False)) for p in prompts]
        results = generator.generate_batch(tokens, max_length=300, sampling_topk=1, beam_size=BEAM, include_prompt_in_result=False)
        for result in results:
            ids = tokenizer.convert_tokens_to_ids(result.sequences[0])
            outputs.append(tokenizer.decode(ids, skip_special_tokens=True).strip())
    return outputs


def score(hypotheses, references):
    chrf = CHRF(word_order=2).corpus_score(hypotheses, [references]).score
    ratio = sum(len(h) for h in hypotheses) / max(sum(len(r) for r in references), 1)
    return round(chrf, 1), round(ratio, 2)


if __name__ == "__main__":
    flores, nllb, output = (os.path.abspath(a) for a in sys.argv[1:4])
    specs = [a.split("=") for a in sys.argv[4:]]
    sources = read(flores, SOURCE[0])
    references = {target[0]: read(flores, target[0]) for target in TARGETS}
    results = {}

    def run(name, translate, load_seconds):
        results[name] = {"load_seconds": round(load_seconds, 1), "seconds": 0.0, "scores": {}, "translations": {}}
        for target in TARGETS:
            start = time.time()
            hypotheses = translate(target)
            results[name]["seconds"] += time.time() - start
            results[name]["scores"][target[2]] = score(hypotheses, references[target[0]])
            results[name]["translations"][target[2]] = hypotheses
            print(name, target[2], "chrF++ %.1f, length ratio %.2f" % results[name]["scores"][target[2]], flush=True)
        results[name]["seconds"] = round(results[name]["seconds"])
        with open(output, "w", encoding="utf-8") as file:
            json.dump({"sentences": SENTENCES, "beam_size_llm": BEAM, "sources": sources, "references": references, "results": results}, file, ensure_ascii=False, indent=1)

    start = time.time()
    sp, translator = load_nllb(nllb)
    run("NLLB-200", lambda target: translate_nllb(sp, translator, sources, target[0]), time.time() - start)
    for name, ct2_dir, kind, *tokenizer_source in specs:
        from transformers import AutoTokenizer

        start = time.time()
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_source[0] if tokenizer_source else ct2_dir)
        generator = ctranslate2.Generator(ct2_dir, device="cpu", compute_type="int8", inter_threads=1, intra_threads=os.cpu_count())
        run(name, lambda target: translate_llm(generator, tokenizer, kind, sources, target), time.time() - start)
        del generator

    print("\n%-22s %s %-9s %s" % ("model", "".join("%-16s" % t[2] for t in TARGETS), "seconds", "loading"))
    for name, r in results.items():
        print("%-22s %s %-9s %s" % (name, "".join("%-16s" % ("%.1f (%.2f)" % tuple(r["scores"][t[2]])) for t in TARGETS), r["seconds"], r["load_seconds"]))
    print("chrF++ (length of the output relative to the reference); seconds are for translating %d sentences in %d languages, without loading" % (SENTENCES, len(TARGETS)))
