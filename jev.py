"""Minimal Jev client: key from ../jev_exp/.env, JSON-file cache, retries, parallel map."""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
ENV_PATH = Path(os.environ.get("JEV_ENV", HERE.parent / "jev_exp" / ".env"))
API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
CACHE_PATH = HERE / "cache" / "jev_cache.json"
_lock = threading.Lock()


def load_key():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get("JEV_API_KEY") or sys.exit(f"JEV_API_KEY missing from {ENV_PATH}")


def _load_cache():
    return json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def _save_cache(cache):
    CACHE_PATH.parent.mkdir(exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(CACHE_PATH)


def call(payload, key, retries=6):
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            API_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Jev API error {e.code}: {e.read().decode()[:500]}")
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def _h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def ask_many(payloads, workers=8, progress=True):
    """Run payloads (dicts with state+questions) in parallel.

    Cached per (state, question): editing one question only re-asks that question.
    Returns one response per payload: {"answers": {...}, "usage": usage of the fresh call or zeros}."""
    key = load_key()
    cache = _load_cache()
    out = [None] * len(payloads)
    todo = []
    for i, p in enumerate(payloads):
        sh = _h({"state": p["state"], "model": MODEL})
        qkeys = {qid: f"{sh}:{_h(q)}" for qid, q in p["questions"].items()}
        answers = {qid: cache[k] for qid, k in qkeys.items() if k in cache}
        missing = {qid: p["questions"][qid] for qid in qkeys if qid not in answers}
        out[i] = {"answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}
        if missing:
            todo.append((i, qkeys, {"state": p["state"], "model": MODEL, "questions": missing}))
    if progress:
        print(f"jev: {len(payloads) - len(todo)} fully cached, {len(todo)} requests to send", flush=True)
    done = 0

    def run(item):
        nonlocal done
        i, qkeys, p = item
        resp = call(p, key)
        with _lock:
            for qid, ans in resp["answers"].items():
                cache[qkeys[qid]] = ans
                out[i]["answers"][qid] = ans
            out[i]["usage"] = resp.get("usage", out[i]["usage"])
            done += 1
            if done % 25 == 0 or done == len(todo):
                _save_cache(cache)
                if progress:
                    print(f"  {done}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, todo))
    _save_cache(cache)
    return out
