"""Itemize the freeform 'Descritipion' column of the AutoPay dispute file with Jev.

Pipeline (one Jev request per unique description + reason code; questions run in parallel):
  row level   n_expenses  Score   how many distinct charges the text claims (0..5+)
              has_<cat>   Noul    one per big expense category
              max_range   Choice  log-spaced bucket of the largest single charge
  per number  role_<id>   Choice  charge / rate / total / reference / not_money
              cat_<id>    Choice  which category that number pays for
Code then builds the items table, multiplies rates by quantities, and reconciles each
original row's items against its Delta column (search over role assignments by joint
probability) so a disagreement between text and money is surfaced, not hidden.

Usage: python itemize.py [--limit N] [--workers 8]
"""
import argparse
import itertools
import json
import math
import re
from pathlib import Path

import pandas as pd

from candidates import annotate, find_candidates
from jev import ask_many

HERE = Path(__file__).parent
SRC = HERE / "AutoPay Dispute Data 20220815.xlsx"
OUT = HERE / "output"
DESC_COL = "Descritipion"

CATEGORIES = {
    "purchased_transportation": "Purchased transportation surcharge or purchase fee (PPG's 'PURCHASE(D) TRANSP(ORTATION) SURCHARGE/FEE', including misspellings)",
    "fuel_surcharge": "Fuel surcharge (FSC, 'FEUL', fuel), including a truckload FSC rate that should have applied",
    "linehaul_base_rate": "Line haul, base cost/rate, minimum charge, rate or contract-rate correction, reweigh or weight rerate, mileage rate, zip/lane factor",
    "detention": "Detention of a driver or equipment (waiting time at shipper/consignee), detention time",
    "storage_demurrage": "Storage, rail ramp storage, dwell days, demurrage, per diem (origin/destination), yard pull, pre-pull",
    "hazmat": "Hazardous materials (hazmat) charge",
    "tailgate": "Tailgate / liftgate delivery charge",
    "delivery_services": "Other delivery services: inside delivery, redelivery, special delivery, private residence delivery, heat or freezable protection",
    "lumper_handling": "Lumper, sortation, reservation or other freight handling fee at a facility",
    "port_drayage": "Port and container drayage charges: chassis, port termination, port congestion, bond",
    "tax": "Tax on charges: GST, HST, sales tax, 'TAX'",
    "other_surcharge": "Other surcharges or event fees: road closure (BC road closure), CV-19/COVID fee, truck ordered not used (TONU), cancellation",
    "unspecified_balance": "A short payment, unpaid invoice or balance due whose charge type is not named at all",
}
ROLES = {
    "charge": "A charge being claimed: the amount of one expense. A lone 'BALANCE DUE $X' or 'SHORT PAID X' with no other claimed amounts in the text is a charge.",
    "rate": "A per-unit rate (per day, per mile, 'each', '@ $X') that multiplies a quantity; the claimed amount is rate × quantity.",
    "total": "A total, subtotal or overall balance that adds up or covers OTHER claimed amounts that also appear as numbers in the text (e.g. after '=' or 'TOTAL'). Never a total when it is the only claimed amount.",
    "reference": "An amount mentioned only for context and not claimed now: already paid, approved, billed, adjusted off, overpayment, freight total, rate approval.",
    "not_money": "Not a money amount: a weight, count, identifier, percentage, date fragment or similar.",
}
RANGES = ["no_amount", "0-10", "10-25", "25-50", "50-100", "100-250", "250-500", "500-1000", "1000-2500", "2500+"]
RANGE_EDGES = [0, 10, 25, 50, 100, 250, 500, 1000, 2500, math.inf]
COUNT_LEVELS = [
    "0: no amount is claimed at all (empty, just a name, or a note with no charge)",
    "1: exactly one distinct expense or charge is claimed",
    "2: two distinct expenses or charges are claimed",
    "3: three distinct expenses or charges are claimed",
    "4: four distinct expenses or charges are claimed",
    "5: five or more distinct expenses or charges are claimed",
]
NONE_CAT = "none"
UNPRICED_MIN = 0.6  # min category Noul for an item that has no amount of its own


def range_of(v):
    if v is None:
        return "no_amount"
    v = abs(v)
    for lo, hi, name in zip(RANGE_EDGES, RANGE_EDGES[1:], RANGES[1:]):
        if lo <= v < hi:
            return name
    return RANGES[-1]


def build_request(desc, reason, cands):
    state = {
        "dispute_description": desc,
        "description_with_tagged_numbers": annotate(desc, cands),
        "reason_code": reason,
        "context": "Freight carrier invoice disputes for PPG. The description is a freeform note written by the carrier "
                   "or a planner explaining which charges on the invoice were unpaid or disputed. Several expenses may be "
                   "listed together, with totals, taxes, per-day rates and amounts that were already paid.",
    }
    q = {
        "n_expenses": {
            "type": "score",
            "instructions": "How many distinct expenses or charges does `dispute_description` claim? Count each separately "
                            "named charge type once (a tax counts as its own charge). Do not count totals, subtotals, per-day "
                            "rates or amounts mentioned only as already paid/approved/billed. A charge named without its own "
                            "amount (e.g. 'TAILGATE AND PURCHASE FEE BALANCE DUE $30') still counts. An amount claimed "
                            "without naming its charge type ('SHORT PAID 300.00', 'DISPUTE - UNPAID $500', a bare '56.56') "
                            "counts as one charge.",
            "criteria": COUNT_LEVELS,
        },
        "max_range": {
            "type": "choice",
            "instructions": "What is the largest single expense amount claimed in `dispute_description`? Use the amount of one "
                            "charge (rate × quantity when only a rate is given), not a total of several charges and not an amount "
                            "that was already paid or approved. Pick the range (in dollars) it falls in.",
            "criteria": {r: ("No money amount is claimed" if r == "no_amount" else f"From ${r.replace('-', ' up to $')}")
                         for r in RANGES},
        },
    }
    for cat, desc_cat in CATEGORIES.items():
        q[f"has_{cat}"] = {
            "type": "noul",
            "instructions": {"category": desc_cat,
                             "question": "Does `dispute_description` explicitly name an expense that belongs to `category` "
                                         "as something being claimed?"},
            "criteria": {"true": "The text names a charge of exactly this kind (misspellings count).",
                         "false": "No charge of this kind is named; related or merely similar charges do not count."},
        }
    for c in cands:
        near = f"'...{desc[max(0, c['start'] - 45):c['end'] + 20].strip()}...'"
        q[f"role_{c['id']}"] = {
            "type": "choice",
            "instructions": f"In `description_with_tagged_numbers`, what role does the number tagged {c['id']} "
                            f"('{c['text']}', in {near}) play?",
            "criteria": ROLES,
        }
        q[f"cat_{c['id']}"] = {
            "type": "choice",
            "instructions": f"In `description_with_tagged_numbers`, which expense category is the number tagged {c['id']} "
                            f"('{c['text']}', in {near}) the amount of? Use the charge named next to it. If it sums several categories or is not money, answer {NONE_CAT}.",
            "criteria": {**CATEGORIES, NONE_CAT: "Covers several categories, or is not a money amount of any category"},
        }
    return {"state": state, "questions": q}


def best_assignments(cands, answers, qtys):
    """Per candidate options: counted as charge (value), as rate (value × nearest qty), or excluded.

    Returns the argmax assignment and a function to find the best assignment matching a target sum."""
    opts = []
    for c in cands:
        p = answers[f"role_{c['id']}"]["probabilities"]
        qty = min(qtys, key=lambda q: abs(q[1] - c["start"]))[0] if qtys else 1
        o = [("charge", c["value"], p["charge"])]
        o.append(("rate", round(c["value"] * qty, 2), p["rate"]))
        o.append(("excluded", 0.0, p["total"] + p["reference"] + p["not_money"]))
        opts.append(o)

    def logp(assign):
        return sum(math.log(max(o[2], 1e-9)) for o in assign)

    argmax = [max(o, key=lambda x: x[2]) for o in opts]
    # A rate that explains a charge of the same category ("ADD $225 ... 3 DAYS AT $75") is not a second item.
    charge_cats = {answers[f"cat_{c['id']}"]["choice"] for c, o in zip(cands, argmax) if o[0] == "charge"}
    argmax = [o if not (o[0] == "rate" and answers[f"cat_{c['id']}"]["choice"] in charge_cats)
              else opt[2] for c, o, opt in zip(cands, argmax, opts)]

    def match(target, tol):
        if len(opts) > 9:
            return None
        best = None
        for assign in itertools.product(*opts):
            if abs(sum(o[1] for o in assign) - target) <= tol:
                if best is None or logp(assign) > logp(best):
                    best = assign
        return best

    return argmax, match, logp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N unique descriptions (pilot)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    df = pd.read_excel(SRC)
    df.insert(0, "row_id", [f"R{i + 2:05d}" for i in range(len(df))])  # R00002 = Excel row 2
    df["desc_clean"] = df[DESC_COL].fillna("").astype(str).str.strip()
    uniq = df.drop_duplicates(["desc_clean", "Reason Code"])[["desc_clean", "Reason Code"]].reset_index(drop=True)
    if args.limit:
        uniq = uniq.sample(min(args.limit, len(uniq)), random_state=7).reset_index(drop=True)
    uniq["desc_id"] = [f"D{i + 1:04d}" for i in range(len(uniq))]

    parsed = [find_candidates(d) for d in uniq["desc_clean"]]
    payloads = [build_request(d, r, c) for d, r, (c, _) in zip(uniq["desc_clean"], uniq["Reason Code"], parsed)]
    responses = ask_many(payloads, workers=args.workers)

    desc_rows, cand_rows, jev_by_key = [], [], {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    for (_, u), (cands, qtys), resp in zip(uniq.iterrows(), parsed, responses):
        a = resp["answers"]
        for k in usage:
            usage[k] += resp.get("usage", {}).get(k, 0)
        n = a["n_expenses"]
        count_probs = {int(k): v for k, v in n["probabilities"].items()}
        rec = {
            "desc_id": u["desc_id"],
            "description": u["desc_clean"],
            "reason_code": u["Reason Code"],
            "n_candidates": len(cands),
            "jev_n_expenses": max(count_probs, key=count_probs.get),
            "jev_n_expenses_score": round(n["score"], 3),
            "jev_n_expenses_conf": round(n["confidence"], 3),
            **{f"p_n_{k}": round(v, 3) for k, v in sorted(count_probs.items())},
            "jev_max_range": a["max_range"]["choice"],
            "jev_max_range_conf": round(a["max_range"]["confidence"], 3),
            **{f"p_{c}": round(a[f"has_{c}"]["noul"], 3) for c in CATEGORIES},
        }
        desc_rows.append(rec)
        for c in cands:
            r, k = a[f"role_{c['id']}"], a[f"cat_{c['id']}"]
            cand_rows.append({
                "desc_id": u["desc_id"], "cand_id": c["id"], "text": c["text"], "value": c["value"],
                "role": r["choice"], "role_conf": round(r["confidence"], 3),
                **{f"p_role_{x}": round(v, 3) for x, v in r["probabilities"].items()},
                "category": k["choice"], "category_conf": round(k["confidence"], 3),
            })
        jev_by_key[(u["desc_clean"], u["Reason Code"])] = (u["desc_id"], cands, qtys, a, rec)

    # ---- per original row: items + reconciliation against Delta ----
    row_out, items = [], []
    for _, row in df.iterrows():
        key = (row["desc_clean"], row["Reason Code"])
        if key not in jev_by_key:
            continue
        desc_id, cands, qtys, a, rec = jev_by_key[key]
        delta = float(row["Delta"]) if pd.notna(row["Delta"]) else None
        argmax, match, logp = best_assignments(cands, a, qtys)
        chosen, method = argmax, "jev_argmax"
        argmax_sum = round(sum(o[1] for o in argmax), 2)
        if delta is not None and cands:
            tol = max(0.02, 0.005 * abs(delta))
            if abs(argmax_sum - abs(delta)) <= tol:
                method = "jev_argmax_matches_delta"
            else:
                m = match(abs(delta), tol)
                # Accept the delta-consistent assignment only if Jev found it at least somewhat plausible.
                if m is not None and logp(m) - logp(argmax) > math.log(0.02):
                    chosen, method = m, "reconciled_to_delta"
                elif argmax_sum and any(abs(argmax_sum * k - abs(delta)) <= tol for k in (2, 3, 4)):
                    method = "delta_is_multiple_of_items"  # e.g. the same invoice counted twice in Delta
                else:
                    method = "delta_mismatch"
        joint_p = math.exp(logp(chosen)) if cands else 1.0

        priced = []
        for c, (kind, amount, p) in zip(cands, chosen):
            if kind == "excluded":
                continue
            # Combine the per-number category distribution with the row-level presence Nouls.
            pc = a[f"cat_{c['id']}"]["probabilities"]
            cat = max(CATEGORIES, key=lambda k: pc.get(k, 0) * a[f"has_{k}"]["noul"])
            priced.append({"cand": c, "kind": kind, "amount": amount, "p": p, "category": cat})
        covered = {x["category"] for x in priced}
        # Expenses named without their own amount: only as many as Jev's count exceeds the priced items,
        # taken from the strongest uncovered category Nouls.
        n_missing = max(0, rec["jev_n_expenses"] - len(priced))
        uncovered = sorted((k for k in CATEGORIES if k not in covered and a[f"has_{k}"]["noul"] >= UNPRICED_MIN
                            and not (k == "unspecified_balance" and priced)),
                           key=lambda k: -a[f"has_{k}"]["noul"])
        unpriced = uncovered[:n_missing]
        n_items = len(priced) + len(unpriced)
        max_item = max((abs(x["amount"]) for x in priced), default=None)

        seq = 0
        for x in priced:
            seq += 1
            c = x["cand"]
            items.append({
                "item_id": f"{row['row_id']}-{seq:02d}", "row_id": row["row_id"], "desc_id": desc_id, "item_seq": seq,
                "category": x["category"], "amount": x["amount"], "amount_source": x["kind"],
                "source_text": c["text"], "source_span": f"{c['start']}:{c['end']}",
                "role_prob": round(x["p"], 3),
                "category_conf": round(a[f"cat_{c['id']}"]["confidence"], 3),
                "category_noul": round(a[f"has_{x['category']}"]["noul"], 3),
                "shares_amount_with_unpriced": bool(unpriced),
                "reconciliation": method,
            })
        for k in unpriced:
            seq += 1
            # An amount stated for this category but left out by the Delta reconciliation is kept, flagged.
            stated = next((c for c, o in zip(cands, chosen) if o[0] == "excluded"
                           and a[f"cat_{c['id']}"]["choice"] == k and a[f"role_{c['id']}"]["choice"] in ("charge", "rate")), None)
            items.append({
                "item_id": f"{row['row_id']}-{seq:02d}", "row_id": row["row_id"], "desc_id": desc_id, "item_seq": seq,
                "category": k, "amount": stated["value"] if stated else None,
                "amount_source": "stated_not_in_delta" if stated else "no_separate_amount",
                "source_text": stated["text"] if stated else None,
                "source_span": f"{stated['start']}:{stated['end']}" if stated else None,
                "role_prob": None, "category_conf": None,
                "category_noul": round(a[f"has_{k}"]["noul"], 3),
                "shares_amount_with_unpriced": True, "reconciliation": method,
            })

        count_ok = min(n_items, 5) == rec["jev_n_expenses"]  # top Score level is "5 or more"
        range_ok = range_of(max_item) == rec["jev_max_range"]
        if method in ("jev_argmax_matches_delta",) and count_ok and rec["jev_n_expenses_conf"] >= 0.6:
            status = "high"
        elif (method in ("jev_argmax_matches_delta", "reconciled_to_delta", "delta_is_multiple_of_items")
              and abs(min(n_items, 5) - rec["jev_n_expenses"]) <= 1):
            status = "medium"
        else:
            status = "low"
        row_out.append({
            "row_id": row["row_id"], "desc_id": desc_id, "description": row["desc_clean"], "reason_code": row["Reason Code"],
            "delta": delta, "items_sum": round(sum(x["amount"] for x in priced), 2), "argmax_sum": argmax_sum,
            "n_items": n_items, "n_priced": len(priced), "n_unpriced": len(unpriced),
            **{k: rec[k] for k in ("jev_n_expenses", "jev_n_expenses_score", "jev_n_expenses_conf")},
            "count_agrees": count_ok,
            "code_max_range": range_of(max_item), "jev_max_range": rec["jev_max_range"],
            "jev_max_range_conf": rec["jev_max_range_conf"], "range_agrees": range_ok,
            "reconciliation": method, "assignment_joint_prob": round(joint_p, 3), "status": status,
            **{k: rec[k] for k in rec if k.startswith("p_")},
        })

    OUT.mkdir(exist_ok=True)
    rows_df, items_df = pd.DataFrame(row_out), pd.DataFrame(items)
    desc_df, cand_df = pd.DataFrame(desc_rows), pd.DataFrame(cand_rows)
    original = df.drop(columns=["desc_clean"])
    with pd.ExcelWriter(OUT / "itemized.xlsx") as xw:
        items_df.to_excel(xw, sheet_name="items", index=False)
        rows_df.to_excel(xw, sheet_name="row_summary", index=False)
        cand_df.to_excel(xw, sheet_name="number_candidates", index=False)
        desc_df.to_excel(xw, sheet_name="unique_descriptions", index=False)
        original.to_excel(xw, sheet_name="original_with_row_id", index=False)
    for name, d in [("items", items_df), ("row_summary", rows_df), ("number_candidates", cand_df),
                    ("unique_descriptions", desc_df)]:
        d.to_csv(OUT / f"{name}.csv", index=False)
    # Full Jev answers per unique description, for the dashboard's per-row tree.
    (OUT / "jev_answers.json").write_text(json.dumps({
        desc_id: {"candidates": [{k: c[k] for k in ("id", "text", "value", "start", "end")} for c in cands],
                  "quantities": qtys, "answers": a}
        for desc_id, cands, qtys, a, _ in jev_by_key.values()}))
    (OUT / "meta.json").write_text(json.dumps({
        "categories": CATEGORIES, "roles": ROLES, "ranges": RANGES, "count_levels": COUNT_LEVELS,
        "usage": usage, "n_requests": len(payloads), "n_rows": len(rows_df), "n_items": len(items_df),
    }, indent=2))

    print(f"\nrows {len(rows_df)}  items {len(items_df)}  unique descriptions {len(desc_df)}  usage {usage}")
    print("\nstatus:\n", rows_df["status"].value_counts().to_string())
    print("\nreconciliation:\n", rows_df["reconciliation"].value_counts().to_string())
    print("\nJev expense count (rows):\n", rows_df["jev_n_expenses"].value_counts().sort_index().to_string())
    print(f"\ncount agrees with itemization: {rows_df['count_agrees'].mean():.1%}   "
          f"range agrees: {rows_df['range_agrees'].mean():.1%}")


if __name__ == "__main__":
    main()
