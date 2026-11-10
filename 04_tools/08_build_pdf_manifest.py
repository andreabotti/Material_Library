"""
08_build_pdf_manifest.py  –  Build a manifest of every file in 01_data/pdf

01_data/pdf mixes EPDs, technical sheets, and VOC certificates in one flat
folder. EPDs are named by their own registration/declaration number, but
technical sheets and VOC certs are just sha256(url)[:16].pdf — indistinguishable
by filename alone. This tool answers "what IS this file, really?" for every
file, independent of which Excel column/URL produced it:

  declared_type   which pipeline column downloaded it (EPD / Technical Sheet /
                  VOC Certificate / VOC Certificate (alt))
  detected_type   libs.lib_doc_classifier's read of the actual file content
  mismatch        declared_type and detected_type disagree (e.g. a VOC URL
                  that actually downloaded a marketing webpage — see the
                  parse_failed investigation that motivated this tool)
  referencing     EETRA IDs / product names / manufacturers that cite this file
  origin_urls     the source URL(s) that map to this local file

Usage (PowerShell):
    python 04_tools/08_build_pdf_manifest.py
    python 04_tools/08_build_pdf_manifest.py --use-claude      # escalate low-confidence heuristic results
    python 04_tools/08_build_pdf_manifest.py --claude-all      # classify every file via Claude (cost!)

Output: 01_data/pdf_manifest.csv
"""
import argparse
import csv
import pathlib
import sys

import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from libs.lib_doc_classifier import classify_document, estimate_cost  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

PARQUET_PATH = _ROOT / "01_data" / "base_data.parquet"
MANIFEST_PATH = _ROOT / "01_data" / "pdf_manifest.csv"

COL_ID           = "0__EETRA_ID"
COL_NAME         = "A__ProductName"
COL_MANUFACTURER = "A__Manufacturer"

# (url_col, local_col, declared_label, comparable_bucket)
_SOURCES = [
    ("E__EPD_URL",         "E__EPD_Local",        "EPD",                    "epd"),
    ("U__TechDetails_URL", "U__TechDetails_Local", "Technical Sheet",       "technical_sheet"),
    ("VO__VOC_URL",        "VO__VOC_Local",        "VOC Certificate",       "voc"),
    ("U__VOC_URL",         "U__VOC_Local_alt",     "VOC Certificate (alt)", "voc"),
]

# detected_type buckets that count as "consistent" with each comparable_bucket
_CONSISTENT = {
    "epd":             {"epd"},
    "technical_sheet": {"technical_sheet"},
    "voc":             {"voc_certificate", "voc_declaration"},
}

_MAX_LIST_ITEMS = 5


def _str(val) -> str:
    return "" if pd.isna(val) else str(val).strip()


def _joined(items: set, cap: int = _MAX_LIST_ITEMS) -> str:
    vals = sorted(v for v in items if v)
    if len(vals) > cap:
        return "; ".join(vals[:cap]) + f"; (+{len(vals) - cap} more)"
    return "; ".join(vals)


def build_index(df: pd.DataFrame) -> dict[str, dict]:
    """local_path -> {declared_buckets, declared_labels, eetra_ids, products, manufacturers, urls}"""
    index: dict[str, dict] = {}
    for url_col, local_col, label, bucket in _SOURCES:
        if local_col not in df.columns:
            continue
        for _, row in df.iterrows():
            local = _str(row.get(local_col, ""))
            if not local:
                continue
            entry = index.setdefault(local, {
                "declared_buckets": set(), "declared_labels": set(),
                "eetra_ids": set(), "products": set(), "manufacturers": set(), "urls": set(),
            })
            entry["declared_buckets"].add(bucket)
            entry["declared_labels"].add(label)
            entry["eetra_ids"].add(_str(row.get(COL_ID, "")))
            entry["products"].add(_str(row.get(COL_NAME, "")))
            entry["manufacturers"].add(_str(row.get(COL_MANUFACTURER, "")))
            if url_col in df.columns:
                entry["urls"].add(_str(row.get(url_col, "")))
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a manifest of every file in 01_data/pdf")
    ap.add_argument("--use-claude", action="store_true",
                     help="Escalate low-confidence heuristic results to Claude")
    ap.add_argument("--claude-all", action="store_true",
                     help="Classify every file via Claude, ignoring heuristic confidence (cost!)")
    args = ap.parse_args()

    client = None
    if args.use_claude or args.claude_all:
        sys.path.insert(0, str(_ROOT / "04_tools"))
        from importlib import import_module
        pipeline_mod_path = _ROOT / "04_tools" / "03_excel_to_parquet.py"
        # Reuse the key-resolution helper without executing the whole pipeline script.
        import ast
        src = pipeline_mod_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        func_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_anthropic_api_key")
        ns = {"os": __import__("os"), "pathlib": pathlib}
        exec(compile(ast.Module(body=[func_node], type_ignores=[]), "<resolve_anthropic_api_key>", "exec"), ns)
        key, src_label = ns["resolve_anthropic_api_key"]()
        if key:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            print(f"Claude classification enabled (key from {src_label}).")
        else:
            print("No Anthropic API key found — falling back to heuristic-only classification.")

    if not PARQUET_PATH.exists():
        print(f"Parquet not found: {PARQUET_PATH}")
        sys.exit(1)

    df = pd.read_parquet(PARQUET_PATH)
    index = build_index(df)
    print(f"{len(index)} unique files referenced across EPD / Technical Sheet / VOC columns.")

    rows_out = []
    total_input_tokens = total_output_tokens = 0
    claude_calls = 0
    crosstab: dict[tuple[str, str], int] = {}

    for i, (local_path_str, entry) in enumerate(sorted(index.items()), 1):
        pdf_path = _ROOT / local_path_str
        exists = pdf_path.exists()
        size_kb = round(pdf_path.stat().st_size / 1024, 1) if exists else None

        if not exists:
            result = {"doc_type": "other", "confidence": "low", "method": "n/a",
                      "notes": "File missing on disk", "_input_tokens": 0, "_output_tokens": 0, "_error": None}
        else:
            result = classify_document(
                pdf_path,
                client=client,
                escalate_low_confidence=args.use_claude,
                force_claude=args.claude_all,
            )

        if result.get("method", "").startswith("claude"):
            claude_calls += 1
        total_input_tokens += result.get("_input_tokens", 0)
        total_output_tokens += result.get("_output_tokens", 0)

        declared_label = " / ".join(sorted(entry["declared_labels"]))
        declared_buckets = entry["declared_buckets"]
        detected = result["doc_type"]
        consistent_types = set().union(*(_CONSISTENT.get(b, set()) for b in declared_buckets)) if declared_buckets else set()
        mismatch = bool(consistent_types) and detected not in consistent_types

        crosstab[(declared_label, detected)] = crosstab.get((declared_label, detected), 0) + 1

        rows_out.append({
            "filename": local_path_str,
            "exists": exists,
            "size_kb": size_kb,
            "declared_type": declared_label,
            "detected_type": detected,
            "confidence": result["confidence"],
            "method": result.get("method", "heuristic"),
            "mismatch": mismatch,
            "eetra_ids": _joined(entry["eetra_ids"]),
            "product_names": _joined(entry["products"]),
            "manufacturers": _joined(entry["manufacturers"]),
            "origin_urls": _joined(entry["urls"], cap=3),
            "notes": result.get("notes", ""),
        })

        if i % 100 == 0:
            print(f"  classified {i}/{len(index)}…")

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()) if rows_out else [])
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\nManifest written → {MANIFEST_PATH} ({len(rows_out)} files)")

    n_mismatch = sum(1 for r in rows_out if r["mismatch"])
    n_missing = sum(1 for r in rows_out if not r["exists"])
    print(f"  {n_mismatch} declared/detected mismatches, {n_missing} files missing on disk")

    if claude_calls:
        cost = estimate_cost(total_input_tokens, total_output_tokens)
        print(f"  {claude_calls} files classified via Claude (~${cost:.4f} USD)")

    print("\nDeclared type -> Detected type crosstab:")
    for (declared, detected), n in sorted(crosstab.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f"  {declared:24s} -> {detected:16s} {n:4d}")

    if n_mismatch:
        print("\nMismatched files (declared vs. detected):")
        for r in rows_out:
            if r["mismatch"]:
                print(f"  {r['filename']:40s} declared={r['declared_type']:22s} detected={r['detected_type']:16s} "
                      f"({r['product_names'][:50]})")


if __name__ == "__main__":
    main()
