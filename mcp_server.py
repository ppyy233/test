# -*- coding: utf-8 -*-
"""
QwenKB V1.1 — MCP 服务器 (Client-Server 模式)
通过 HTTP 暴露 search_knowledge_base 工具，供 opencode 等 MCP 客户端调用
使用 AsyncHttpClient 连接 ChromaDB Server 实现异步查询
"""
import os
import sys
import json
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from openai import OpenAI
import chromadb
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            str(Path(__file__).resolve().parent / "mcp_server.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    ],
)
logger = logging.getLogger("QwenKB-MCP")


def get_base_dir():
    return Path(__file__).resolve().parent


app = FastAPI(title="QwenKB MCP Server", version="1.1.0")

_oai_client = None
_chroma_client = None
_chroma_collection = None


def get_oai_client():
    global _oai_client
    if _oai_client is None:
        _oai_client = OpenAI(
            api_key=config.EMBEDDING_API_KEY,
            base_url=config.EMBEDDING_API_URL.rsplit("/v1/", 1)[0] + "/v1/",
        )
    return _oai_client


async def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = await chromadb.AsyncHttpClient(
            host=config.CHROMA_SERVER_HOST,
            port=config.CHROMA_SERVER_PORT,
        )
    return _chroma_client


async def get_collection_async():
    global _chroma_collection
    if _chroma_collection is None:
        client = await get_chroma_client()
        _chroma_collection = await client.get_collection(name=config.COLLECTION_NAME)
    return _chroma_collection


async def check_lm_studio_health() -> tuple[bool, str]:
    base_url = config.EMBEDDING_API_URL.rsplit("/v1/", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{base_url}/v1/models", headers={
                "Authorization": f"Bearer {config.EMBEDDING_API_KEY}"
            })
            if r.status_code == 200:
                return True, ""
            return False, f"LM Studio 返回状态码 {r.status_code}"
    except Exception as e:
        return False, f"LM Studio 未启动或不可访问: {e}"


def embed_query(query: str) -> list[float]:
    client = get_oai_client()
    resp = client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=[query],
    )
    vec = resp.data[0].embedding
    if len(vec) != config.EMBEDDING_DIM:
        raise ValueError(
            f"LM Studio 返回向量维度 {len(vec)}，期望 {config.EMBEDDING_DIM}"
        )
    return vec


async def search_async(query: str) -> str:
    ok, err = await check_lm_studio_health()
    if not ok:
        return f"[错误] {err}\n请启动 LM Studio 并加载 Qwen3-Embedding 模型后重试。"

    try:
        query_vec = await asyncio.to_thread(embed_query, query)
        collection = await get_collection_async()
        results = await collection.query(
            query_embeddings=[query_vec],
            n_results=config.RETRIEVAL_K,
            include=["documents", "metadatas", "distances"],
        )

        if not results or not results["ids"] or not results["ids"][0]:
            return "知识库中未找到相关内容。"

        parts = [f"找到 {len(results['ids'][0])} 条相关文档:\n"]
        for i, (doc_id, doc_text, meta, dist) in enumerate(zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ), 1):
            source = meta.get("source", "未知来源")
            fname = os.path.basename(source)
            similarity = max(0, 1 - dist)
            part = f"[{i}] 来源: {fname} | 相似度: {similarity:.2%}\n{doc_text.strip()}"
            parts.append(part)
        return "\n\n".join(parts)

    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return f"[错误] 搜索过程出错: {e}"


# ============================================================
# MCP 协议端点
# ============================================================

@app.get("/health")
async def health_check():
    ok, err = await check_lm_studio_health()
    try:
        coll = await get_collection_async()
        db_count = await coll.count()
    except Exception:
        db_count = 0
    return {
        "status": "ok",
        "lm_studio": {"online": ok, "error": err},
        "chromadb": {
            "server": f"{config.CHROMA_SERVER_HOST}:{config.CHROMA_SERVER_PORT}",
            "collection": config.COLLECTION_NAME,
            "documents": db_count,
        },
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    method = body.get("method", "")
    req_id = body.get("id", 0)

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [{
                    "name": "search_knowledge_base",
                    "description": "【优先调用】遇到以下情况应优先使用此工具搜索本地知识库：① 用户询问的信息可能属于个人私有数据或特定工作环境；② 问题涉及你训练数据中可能不存在的特定人物、地点或事件；③ 你对答案不确定，需要从本地文档中查找事实依据。调用此工具来检索本地知识库中的文档信息。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "要搜索的问题或关键词，使用中文或英文均可。"
                            }
                        },
                        "required": ["query"]
                    }
                }]
            }
        })

    elif method == "tools/call":
        tool_name = body.get("params", {}).get("name", "")
        arguments = body.get("params", {}).get("arguments", {})

        if tool_name == "search_knowledge_base":
            query_text = arguments.get("query", "")
            if not query_text:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "缺少 query 参数"}
                }, status_code=400)
            logger.info(f"搜索: {query_text[:100]}")
            result_text = await search_async(query_text)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}]
                }
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"未知工具: {tool_name}"}
        }, status_code=404)

    elif method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "QwenKB", "version": "1.1.0"},
                "capabilities": {"tools": {}}
            }
        })

    elif method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})

    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"未知方法: {method}"}
        }, status_code=404)


def main():
    logger.info("QwenKB MCP Server V1.1.0 启动中...")
    logger.info(f"LM Studio: {config.EMBEDDING_API_URL}")
    logger.info(f"ChromaDB Server: {config.CHROMA_SERVER_HOST}:{config.CHROMA_SERVER_PORT}")
    logger.info(f"监听: http://{config.MCP_SERVER_HOST}:{config.MCP_SERVER_PORT}")

    async def startup_checks():
        ok, err = await check_lm_studio_health()
        if ok:
            logger.info("LM Studio: 在线")
        else:
            logger.warning(f"LM Studio: {err}")

        try:
            client = await get_chroma_client()
            await client.heartbeat()
            logger.info("ChromaDB Server: 在线")
        except Exception as e:
            logger.warning(f"ChromaDB Server 不可用: {e}")

    asyncio.run(startup_checks())

    uvicorn.run(
        app,
        host=config.MCP_SERVER_HOST,
        port=config.MCP_SERVER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
