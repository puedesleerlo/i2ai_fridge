# Dispute expense itemization with Jev

Splits the freeform `Descritipion` column of `AutoPay Dispute Data 20220815.xlsx` into one row per expense.

```
python itemize.py            # Jev calls (cached per question in cache/jev_cache.json) → output/*.csv, output/itemized.xlsx
python report.py             # output/report.html (overview)
python dashboard.py          # output/dashboard.html (per-row scores + itemization tree; open with #R00045 to jump to a row)
python itemize.py --limit 40 # pilot on a sample of unique descriptions
```

The API key is read from `../jev_exp/.env` (`JEV_API_KEY`). Override the path with `JEV_ENV=/path/.env`.

## How it works

1. **Candidates (code, `candidates.py`)**: finds every number that could be money, including `$1 277.68`, bare `56.56` and `.73`. Rules skip things that are never money: dates, times, `LBS`/`KG`/`%`, day counts, `CV 19`, ZIP codes and long IDs. Day counts are kept as quantities.
2. **Judgments (Jev, one request per unique description, all questions answered in parallel)**
   - `n_expenses`: Score from 0 to 5+, how many distinct charges the text claims (including charges named without their own amount)
   - `has_<category>`: one Noul per category (13 categories, listed in `output/meta.json`)
   - `max_range`: Choice over log-spaced buckets for the largest single charge: none, 0-10, 10-25, 25-50, 50-100, 100-250, 250-500, 500-1k, 1k-2.5k, 2.5k+
   - for each candidate number, `role` (charge / rate / total / reference / not_money) and `category`
3. **Composition (code, `itemize.py`)**: a charge becomes an item. A rate becomes an item worth rate × quantity, unless a charge of the same category already covers it. Expenses Jev counts but that have no amount become items with `amount = null`.
4. **Check against Delta**: each original row's items are compared with its `Delta`. If Jev's most likely roles don't add up, code searches the other role assignments Jev gave some probability, weighted by joint probability. Every row gets a `reconciliation` label and a `status` (high / medium / low).

## Outputs (`output/`)

| file / sheet | grain | key |
|---|---|---|
| `items` | one per expense | `item_id` = `row_id-seq`, links to `row_id` |
| `row_summary` | one per original row | `row_id` (R00002 = Excel row 2), count, confidence, category Nouls, range, status |
| `number_candidates` | one per number in each unique description | `desc_id`, `cand_id`, role and category probabilities |
| `unique_descriptions` | one per unique description | `desc_id` |
| `original_with_row_id` (xlsx) | original data plus `row_id` | |
