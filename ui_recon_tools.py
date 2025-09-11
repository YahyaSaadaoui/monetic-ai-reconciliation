# ===============================
# File: ui_recon_tools.py
# Purpose: FastAPI endpoints + Agno tools for uploads (enforce 2 files or 1 archive)
# ===============================
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name("env.dev"), override=True)
import base64
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage
import os
from l4_clearing_recon import (
    load_clearing_from_bytes,
    reconcile,
    ReconConfig,
    detect_side_from_hints,
    parse_clearing_file,
    reconcile_pair,
    reconcile_archive,
    recon_planner,
)
from agno.agent import Agent
from agno.models.google import Gemini
from l4_clearing_recon import MODEL_ID
import tempfile
import uvicorn

AGENT_DB = "tmp/agents.db"
os.makedirs("tmp", exist_ok=True)

# Tools to let the agent remember last result
_last_result: dict | None = None

from agno.tools import tool as _tool

@_tool(show_result=False)
def remember_last_recon(result: dict) -> str:
    global _last_result
    _last_result = result
    return "stored"

@_tool(show_result=True)
def recall_last_recon() -> dict:
    return _last_result or {"info": "no reconciliation stored yet"}

recon_agent = Agent(
    name="Recon Agent",
    model=Gemini(id=MODEL_ID, api_key=os.getenv("GOOGLE_API_KEY")),
    tools=[parse_clearing_file, reconcile_pair, reconcile_archive, remember_last_recon, recall_last_recon],
    instructions=[
        "You reconcile only when exactly two clearing files are provided, or when a single archive (.zip/.rar) is provided.",
        "Refuse single non-archive uploads; instruct user to provide issuer+acquirer together.",
        "Always store the result via remember_last_recon(result).",
    ],
    storage=SqliteStorage(table_name="recon_agent", db_file=AGENT_DB),
    add_datetime_to_instructions=True,
    add_history_to_messages=True,
    num_history_responses=5,
    markdown=True,
)

# playground = Playground(agents=[recon_agent])
# app = playground.get_app()
api_app = FastAPI(title="Clearing Recon API")

# Strong upload contract: exactly 2 files OR exactly 1 archive (.zip/.rar)
@api_app.post("/reconcile")
async def reconcile_upload(files: list[UploadFile] = File(...)):
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        # Archive path (single)
        if len(files) == 1 and os.path.splitext(files[0].filename)[1].lower() in (".zip", ".rar"):
            content = await files[0].read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(files[0].filename)[1]) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            result = reconcile_archive.entrypoint(path=tmp_path)
            remember_last_recon.entrypoint(result=result)
            return {"ok": True, "mode": "archive", "result": result}

        # Exactly two files (issuer + acquirer)
        if len(files) != 2:
            raise HTTPException(status_code=400, detail="You must upload exactly two files (issuer + acquirer), or a single .zip/.rar archive.")

        # Read both, auto-detect sides
        tmp_paths: list[str] = []
        batches = []
        for f in files:
            data = await f.read()
            suffix = os.path.splitext(f.filename)[1].lower()
            if suffix not in (".json", ".csv", ".xml"):
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
            batch = load_clearing_from_bytes(data, suffix, filename=f.filename)
            batches.append(batch)
        # ensure issuer/acquirer ordering
        a, b = batches
        if a.side == "acquirer" and b.side == "issuer":
            a, b = b, a
        if a.side != "issuer" or b.side != "acquirer":
            raise HTTPException(status_code=400, detail="Could not detect issuer vs acquirer from files. Rename files to include 'issuer'/'acquirer' or add 'side' in content.")
        result = reconcile(a, b, ReconConfig()).model_dump()
        remember_last_recon.entrypoint(result=result)
        return {"ok": True, "mode": "pair", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# CORS for local dev
api_app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2\d|3[0-1])\.[0-9]{1,3}\.[0-9]{1,3})(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run("ui_recon_tools:api_app", host="127.0.0.1", port=7788, reload=True)
