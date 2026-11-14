# Measured results

Numbers behind the claims in the README, the CHANGELOG, and the tooltips of the app. `tests/check_claims.py` re-derives them and fails if a claim and the results disagree.

| File | Produced by | Contents |
|---|---|---|
| `beam_nllb600_m3.json` | `tests/beam_eval.py` | chrF++ and time of NLLB-200 distilled 600M (int8) with beam sizes 1, 2, 3 and 5 on 200 FLORES-200 devtest sentences into French, Arabic, Turkish and Hindi, and the paired bootstrap against beam size 3. Measured on an Apple M3 with 16 GB, CTranslate2 4.8.4, while other programs were open, so the times are comparable with each other only |
| `comet_beam_nllb600_m3.json` | `tests/comet_beam.py` | COMET-22 scores of the same translations, per segment and per system, and the paired bootstrap |
| `cometenv_freeze.txt` | `pip freeze` | The versions of the libraries used for COMET |
| `gpu_check_rtx5090_linux.json` | `tests/gpu_check.py` | English to French on an NVIDIA RTX 5090 with Linux, for each compute type |
| `gpu_batch_rtx5090_linux.json` | `tests/gpu_batch_eval.py` | Words per second, time per call and GPU memory of NLLB-200 600M on the RTX 5090 for 4 to 256 sentences per call and three token limits, on a text of 2,029 words |
| `gpu_batch_ab_rtx5090_linux.json` | `tests/gpu_batch_ab.py` | Words per second of the settings of the CPU (8 sentences per call) and of the GPU (128 sentences or 4,096 tokens) in 5 alternating rounds on one pod, and the ratio of the medians |
| `gpu_batch_quality_rtx5090_linux.json` | `tests/gpu_batch_quality.py` | chrF++ of 600 sentences into French and Arabic with larger batches, the number of sentences that change, and the paired bootstrap against the setting of the CPU |
| `gpu_weights_rtx5090_linux.json` | `tests/gpu_weights_eval.py` | chrF++ of the int8 files run as float16, against a model converted straight to float16, on the same 600 sentences |
| `lid_confidence.json` | `tests/lid_eval.py` | Accuracy of the language detection for texts of 1 to 10 words and for whole sentences, with the share of texts above probability thresholds |

The FLORES-200 text is released under CC BY-SA and is not stored here. The files in this folder have the translations and the examples of wrong detections removed, so the chrF++ intervals can be checked against the stored values only, and the COMET intervals are recomputed from the stored segment scores. To reproduce a result from the start, run the script named in the table with the FLORES-200 data from https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz.
