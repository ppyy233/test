import os, sys

ROOT = r"E:\桌面\local-database"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import uvicorn
from chromadb.server.fastapi import FastAPI
from chromadb.config import Settings

s = Settings(
    chroma_server_host="127.0.0.1",
    chroma_server_http_port=9898,
    persist_directory=os.path.join(ROOT, "chroma_db"),
    is_persistent=True,
    anonymized_telemetry=False,
)
server = FastAPI(s)
app = server.app()
uvicorn.run(app, host="127.0.0.1", port=9898)
