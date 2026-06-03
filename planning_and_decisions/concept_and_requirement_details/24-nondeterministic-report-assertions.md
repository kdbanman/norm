# 24 — Asserting on reports despite LLM nondeterminism

- **Type:** Verification approach (testing principle)
- **Affects:** REQ-PREPROCESS-001, REQ-INTERVAL-001, anything that checks report output

## The gap

Reports are markdown emitted by a multimodal model. The **content is nondeterministic**, so no
test may assert on the *text* of a report. Yet several requirements are "about" reporting. We
need a principle for what is fair to assert.

## Principle (suspected)

Assert only on **structure and side effects** and on **inputs to `generate()`**, never on
generated prose:

- **Structural/side-effect:** a markdown blob was written; it's **encrypted** [18]; correct
  **row count** (= window count [04]); correct row fields (`window_start/end`, `capture_ids`,
  `model`, `prompt_id`); exit code; stdout-vs-`--output` routing (REQ-INTERVAL-005).
- **Input-side:** via the seam in [16] — `generate()` received both modalities, the configured
  prompt, the configured `model_ref`.
- **Determinism aid:** the **fake model [16]** returns a fixed canned markdown, which lets even
  shape-level checks ("output equals the canned string," "interval received preprocess
  markdown N..M") become exact and stable. Real-weights runs are reserved for occasional
  smoke tests that assert only "non-empty markdown, exit 0."

Document this as a standing convention so no one writes a brittle content assertion.

## Resolution

TODO
