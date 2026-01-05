from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import HtmlDiff, SequenceMatcher
from typing import Dict, List, Tuple

ITEM_RE_10KQ = re.compile(r"(?im)^\s*(item)\s+(\d{1,2})([a-z]?)\s*[\.:]\s*(.+?)\s*$")
ITEM_RE_8K = re.compile(r"(?im)^\s*(item)\s+(\d{1,2})\.(\d{2})\s*[\.:]\s*(.+?)\s*$")

def normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

@dataclass
class ChunkResult:
    chunks: Dict[str, Tuple[str, str]]  # key -> (title, body)
    unstructured: bool

def chunk_by_items(form_type: str, text: str) -> ChunkResult:
    t = normalize_text(text)
    if form_type == "8-K":
        matches = list(ITEM_RE_8K.finditer(t))
        if len(matches) < 2:
            return ChunkResult({"UNSTRUCTURED": ("Unstructured", t)}, unstructured=True)
        return ChunkResult(_split_by_matches_8k(t, matches), unstructured=False)

    matches = list(ITEM_RE_10KQ.finditer(t))
    if len(matches) < 3:
        return ChunkResult({"UNSTRUCTURED": ("Unstructured", t)}, unstructured=True)
    return ChunkResult(_split_by_matches_10kq(t, matches), unstructured=False)

def _split_by_matches_10kq(t: str, matches) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    spans = []
    for m in matches:
        start = m.start()
        item_num = m.group(2)
        item_letter = (m.group(3) or "").upper()
        title = m.group(4).strip()
        key = f"ITEM_{item_num}{item_letter}"
        label = f"Item {item_num}{item_letter} — {title}" if title else f"Item {item_num}{item_letter}"
        spans.append((start, key, label))

    for i, (start, key, label) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(t)
        body = t[start:end].strip()
        out[key] = (label, body)
    return out

def _split_by_matches_8k(t: str, matches) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    spans = []
    for m in matches:
        start = m.start()
        item_a = m.group(2)
        item_b = m.group(3)
        title = m.group(4).strip()
        key = f"ITEM_{item_a}_{item_b}"
        label = f"Item {item_a}.{item_b} — {title}" if title else f"Item {item_a}.{item_b}"
        spans.append((start, key, label))

    for i, (start, key, label) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(t)
        body = t[start:end].strip()
        out[key] = (label, body)
    return out

def is_meaningful_change(old: str, new: str) -> bool:
    o = normalize_text(old)
    n = normalize_text(new)
    if o == n:
        return False
    ratio = SequenceMatcher(None, o, n).ratio()
    return ratio < 0.995

def diff_sections(old_chunks: Dict[str, Tuple[str, str]], new_chunks: Dict[str, Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    hd = HtmlDiff(tabsize=2, wrapcolumn=120)
    changed: List[Tuple[str, str, str]] = []
    keys = sorted(set(old_chunks.keys()) | set(new_chunks.keys()))
    for key in keys:
        old_title, old_body = old_chunks.get(key, ("", ""))
        new_title, new_body = new_chunks.get(key, ("", ""))
        title = new_title or old_title or key
        if not is_meaningful_change(old_body, new_body):
            continue
        old_lines = normalize_text(old_body).splitlines()
        new_lines = normalize_text(new_body).splitlines()
        table = hd.make_table(old_lines, new_lines, fromdesc="Previous", todesc="Current", context=True, numlines=2)
        changed.append((key, title, table))
    return changed
