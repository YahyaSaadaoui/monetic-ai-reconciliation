# ===============================
# Purpose: Level‑4 (Agentic) Issuer↔Acquirer clearing reconciliation using Agno tools
# ===============================

import os, io, json, csv, zipfile, tempfile, re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional, Literal

import xmltodict  # type: ignore
from agno.tools import tool
from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field, ValidationError, condecimal
from dotenv import load_dotenv
load_dotenv("env.dev", override=True)

# ---- Config ----
MODEL_ID = os.getenv("MODEL_ID", "gemini-1.5-flash")
DATE_FMT = "%Y-%m-%d"  # e.g., 2025-08-09
DEFAULT_DATE_TOL_DAYS = int(os.getenv("DATE_TOL_DAYS", 2))


# ---- Models ----
class ClearingTxn(BaseModel):
    rrn: str
    pan: str = Field(..., description="Masked PAN (e.g., ****1111)")
    amount: condecimal(gt=0)
    currency: str
    date: str  # yyyy-mm-dd

class ClearingBatch(BaseModel):
    batch_id: str
    side: Optional[Literal["issuer", "acquirer"]] = None
    txns: List[ClearingTxn]
    source_file: Optional[str] = None


# ---- Helpers ----
_DEF_ISS_PAT = re.compile(r"\b(iss|issuer)\b", re.I)
_DEF_ACQ_PAT = re.compile(r"\b(acq|acquirer)\b", re.I)


def _parse_decimal(x) -> Decimal:
    if isinstance(x, (int, float, Decimal)):
        return Decimal(str(x))
    try:
        return Decimal(str(x).strip())
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {x}")


def _coerce_date(s: str) -> str:
    s = str(s).strip()
    # support yyyy-mm-dd or yyyy/mm/dd etc.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().strftime(DATE_FMT)
        except ValueError:
            pass
    # try ISO
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().strftime(DATE_FMT)
    except Exception:
        raise ValueError(f"Unrecognized date format: {s}")


def detect_side_from_hints(filename: str, batch_id: Optional[str], raw_text: str | None) -> Optional[str]:
    name = (filename or "").lower()
    if batch_id:
        bid = batch_id.lower()
        if bid.startswith("iss"):
            return "issuer"
        if bid.startswith("acq"):
            return "acquirer"
        if "issuer" in bid:
            return "issuer"
        if "acquirer" in bid:
            return "acquirer"
    if _DEF_ISS_PAT.search(name):
        return "issuer"
    if _DEF_ACQ_PAT.search(name):
        return "acquirer"
    if raw_text:
        if _DEF_ISS_PAT.search(raw_text):
            return "issuer"
        if _DEF_ACQ_PAT.search(raw_text):
            return "acquirer"
    return None


def load_clearing_from_bytes(data: bytes, suffix: str, filename: str = "") -> ClearingBatch:
    """Parse JSON/CSV/XML into ClearingBatch. Does not enforce side; detects heuristically."""
    suffix = suffix.lower()
    if suffix == ".json":
        raw = json.loads(data.decode("utf-8"))
        if isinstance(raw, dict) and "batch" in raw and "txns" not in raw:
            raw = raw["batch"]
        batch_id = raw.get("batch_id", os.path.splitext(os.path.basename(filename))[0])
        side = raw.get("side")
        txns = []
        for r in raw.get("txns", []):
            txns.append(
                ClearingTxn(
                    rrn=str(r["rrn"]),
                    pan=str(r.get("pan", "")),
                    amount=_parse_decimal(r["amount"]),
                    currency=str(r.get("currency", "")),
                    date=_coerce_date(r["date"]),
                )
            )
        side = side or detect_side_from_hints(filename, batch_id, json.dumps(raw)[:2000])
        return ClearingBatch(batch_id=batch_id, side=side, txns=txns, source_file=filename)

    if suffix == ".xml":
        text = data.decode("utf-8")
        d = xmltodict.parse(text)
        b = d.get("batch") or d
        batch_id = b.get("batch_id") or os.path.splitext(os.path.basename(filename))[0]
        side = b.get("side")
        items = b.get("txns", {}).get("txn", [])
        if isinstance(items, dict):
            items = [items]
        txns = []
        for r in items:
            txns.append(
                ClearingTxn(
                    rrn=str(r["rrn"]),
                    pan=str(r.get("pan", "")),
                    amount=_parse_decimal(r["amount"]),
                    currency=str(r.get("currency", "")),
                    date=_coerce_date(r["date"]),
                )
            )
        side = side or detect_side_from_hints(filename, batch_id, text[:2000])
        return ClearingBatch(batch_id=batch_id, side=side, txns=txns, source_file=filename)

    if suffix == ".csv":
        text = data.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            raise ValueError("CSV is empty")
        batch_id = rows[0].get("batch_id") or os.path.splitext(os.path.basename(filename))[0]
        side = rows[0].get("side")
        txns = []
        for r in rows:
            txns.append(
                ClearingTxn(
                    rrn=str(r["rrn"]),
                    pan=str(r.get("pan", "")),
                    amount=_parse_decimal(r["amount"]),
                    currency=str(r.get("currency", "")),
                    date=_coerce_date(r["date"]),
                )
            )
        side = side or detect_side_from_hints(filename, batch_id, text[:2000])
        return ClearingBatch(batch_id=batch_id, side=side, txns=txns, source_file=filename)

    raise ValueError(f"Unsupported file type: {suffix}")


# ---- Reconciliation core ----
class ReconConfig(BaseModel):
    date_tolerance_days: int = DEFAULT_DATE_TOL_DAYS
    amount_tolerance: condecimal(ge=0) = Decimal("0.00")  # exact by default


class ReconResult(BaseModel):
    matched: List[Dict]
    mismatches: List[Dict]
    issuer_only: List[Dict]
    acquirer_only: List[Dict]
    actions: List[str]
    metrics: Dict[str, int]
    summary_md: str


def _index_by_rrn(batch: ClearingBatch) -> Dict[str, List[ClearingTxn]]:
    idx: Dict[str, List[ClearingTxn]] = {}
    for t in batch.txns:
        idx.setdefault(t.rrn, []).append(t)
    return idx


def reconcile(issuer: ClearingBatch, acquirer: ClearingBatch, cfg: ReconConfig | None = None) -> ReconResult:
    cfg = cfg or ReconConfig()
    iss_idx = _index_by_rrn(issuer)
    acq_idx = _index_by_rrn(acquirer)

    matched, mismatches, issuer_only, acquirer_only = [], [], [], []

    for rrn, txs in iss_idx.items():
        if len(txs) > 1:
            mismatches.append({"rrn": rrn, "reason": "duplicate_issuer", "count": len(txs)})
    for rrn, txs in acq_idx.items():
        if len(txs) > 1:
            mismatches.append({"rrn": rrn, "reason": "duplicate_acquirer", "count": len(txs)})

    all_rrn = set(iss_idx) | set(acq_idx)
    for rrn in sorted(all_rrn):
        iss = iss_idx.get(rrn, [])
        acq = acq_idx.get(rrn, [])
        if iss and acq:
            a = iss[0]
            b = acq[0]
            # currency
            if a.currency != b.currency:
                mismatches.append({
                    "rrn": rrn,
                    "reason": "currency_mismatch",
                    "issuer": a.currency,
                    "acquirer": b.currency,
                })
                continue
            # amount
            delta = abs(_parse_decimal(a.amount) - _parse_decimal(b.amount))
            if delta > _parse_decimal(cfg.amount_tolerance):
                mismatches.append({
                    "rrn": rrn,
                    "reason": "amount_delta",
                    "issuer": str(a.amount),
                    "acquirer": str(b.amount),
                    "delta": str(delta),
                })
                continue
            # date tolerance
            da = datetime.strptime(a.date, DATE_FMT).date()
            db = datetime.strptime(b.date, DATE_FMT).date()
            if abs((da - db).days) > int(cfg.date_tolerance_days):
                mismatches.append({
                    "rrn": rrn,
                    "reason": "date_out_of_tolerance",
                    "issuer": a.date,
                    "acquirer": b.date,
                    "tolerance_days": cfg.date_tolerance_days,
                })
                continue
            matched.append({"rrn": rrn, "status": "ok"})
        elif iss and not acq:
            issuer_only.append({"rrn": rrn, "reason": "missing_on_acquirer"})
        elif acq and not iss:
            acquirer_only.append({"rrn": rrn, "reason": "missing_on_issuer"})

    # actions
    actions: List[str] = []
    for it in issuer_only:
        actions.append(f"Request resend for {it['rrn']} from acquirer")
    for it in acquirer_only:
        actions.append(f"Open investigation ticket for {it['rrn']}; potential late presentment or routing issue")
    for m in mismatches:
        if m["reason"] == "amount_delta":
            actions.append(f"Amount delta on {m['rrn']}: raise dispute/adjustment")
        elif m["reason"] == "currency_mismatch":
            actions.append(f"Currency mismatch on {m['rrn']}: verify FX and correct clearing file")
        elif m["reason"].startswith("duplicate"):
            actions.append(f"Duplicate {m['reason'].split('_')[1]} rrn {m['rrn']}: de-duplicate and re-send")
        elif m["reason"] == "date_out_of_tolerance":
            actions.append(f"Date mismatch on {m['rrn']}: confirm presentment date vs auth date")

    metrics = {
        "matched": len(matched),
        "mismatches": len(mismatches),
        "issuer_only": len(issuer_only),
        "acquirer_only": len(acquirer_only),
        "total": len(matched) + len(mismatches) + len(issuer_only) + len(acquirer_only),
    }

    summary_md = (
        f"Reconciliation: {metrics['matched']} match, "
        f"{metrics['mismatches']} mismatches, "
        f"{metrics['issuer_only']} issuer-only, "
        f"{metrics['acquirer_only']} acquirer-only."
    )

    return ReconResult(
        matched=matched,
        mismatches=mismatches,
        issuer_only=issuer_only,
        acquirer_only=acquirer_only,
        actions=actions,
        metrics=metrics,
        summary_md=summary_md,
    )


# ---- Pair detection for archives (batch mode) ----
class ParsedFile(BaseModel):
    batch: ClearingBatch
    rrn_set: set


def _guess_side(batch: ClearingBatch, filename: str, raw_text: str | None) -> ClearingBatch:
    if batch.side:
        return batch
    side = detect_side_from_hints(filename, batch.batch_id, raw_text)
    return ClearingBatch(**{**batch.model_dump(), "side": side})


def _pair_batches(files: List[ParsedFile]) -> List[Tuple[ClearingBatch, ClearingBatch]]:
    issuers = [pf for pf in files if pf.batch.side == "issuer"]
    acqs = [pf for pf in files if pf.batch.side == "acquirer"]

    # If some sides are unknown, try to infer by file name or fall back to overlap
    unknowns = [pf for pf in files if pf.batch.side is None]
    for u in unknowns:
        # heuristic: if name contains issuer/acquirer already handled in detect_side_from_hints; here we default by overlap later
        pass

    pairs: List[Tuple[ClearingBatch, ClearingBatch]] = []
    used_acq = set()
    for iss in issuers:
        # choose acq with max RRN overlap
        best = None
        best_overlap = -1
        for j, acq in enumerate(acqs):
            if j in used_acq:
                continue
            ov = len(iss.rrn_set & acq.rrn_set)
            if ov > best_overlap:
                best = j
                best_overlap = ov
        if best is not None and best_overlap >= 0:
            pairs.append((issuers[issuers.index(iss)].batch, acqs[best].batch))
            used_acq.add(best)

    # try pairing unknowns by overlap
    remaining = [pf for pf in files if pf.batch not in [b for pair in pairs for b in pair]]
    # naive: attempt all combos and pick high overlap, assign sides arbitrarily
    while len(remaining) >= 2:
        best_pair = None
        best_overlap = -1
        for i in range(len(remaining)):
            for j in range(i + 1, len(remaining)):
                ov = len(remaining[i].rrn_set & remaining[j].rrn_set)
                if ov > best_overlap:
                    best_overlap = ov
                    best_pair = (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        a = remaining[i].batch
        b = remaining[j].batch
        # assign sides by filename hints if any else default a->issuer, b->acquirer
        if a.side is None and b.side is None:
            a = ClearingBatch(**{**a.model_dump(), "side": "issuer"})
            b = ClearingBatch(**{**b.model_dump(), "side": "acquirer"})
        elif a.side is None:
            a = ClearingBatch(**{**a.model_dump(), "side": "issuer" if b.side == "acquirer" else "acquirer"})
        elif b.side is None:
            b = ClearingBatch(**{**b.model_dump(), "side": "acquirer" if a.side == "issuer" else "issuer"})
        pairs.append((a, b))
        # remove used
        for idx in sorted(best_pair, reverse=True):
            remaining.pop(idx)

    return pairs


# ---- Tools (for Agno agents) ----
@tool(show_result=True)
def parse_clearing_file(path: str) -> dict:
    """Load a clearing file (json/csv/xml) from disk and return a ClearingBatch dict."""
    p = os.path.abspath(path)
    suffix = os.path.splitext(p)[1].lower()
    data = open(p, "rb").read()
    batch = load_clearing_from_bytes(data, suffix, filename=os.path.basename(p))
    return batch.model_dump()


@tool(show_result=True)
def reconcile_pair(issuer_path: str, acquirer_path: str, date_tolerance_days: int = DEFAULT_DATE_TOL_DAYS, amount_tolerance: float = 0.0) -> dict:
    """Deterministic reconciliation for two files (issuer, acquirer). Auto-detects sides; will swap if needed."""
    a = load_clearing_from_bytes(open(issuer_path, "rb").read(), os.path.splitext(issuer_path)[1], filename=os.path.basename(issuer_path))
    b = load_clearing_from_bytes(open(acquirer_path, "rb").read(), os.path.splitext(acquirer_path)[1], filename=os.path.basename(acquirer_path))

    # ensure sides
    if a.side == "acquirer" and b.side == "issuer":
        a, b = b, a
    if a.side not in ("issuer", None) or b.side not in ("acquirer", None):
        # if one is unknown but the other known, set appropriately
        if a.side == "issuer" and b.side is None:
            b = ClearingBatch(**{**b.model_dump(), "side": "acquirer"})
        elif b.side == "acquirer" and a.side is None:
            a = ClearingBatch(**{**a.model_dump(), "side": "issuer"})

    if (a.side != "issuer") or (b.side != "acquirer"):
        raise ValueError("Could not reliably detect issuer vs acquirer. Please include 'side' or rename files with 'issuer'/'acquirer'.")

    res = reconcile(a, b, ReconConfig(date_tolerance_days=date_tolerance_days, amount_tolerance=Decimal(str(amount_tolerance))))
    return res.model_dump()


@tool(show_result=True)
def reconcile_archive(path: str, date_tolerance_days: int = DEFAULT_DATE_TOL_DAYS, amount_tolerance: float = 0.0) -> dict:
    """Batch mode: accept a .zip or .rar on disk, extract, auto-pair issuer/acquirer, and return list of results + totals."""
    suf = os.path.splitext(path)[1].lower()
    if suf not in (".zip", ".rar"):
        raise ValueError("Archive must be .zip or .rar")

    tmpdir = tempfile.mkdtemp(prefix="recon_")
    paths: List[str] = []
    if suf == ".zip":
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(tmpdir)
            for n in z.namelist():
                if n.lower().endswith((".json", ".csv", ".xml")):
                    paths.append(os.path.join(tmpdir, n))
    else:
        import rarfile  # type: ignore
        try:
            with rarfile.RarFile(path) as rf:
                rf.extractall(tmpdir)
                for n in rf.namelist():
                    if n.lower().endswith((".json", ".csv", ".xml")):
                        paths.append(os.path.join(tmpdir, n))
        except rarfile.RarCannotExec:
            raise RuntimeError("RAR support needs 'unrar' installed on PATH.")

    parsed: List[ParsedFile] = []
    for p in paths:
        suf2 = os.path.splitext(p)[1].lower()
        data = open(p, "rb").read()
        batch = load_clearing_from_bytes(data, suf2, filename=os.path.basename(p))
        batch = _guess_side(batch, os.path.basename(p), None)
        rrn_set = {t.rrn for t in batch.txns}
        parsed.append(ParsedFile(batch=batch, rrn_set=rrn_set))

    pairs = _pair_batches(parsed)
    results = []
    totals = {"pairs": len(pairs), "matched": 0, "mismatches": 0, "issuer_only": 0, "acquirer_only": 0}
    for iss, acq in pairs:
        r = reconcile(iss, acq, ReconConfig(date_tolerance_days=date_tolerance_days, amount_tolerance=Decimal(str(amount_tolerance))))
        results.append({
            "issuer_file": iss.source_file,
            "acquirer_file": acq.source_file,
            "result": r.model_dump(),
        })
        totals["matched"] += r.metrics["matched"]
        totals["mismatches"] += r.metrics["mismatches"]
        totals["issuer_only"] += r.metrics["issuer_only"]
        totals["acquirer_only"] += r.metrics["acquirer_only"]

    return {"pairs": len(pairs), "totals": totals, "results": results}


# ---- Agents ----
recon_planner = Agent(
    name="Recon Planner",
    role=(
        "Reconcile issuer/acquirer clearing files. When given 2 paths, call reconcile_pair(issuer_path, acquirer_path). "
        "When given an archive path (.zip/.rar), call reconcile_archive(path). Return only tool JSON."
    ),
    model=Gemini(id=MODEL_ID),
    tools=[parse_clearing_file, reconcile_pair, reconcile_archive],
    reasoning=False,
    markdown=True,
)

recon_reporter = Agent(
    name="Recon Reporter",
    role="Turn a reconciliation JSON into a short human summary in Markdown.",
    model=Gemini(id=MODEL_ID),
    reasoning=True,
    markdown=True,
)

