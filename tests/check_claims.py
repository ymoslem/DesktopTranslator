"""Check the claims that the README, the CHANGELOG and the tooltips of the app make about measured results.

Usage: python tests/check_claims.py

It reads the files in results/ (see results/README.md), recomputes what it can, and stops with an error
if a claim and the results disagree. The claims are
  - a single word is detected correctly about 60% of the time (CHANGELOG)
  - beam size 1 scores lower than beam size 3 in French, Arabic, Turkish and Hindi, with chrF++ and COMET
  - beam sizes 2 and 5 are comparable to beam size 3 (CHANGELOG, tooltip of Translation quality)
  - a larger beam size takes longer (tooltip of Translation quality, README)
  - a model on a GPU runs as float16, tested on an NVIDIA RTX 5090 with Linux (CHANGELOG, README)
  - on a GPU, 128 sentences per call with 4,096 tokens run about 4 times as fast as the CPU settings (engine.py, CHANGELOG)
  - on one machine, with 8 sentences per batch, the GPU is about 7 times as fast as a CPU with 16 threads and about 15 times as fast as one with 4 threads
  - with those settings, chrF++ is within 0.05 of the CPU settings and the difference is comparable (engine.py)
  - the int8 files run as float16 are comparable to a model converted straight to float16 (README)
"""
import json
import os
import random

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
LANGUAGES = ("French", "Arabic", "Turkish", "Hindi")
BEAMS = ("1", "2", "3", "5")
RESAMPLES, TOLERANCE = 1000, 1e-9


def load(name):
    with open(os.path.join(RESULTS, name), encoding="utf-8") as file:
        return json.load(file)


def bootstrap(scores_a, scores_b):
    """The paired bootstrap of tests/comet_beam.py: the difference in the mean with a 95% interval"""
    rng, n = random.Random(1), len(scores_a)
    differences = []
    for _ in range(RESAMPLES):
        chosen = [rng.randrange(n) for _ in range(n)]
        differences.append(sum(scores_a[i] - scores_b[i] for i in chosen) / n)
    differences.sort()
    return differences[int(0.025 * RESAMPLES)], differences[int(0.975 * RESAMPLES) - 1]


def check(condition, claim):
    assert condition, "FAILED: " + claim
    print("ok   " + claim)


def main():
    lid = load("lid_confidence.json")
    accuracy = lid["by_length"]["1"]["accuracy"]
    check(abs(accuracy - 0.60) < 0.05, "a single word is detected correctly about 60%% of the time (%.1f%%)" % (100 * accuracy))

    beam, comet = load("beam_nllb600_m3.json"), load("comet_beam_nllb600_m3.json")
    check(beam["model"] == "nllb-200-distilled-600M-int8" and set(beam["scores"]) == set(LANGUAGES) and beam["sentences"] == 200,
          "the beam results are for NLLB-200 600M, four languages, 200 sentences")
    for name in LANGUAGES:
        segments = comet["segments"][name]
        for other in ("1", "2", "5"):  # the stored COMET intervals are what the segment scores give
            low, high = bootstrap(segments[other], segments["3"])
            stored = comet["bootstrap_vs_beam_3"][name][other]
            check(abs(low - stored["low"]) < TOLERANCE and abs(high - stored["high"]) < TOLERANCE,
                  "%s, beam size %s: the COMET interval is recomputed from the segment scores" % (name, other))
        for metric, stats in (("chrF++", beam["bootstrap_vs_beam_3"][name]), ("COMET", comet["bootstrap_vs_beam_3"][name])):
            one = stats["1"]
            check(one["high"] < 0, "%s, beam size 1 scores lower than 3 (%s, interval [%.4f, %.4f])" % (name, metric, one["low"], one["high"]))
            for other in ("2", "5"):
                interval = stats[other]
                check(interval["low"] <= 0 <= interval["high"],
                      "%s, beam size %s is comparable to 3 (%s, interval [%.4f, %.4f])" % (name, other, metric, interval["low"], interval["high"]))
        times = [beam["seconds"][name][b] for b in BEAMS]
        check(times == sorted(times), "%s, a larger beam size takes longer (%s s)" % (name, ", ".join("%.0f" % t for t in times)))

    gpu = load("gpu_check_rtx5090_linux.json")
    check("RTX 5090" in gpu["machine"]["gpus"][0] and gpu["machine"]["platform"].startswith("Linux"), "the GPU results are from an NVIDIA RTX 5090 with Linux")
    rows = gpu["rows"]
    check(rows["app"]["device_used"] == "cuda" and rows["app"]["chrf"] == rows["float16"]["chrf"]
          and rows["float16"]["same_as_first"] == gpu["sentences"], "the app runs a model on the GPU as float16, with the same translations")

    sweep = load("gpu_batch_rtx5090_linux.json")
    speed = {(r["sentences_per_call"], r["token_limit"]): r["words_per_second"] for r in sweep["rows"]}
    ratio = speed[(128, 4096)] / speed[(8, 1024)]
    check(round(ratio) == 4 and sweep["default"] == {"sentences_per_call": 8, "token_limit": 1024},
          "128 sentences with 4,096 tokens run %.2f times as fast as 8 sentences with 1,024" % ratio)
    alternating = load("gpu_batch_ab_rtx5090_linux.json")
    check(round(alternating["ratio"]) == 4 and len(alternating["words_per_second"]["gpu settings"]) == alternating["rounds"] == 5
          and min(alternating["words_per_second"]["gpu settings"]) > max(alternating["words_per_second"]["cpu settings"]),
          "alternating rounds on one pod: %.2f times as fast, and every run of the GPU settings beats every run of the CPU settings" % alternating["ratio"])
    for cores, expected in ((32, 7), (8, 15)):
        same = load("gpu_cpu_same_machine_rtxpro4500_linux_%dcores.json" % cores)
        runs, ratios = same["words_per_second"], same["ratios"]
        check(same["machine"]["cores_assumed"] == cores and same["devices"] == {"cpu": "cpu", "gpu": "cuda"}, "%d cores: the CPU and the GPU of one machine" % cores)
        check(round(ratios["gpu 8 over cpu 8"]) == expected and min(runs["gpu, 8 sentences"]) > max(runs["cpu, 8 sentences"]),
              "%d cores, 8 sentences per batch: the GPU is %.1f times as fast as the CPU, in every run" % (cores, ratios["gpu 8 over cpu 8"]))
        check(round(ratios["gpu 128 over gpu 8"]) == 4 and min(runs["gpu, 128 sentences"]) > max(runs["gpu, 8 sentences"]),
              "%d cores: on the GPU, 128 sentences per batch are %.1f times as fast as 8" % (cores, ratios["gpu 128 over gpu 8"]))
        check(same["paragraph_seconds"]["gpu"]["median"] < same["paragraph_seconds"]["cpu"]["median"],
              "%d cores: a paragraph of %d words takes %.2f s on the GPU and %.2f s on the CPU" % (
                  cores, same["paragraph_words"], same["paragraph_seconds"]["gpu"]["median"], same["paragraph_seconds"]["cpu"]["median"]))
    quality = load("gpu_batch_quality_rtx5090_linux.json")
    for name, pairs in quality["rows"].items():
        for pair in ("128,4096",):
            row = pairs[pair]
            check(abs(row["difference_from_default"]) <= 0.05 + 1e-9 and row["low"] <= 0 <= row["high"],
                  "%s, 128 sentences with 4,096 tokens: chrF++ difference %+.2f [%+.2f, %+.2f]" % (name, row["difference_from_default"], row["low"], row["high"]))
    weights = load("gpu_weights_rtx5090_linux.json")
    for name, row in weights["rows"].items():
        check(row["low"] <= 0 <= row["high"], "%s, int8 files as float16 against float16 weights: comparable (%+.2f [%+.2f, %+.2f])" % (name, row["difference"], row["low"], row["high"]))
    print("\nAll claims agree with the results.")


if __name__ == "__main__":
    main()
