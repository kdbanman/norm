# 03 — What exactly is `prompt_id`?

- **Type:** Spec clarification
- **Affects:** concept §6 (data model), REQ-PREPROCESS-001, REQ-CONFIG-003; relates to [02]

## What's unclear

The preprocess data model stores a `prompt_id`, but config only stores the **literal**
prompt text (`prompt_preprocess`, `prompt_interval`). There is no prompt table or registry,
and nothing defines how `prompt_id` is derived or what it references.

## Why it matters

`prompt_id` is part of how we detect that a prompt changed (see [02]). If it's undefined we
can't assert REQ-CONFIG-003 ("the new prompt text was used") via row inspection, nor reason
about idempotency after a prompt edit.

## Options / suspected answer

- **(a) Content hash** *(suspected)* — `prompt_id = hash(effective_prompt_text)` (e.g., a
  short SHA-256 prefix). Editing the prompt changes the id automatically, which makes window
  invalidation in [02] fall out for free. Cheap, stateless, no registry needed.
- **(b) Monotonic config version** — a counter bumped whenever any prompt key changes. Works
  but couples the id to config history rather than to the prompt itself.
- **(c) Named enum** — only valid for a fixed prompt set; rejected since prompts are
  free-form, user-editable text.

Suggestion: also persist the **literal prompt text** (or store it addressably by its hash)
so `export` / debugging can show exactly what was sent to `generate()`.

## Resolution

TODO
