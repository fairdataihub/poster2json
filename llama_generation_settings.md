# Llama 3.1 8B Generation Settings

Reference for the JSON-structuring model in poster2json: which generation knobs we set, their values, and *why* each one matters for getting complete, deterministic JSON out of a stock instruct model.

> **The model is not fine-tuned.** `JSON_MODEL_ID = "fairdataihub/Llama-3.1-8B-Poster-Extraction"` is a verbatim mirror of Meta's `Llama-3.1-8B-Instruct`. All extraction quality comes from the prompt + the generation settings below, not from weight tuning. Any HuggingFace instruct model can be swapped in via `--model`.

All settings live in `poster2json/extract.py`. Code anchors are given per setting (line numbers approximate).

---

## Summary table

| Setting | Value | Where |
|---------|-------|-------|
| Decoding | greedy (`do_sample=False`) | `_generate()`, line 1357 |
| Sampling params | none (no `temperature` / `top_p` / `top_k` / `num_beams`) | `_generate()` |
| Primary output budget | `MAX_JSON_TOKENS = 18000` | line 46 |
| Retry/fallback budget | `MAX_RETRY_TOKENS = 24000` | line 47 |
| Input gate | `MAX_INPUT_TOKENS = 15000` | line 48 |
| EOS handling | `_JsonBraceProcessor` (custom `LogitsProcessor`) | line 1282 |
| Default quantization | 4-bit NF4 (`bnb_4bit_compute_dtype=bfloat16`, double-quant) | `load_json_model()`, line 1227 |
| Alt quantization | `8bit`, `fp16` (bf16) via `--quantization` | line 1224 / 1235 |
| Attention | Flash Attention 2 when installed, else default | line 1208 |
| Native context | 128K (model default; not overridden) | — |

---

## Decoding: greedy, deterministic

```python
outputs = model.generate(
    **inputs,
    max_new_tokens=max_tokens,
    do_sample=False,          # greedy
    pad_token_id=tokenizer.eos_token_id,
    streamer=streamer,
    logits_processor=LogitsProcessorList([processor]),
)
```

`do_sample=False` → greedy decoding. No `temperature`, `top_p`, `top_k`, or `num_beams` are passed.

**Why:**
- **Determinism.** The same poster text yields byte-identical JSON every run. This is what makes the validation set trustworthy and lets us isolate the blast radius of a change — if a prompt or extraction tweak only affects 3 posters, the other 17 outputs are unchanged bit-for-bit.
- **Structured extraction favors greedy.** We want the single most-likely faithful transcription of the poster, not creative variation. Sampling buys diversity we don't want and raises the rate of malformed JSON.

## EOS suppression: the brace-balance processor

This is the single most important fix for truncated JSON. `_JsonBraceProcessor` (a `LogitsProcessor`) tracks JSON brace depth across the generated tokens and forces the logits of **all** EOS tokens to `-inf` until the outermost object closes (depth returns to 0).

**Why:** Llama 3.1 has three EOS-like tokens — `<|end_of_text|>` (128001), `<|eom_id|>` (128008), `<|eot_id|>` (128009). HuggingFace's `min_new_tokens` only suppresses the primary one, so the model would hit `<|eot_id|>` early and emit truncated JSON. We collect all three in `_get_eos_token_ids()` (line 1267) and suppress every one until the JSON is structurally complete. The processor also tracks string state (`"` toggles, `\` escapes) so braces inside string values don't fool the depth counter.

## Token budgets

| Constant | Value | Role |
|----------|-------|------|
| `MAX_JSON_TOKENS` | 18000 | First-pass output budget. Posters routinely produce large JSON (many sections + captions + references). |
| `MAX_RETRY_TOKENS` | 24000 | Used on retry and on the fallback-prompt pass, for posters whose JSON gets truncated at 18k. |
| `MAX_INPUT_TOKENS` | 15000 | Input gate. Posters longer than this are rejected with `INPUT_TOO_LONG` rather than silently truncated — a truncated prompt produces confidently-wrong JSON, which is worse than an explicit error. |

The model's native context is 128K, so 15k-in + 24k-out sits comfortably inside it; the gates are about output completeness and failing loudly, not context limits.

### Retry ladder

`extract_json_with_retry()` (line 2251) escalates only when the parse fails or the output looks truncated:

1. **Primary** — full `EXTRACTION_PROMPT` @ `MAX_JSON_TOKENS` (18k).
2. **Retry** — same full prompt @ `MAX_RETRY_TOKENS` (24k), if step 1 errored or truncated.
3. **Fallback** — shorter `FALLBACK_PROMPT` @ `MAX_RETRY_TOKENS` (24k), if step 2 still errored or truncated.

Each step is followed by `_robust_json_parse()` (hand-rolled repair passes, then the `json-repair` library as a last resort). The ladder is cheap in the common case — most posters succeed on step 1 and never pay for the retries.

## Quantization

Default is **4-bit NF4**:

```python
BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)
```

**Why 4-bit default:** fits the 8B model in ~6GB VRAM, which drops the PDF-pipeline floor to ~8GB cards. Extraction quality held up on the canary set at 4-bit, so it became the default in v0.3.0.

Override with `--quantization`:
- `8bit` — `BitsAndBytesConfig(load_in_8bit=True)`.
- `fp16` — bf16 weights (`torch_dtype=torch.bfloat16`), highest fidelity, needs ≥16GB.

Flash Attention 2 is used automatically when `flash_attn` is importable; otherwise it falls back to default attention with no behavior change.

---

## What we deliberately did *not* do

- **No fine-tuning.** See note at top — stock instruct weights.
- **No sampling.** Greedy only; reproducibility beats diversity for this task.
- **No `min_new_tokens` for completeness.** It only guards one EOS token; the brace processor is the correct mechanism.
- **No silent input truncation.** Over-long posters error out instead of being cut.

## See also

- [crosswalk.md](crosswalk.md) — text-extraction (pdfplumber / XY-cut) parameter reference.
- [docs/architecture.md](docs/architecture.md) — Stage 2 (JSON structuring) overview.
- [docs/evaluation.md](docs/evaluation.md) — validation metrics and current scores.
