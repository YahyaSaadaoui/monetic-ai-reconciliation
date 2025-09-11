# ui_recon_api_only.py
import os, json, tempfile, zipfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from l4_clearing_recon import (
    load_clearing_from_bytes,
    reconcile,
    ReconConfig,
)
from dotenv import load_dotenv

from dotenv import load_dotenv
app = FastAPI(title="Clearing Recon API (strict 2-file / 1-archive)")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|"
                       r"192\.168\.\d{1,3}\.\d{1,3}|"
                       r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
                       r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _ensure_sides(ba, bb):
    # issuer/acquirer ordering; try to fix if reversed/unknown
    a, b = ba, bb
    if a.side == "acquirer" and b.side == "issuer":
        a, b = b, a
    if a.side != "issuer" or b.side != "acquirer":
        raise HTTPException(
            status_code=400,
            detail="Could not detect issuer vs acquirer. Rename files to include 'issuer'/'acquirer' or add 'side' in JSON/CSV/XML."
        )
    return a, b

@app.post("/reconcile")
async def reconcile_upload(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files provided")

    # Single archive
    if len(files) == 1 and os.path.splitext(files[0].filename)[1].lower() in (".zip",):
        up = files[0]
        content = await up.read()
        with tempfile.TemporaryDirectory() as tmpdir:
            zpath = Path(tmpdir) / "upload.zip"
            zpath.write_bytes(content)
            with zipfile.ZipFile(zpath, "r") as zf:
                zf.extractall(tmpdir)
            # find candidate data files
            paths = []
            for root, _, names in os.walk(tmpdir):
                for n in names:
                    if n.lower().endswith((".json", ".csv", ".xml")):
                        paths.append(os.path.join(root, n))
            if len(paths) < 2:
                raise HTTPException(400, "Archive must contain at least 2 clearing files")
            # naive pairing: take the first 2
            a_path, b_path = paths[0], paths[1]
            a = load_clearing_from_bytes(Path(a_path).read_bytes(), Path(a_path).suffix, filename=os.path.basename(a_path))
            b = load_clearing_from_bytes(Path(b_path).read_bytes(), Path(b_path).suffix, filename=os.path.basename(b_path))
            a, b = _ensure_sides(a, b)
            res = reconcile(a, b, ReconConfig()).model_dump()
            return {"ok": True, "mode": "archive", "result": res}

    # Exactly two files (issuer + acquirer)
    if len(files) != 2:
        raise HTTPException(400, "Upload exactly two files (issuer + acquirer), or a single .zip archive")

    batches = []
    for f in files:
        data = await f.read()
        suffix = Path(f.filename).suffix.lower()
        if suffix not in (".json", ".csv", ".xml"):
            raise HTTPException(400, f"Unsupported type: {suffix}")
        batches.append(load_clearing_from_bytes(data, suffix, filename=f.filename))

    a, b = _ensure_sides(batches[0], batches[1])
    res = reconcile(a, b, ReconConfig()).model_dump()
    return {"ok": True, "mode": "pair", "result": res}
