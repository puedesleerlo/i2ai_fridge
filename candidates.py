"""Code-side candidate finder: every number in a description that could be a money amount.

Tuned to over-find. Known non-money numbers (dates, times, weights, percentages, ids,
day counts, CV-19) are masked by rule; everything else becomes a candidate that Jev
labels (charge / rate / total / reference / not money).
"""
import re

# Masked first: never money. Order matters (longer patterns before shorter).
MASKS = [
    r"\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",   # 2022-03-14 10:00:00
    r"\d{1,2}/\d{1,2}/\d{1,2}/\d{1,2}",                          # 07/18/07/22 (two dates)
    r"\d{1,2}/\d{1,2}/\d{2,4}",                                  # 5/21/2022
    r"(?<![\d$.])\d{1,2}/\d{1,2}(?![\d/])",                      # 02/22
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?",                    # 11:22:00 PM
    r"CV\s?-?\s?19",                                             # CV 19 fee
    r"ZIP\s+\d+",                                                # ZIP 33101
    r"#\s*\d{6,}",                                               # PYMT ADVICE # 2400300373
]
MASK_RE = re.compile("|".join(f"(?:{m})" for m in MASKS), re.I)

# A number: optional sign and $, space-grouped thousands ("8 400.00", "26 901"),
# plain ints/decimals, or a bare decimal (".73").
NUM_RE = re.compile(
    r"(?P<sign>-\s?)?(?P<dollar>\$\s?)?"
    r"(?P<num>\d{1,3}(?: \d{3})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?|\.\d+)"
)
UNIT_AFTER = re.compile(r"\s*(?:LBS?\b|KGS?\b|KG|%|DAYS?\b|DAY\(S\)|DWELL DAY)", re.I)
QTY_RE = re.compile(r"(?<![\d.$])(\d+)\s*(?:DWELL\s+)?(?:DAYS?\b|DAY\(S\))", re.I)


def _mask(text):
    return MASK_RE.sub(lambda m: "\x00" * len(m.group()), text)


def find_candidates(text):
    """Return (candidates, [(quantity, position)]). Each candidate keeps its verbatim span."""
    text = text or ""
    masked = _mask(text)
    cands = []
    for m in NUM_RE.finditer(masked):
        if "\x00" in m.group():
            continue
        start, end = m.span()
        num = m.group("num")
        # Units after the number mark weights / percentages / day counts: not money.
        if UNIT_AFTER.match(masked, end):
            continue
        digits = num.replace(" ", "")
        if "." not in digits and len(digits) >= 6 and not m.group("dollar"):
            continue  # long bare integers are ids (BOL, invoice, advice numbers)
        value = float(digits)
        # A leading '-' only counts as a sign when it hugs the number ("-250"), not "FEE - $20".
        sign = m.group("sign")
        if sign and (start > 0 and text[start - 1] not in " (") or (sign and " " in sign):
            start += len(sign)
            sign = None
        if sign:
            value = -value
        cands.append({
            "id": f"A{len(cands) + 1}",
            "text": text[start:end].strip(),
            "value": round(value, 2),
            "has_dollar": bool(m.group("dollar")),
            "start": start,
            "end": end,
        })
    qtys = [(int(m.group(1)), m.start()) for m in QTY_RE.finditer(masked)]
    return cands, qtys


def annotate(text, cands):
    """Description with each candidate tagged in place: 'FEE [A1: $60.00] AND ...'."""
    out, pos = [], 0
    for c in cands:
        out.append(text[pos:c["start"]])
        out.append(f"[{c['id']}: {text[c['start']:c['end']].strip()}]")
        pos = c["end"]
    out.append(text[pos:])
    return "".join(out)


if __name__ == "__main__":
    for s in [
        "SORTATION FEE $60.00 AND RESERVATION FEE $12.00 = $72.00 + GST $3.60 = $75.60",
        "SHORT PAID  300.00    ADJUSTED OFF 150.00 HAZMAT    BILLED LINEHAUL  2 023.37   FUEL SURCHARGE 556.43",
        "INVOICE REFLECTED ON SITE AS PAID IN PYMT ADVICE # 2400300373 DATED 1/13/2022  INVOICE NOT INCLUDED & IS STILL UNPAID $1 277.68",
        "ADD $225 ORGIN PERDIEM - EMPTY DROPPED 05/24 PICKED UP 05/31 - 05/24/05/28 FREE- 05/29-05/31- 3 DAYS AT $75 EACH",
        "$150 HAZMAT CHARGE ON SHIPMENT BOL 26 901 LBS",
        "$60 DRIVER DETENTION 2022-03-14 10:00:00-2022-03-14 11:22:00",
        "-250 TONU NOT NEED 2009.21 AMOUNT APPROVED",
        "DETENTION TIME $110.00 + CV 19 FEE $15.00 = $125.00 + HST",
        "DWELL DTN- DERAMP 1/28/2022 (+) DELIVERY 2/1/2022= 2 DAY(S) DWELL @300",
        "PURCHASE TRANSPORTATION SURCHARGE - $20.00",
        "$50 - ZIP 33101 TO FL HAS 15% FACTOR PER CONTRACT",
        ".73 FSC",
    ]:
        c, q = find_candidates(s)
        print(annotate(s, c), "| qty", q)
