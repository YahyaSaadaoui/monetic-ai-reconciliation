import os
import yaml
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage
from l4_clearing_recon import recon_planner
from ui_recon_tools import recon_agent 
import uvicorn
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).with_name("env.dev"), override=True)
app = Playground(agents=[recon_agent, recon_planner]).get_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run("playground:app", host="127.0.0.1", port=7777, reload=True)
