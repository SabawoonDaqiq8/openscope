# AI-assisted Scope 3 spend classification

Most companies start Scope 3 from their purchase ledger: thousands of lines like
`CloudStack Inc · Annual SaaS subscription · 6300 Software subscriptions · 36,000 USD`. Each
line has to be (a) kept or excluded, (b) assigned one of the 15 GHG Protocol categories, and
(c) matched to a spend-based emission factor. Done by hand this takes days, and it is hard to
make consistent and auditable.

openscope automates it with a **hybrid pipeline** that keeps a human in charge.

```
ledger CSV ──► rules ──► supplier memory ──► Claude ──► confidence gate ──► review CSV
                (exact)    (reviewed before)   (batched,        │                │
                                                schema-bound)   │      reviewer edits in Excel
                                                                ▼                ▼
                                                         auto-accepted    review-apply ──► audit log (JSONL)
                                                                                 │     ──► supplier memory
                                                                                 ▼
                                                                    spend-based activities ──► calculate
```

## Stages

| Stage | What it does | Why |
|---|---|---|
| **Rules** | Regex on GL account, account name, supplier or description. Bundled rules exclude payroll, taxes, depreciation, finance costs, intercompany transfers, donations and refunds. | Your chart of accounts already encodes a lot. Rules are free, exact and explainable. |
| **Supplier memory** | Reuses a reviewer's earlier decision for the same (normalised) supplier. | Ledgers are dominated by repeat suppliers; humans review each one once. |
| **Claude** | Classifies the remaining lines in batches. | Handles the long tail of free-text descriptions. |
| **Confidence gate** | Model decisions below the threshold (default 0.85), or "classify" decisions without a factor, go to review. | You tune the trade-off between automation and risk. |
| **Review** | The reviewer accepts, overrides or excludes lines in a CSV. Decisions are validated and logged. | The audit trail records who decided what, when and why. |

## Model integration

* **Constrained output.** The response must match a JSON schema whose `factor_id` enum holds
  only the spend-based factors in your registry, and whose category enum is 0–15. The model
  cannot invent a factor. Results are matched back to lines by `line_id`; unknown or duplicate
  ids are ignored.
* **Prompt caching.** The system prompt (instructions, category guide, factor catalogue) is
  byte-identical for every batch and marked `cache_control`; only the batch of lines changes.
* **Cost and effort.** The default is `claude-opus-5-5` at `effort=low`. Classification gains
  little from deep reasoning. Tune `--model`, `--effort` and `--batch-size` against the eval.
* **Failure handling.** If a batch ends in a refusal, hits `max_tokens` or returns unparseable
  output, its lines are not guessed. They go to review, and the failure is reported. Server-side
  refusal fallbacks are on by default.
* **Prompt-injection hygiene.** Ledger text comes from third-party invoices. It is passed as
  JSON data in the user turn, and the system prompt tells the model not to follow instructions
  inside it. Because the output is schema-bound to a closed set of values, an injected
  instruction can at most mis-classify a line, and that is what review and the eval are for.
* **Scope 1/2 energy bills** (electricity, gas, fuel) are excluded from spend-based Scope 3 on
  purpose. They belong in Scope 1/2 from kWh or litres activity data.

## Measuring it

```bash
openscope classify examples/ledger_sample.csv \
  --factors examples/spend_factors_example.csv \
  --rules examples/classification_rules_example.csv \
  --out review.csv --labels examples/ledger_sample_labels.csv [--llm]
```

* **accuracy**: decision and category correct, over all labelled lines
* **coverage**: share of lines decided without human review
* **auto-accept precision**: accuracy on the lines that skip review. This is the number that
  tells you whether the threshold is safe; keep it close to 1.0.

Baseline on the bundled 40-line sample, rules only: coverage 37.5%, auto-accept precision 100%.
Run with `--llm` (needs `ANTHROPIC_API_KEY` and `pip install 'openscope[ai]'`) to measure the
hybrid pipeline. The sample is small and synthetic, so build a labelled sample from your own
ledger before trusting any threshold.

### Benchmark script

```bash
export ANTHROPIC_API_KEY=...            # your key; never commit it
python scripts/benchmark_classifier.py --models claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5
```

This runs rules-only, Claude-only and hybrid configurations on the labelled sample, re-scores
each at thresholds from 0.5 to 0.95 (no extra API calls) and writes
`docs/benchmarks/classifier.md` plus the raw model output in `classifier-results.json`.
`--rules-only` needs no key.

Model-reported confidence is not a calibrated probability. Pick the threshold from the
auto-accept precision on labelled data, not from the number alone.

## Review CSV

Rows needing review come first, sorted by spend. Fill in `review_action`:

| review_action | also fill | effect |
|---|---|---|
| `accept` | – | Keep the proposal (only if it has a category and factor) |
| `override` | `review_category`, `review_factor_id`, `review_note` | Replace the proposal |
| `exclude` | `review_note` | Not a Scope 3 purchase |
| *(blank)* | – | No decision; pending lines are not exported |

```bash
openscope review-apply review.csv --reviewer "Your Name" \
  --activities-out spend_activities.csv --audit-log audit.jsonl --memory suppliers.json \
  --factors examples/spend_factors_example.csv
openscope calculate spend_activities.csv --factors examples/spend_factors_example.csv
```
