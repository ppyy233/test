@echo off
title QwenKB ChromaDB Server
echo ============================================================
echo   QwenKB ChromaDB Server
echo ============================================================
echo   Path: chroma_db
echo   Port: 9898
echo.
echo Starting ChromaDB server...
echo   Press Ctrl+C to stop
echo.
python -c "import uvicorn; from chromadb.server.fastapi import FastAPI; from chromadb.config import Settings; s = Settings(chroma_server_host='127.0.0.1', chroma_server_http_port=9898, persist_directory='chroma_db', is_persistent=True, anonymized_telemetry=False); server = FastAPI(s); app = server.app(); uvicorn.run(app, host='127.0.0.1', port=9898)"
pause
