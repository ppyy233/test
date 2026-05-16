# -*- coding: utf-8 -*-
"""
QwenKB V1.1 — 知识库构建脚本 (Client-Server 模式)
读取 docs/ 中的文档 → 中文友好切片 → 调用 LM Studio 向量化 → 存入 ChromaDB Server
支持：PDF / Word / TXT / 代码文件等 30+ 格式
用法：python build_kb.py [--collection NAME]
"""
import os
import sys
import time
import hashlib
import argparse
from pathlib import Path
from typing import List

from openai import OpenAI
import chromadb
from pypdf import PdfReader
from docx import Document as DocxDocument

import config


def get_base_dir() -> Path:
    return Path(__file__).resolve().parent


def read_pdf(filepath: str) -> str:
    reader = PdfReader(filepath)
    texts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            texts.append(t)
    return "\n".join(texts)


def read_docx(filepath: str) -> str:
    doc = DocxDocument(filepath)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_txt(filepath: str) -> str:
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""


def read_md(filepath: str) -> str:
    return read_txt(filepath)


SUPPORTED_EXT = {
    ".pdf":  read_pdf,
    ".docx": read_docx,
    ".txt":  read_txt,
    ".md":   read_md,
    ".py":   read_txt,
    ".js":   read_txt,
    ".ts":   read_txt,
    ".java": read_txt,
    ".c":    read_txt,
    ".cpp":  read_txt,
    ".go":   read_txt,
    ".rs":   read_txt,
    ".r":    read_txt,
    ".R":    read_txt,
    ".sh":   read_txt,
    ".ps1":  read_txt,
    ".swift": read_txt,
    ".kt":   read_txt,
    ".rb":   read_txt,
    ".lua":  read_txt,
    ".sql":  read_txt,
    ".json": read_txt,
    ".yaml": read_txt,
    ".yml":  read_txt,
    ".csv":  read_txt,
    ".xml":  read_txt,
    ".toml": read_txt,
    ".ini":  read_txt,
    ".cfg":  read_txt,
    ".conf": read_txt,
    ".log":  read_txt,
    ".html": read_txt,
    ".css":  read_txt,
}


def load_all_documents(docs_dir: Path) -> List[dict]:
    documents = []
    seen = set()

    for ext, reader_fn in SUPPORTED_EXT.items():
        for f in docs_dir.glob(f"**/*{ext}"):
            if not f.is_file():
                continue
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)

            try:
                text = reader_fn(str(f))
                if text.strip():
                    rel = f.relative_to(docs_dir)
                    documents.append({"path": str(f), "text": text})
                    print(f"  [OK] {rel} ({len(text)} 字)")
                else:
                    print(f"  [跳过] {f.name} (无文字内容)")
            except Exception as e:
                print(f"  [失败] {f.name}: {e}")
    print(f"\n共加载 {len(documents)} 份文档")
    return documents


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    sep = config.CHINESE_SEPARATORS
    parts = [text]
    for s in sep:
        if not s:
            continue
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(s))
        parts = new_parts
    segments = [seg.strip() for seg in parts if seg.strip()]

    chunks = []
    current_chunk = ""
    for seg in segments:
        if current_chunk and len(current_chunk) + len(seg) > chunk_size:
            chunks.append(current_chunk.strip())
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:] + seg
            else:
                current_chunk = seg
        else:
            if current_chunk:
                current_chunk += " " + seg
            else:
                current_chunk = seg
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    for i, ch in enumerate(chunks):
        if len(ch) > chunk_size * 1.5:
            sub_chunks = []
            for j in range(0, len(ch), chunk_size):
                sub_chunks.append(ch[j:j+chunk_size])
            chunks[i:i+1] = sub_chunks

    return chunks


def md5_short(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


class EmbeddingClient:
    """LM Studio 嵌入客户端——预计算向量，不耦合 ChromaDB"""

    def __init__(self, openai_client: OpenAI, model: str, dim: int):
        self._client = openai_client
        self._model = model
        self._dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        batch_size = 20
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            for item in resp.data:
                vec = item.embedding
                if len(vec) != self._dim:
                    raise ValueError(
                        f"LM Studio 返回向量维度 {len(vec)}，期望 {self._dim}。"
                        f"请检查 {self._model} 模型配置"
                    )
                embeddings.append(vec)
        return embeddings


def build_knowledge_base(collection_name: str = None):
    if collection_name is None:
        collection_name = config.COLLECTION_NAME

    base_dir = get_base_dir()
    docs_dir = base_dir / config.DOCS_DIR

    print("=" * 60)
    print("  QwenKB V1.1 — 知识库构建 (Client-Server)")
    print("=" * 60)

    if not docs_dir.exists():
        print(f"\n创建文档文件夹: {docs_dir}")
        docs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n文档目录: {docs_dir}")
    print(f"ChromaDB Server: {config.CHROMA_SERVER_HOST}:{config.CHROMA_SERVER_PORT}")
    print(f"集合名称: {collection_name}")

    print("\n[1/4] 连接 ChromaDB Server...")
    chroma_client = chromadb.HttpClient(
        host=config.CHROMA_SERVER_HOST,
        port=config.CHROMA_SERVER_PORT,
    )
    try:
        heartbeat = chroma_client.heartbeat()
        print(f"  已连接 (心跳: {heartbeat} ns)")
    except Exception as e:
        print(f"  无法连接 ChromaDB Server: {e}")
        print(f"  请先启动: start_chroma_server.bat")
        return

    print("\n[2/4] 加载文档...")
    documents = load_all_documents(docs_dir)
    if not documents:
        print("没有找到任何文档，请将文件放入 docs/ 文件夹后重试。")
        return

    print("\n  文本切片...")
    all_chunks = []
    for doc in documents:
        chunks = split_text(doc["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "id": f"{md5_short(doc['path'])}-{i}",
                "text": chunk,
                "source": doc["path"],
                "chunk_index": i,
            })
    print(f"  共切出 {len(all_chunks)} 个文本块")

    print("\n[3/4] 初始化 LM Studio 嵌入服务...")
    print(f"  地址: {config.EMBEDDING_API_URL}")
    print(f"  模型: {config.EMBEDDING_MODEL}")
    print(f"  维度: {config.EMBEDDING_DIM}")

    oai_client = OpenAI(
        api_key=config.EMBEDDING_API_KEY,
        base_url=config.EMBEDDING_API_URL.rsplit("/v1/", 1)[0] + "/v1/",
    )
    emb_client = EmbeddingClient(oai_client, config.EMBEDDING_MODEL, config.EMBEDDING_DIM)

    print("\n[4/4] 向量化并存入 ChromaDB (全量重建)...")

    try:
        chroma_client.delete_collection(collection_name)
        print("  已清空旧集合")
    except Exception:
        print("  创建新集合")

    collection = chroma_client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    add_batch_size = 50
    total = len(all_chunks)
    for i in range(0, total, add_batch_size):
        batch = all_chunks[i:i+add_batch_size]
        ids = [c["id"] for c in batch]
        texts = [c["text"] for c in batch]
        metas = [{"source": c["source"], "chunk_index": c["chunk_index"]} for c in batch]

        embeddings = emb_client.embed(texts)

        collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)

        pct = min(100, int((i + len(batch)) / total * 100))
        done = i + len(batch)
        print(f"  进度: {done}/{total} ({pct}%)")

        if i + add_batch_size < total:
            time.sleep(0.1)

    count = collection.count()
    print(f"\n" + "=" * 60)
    print(f"  建库完成！集合 '{collection_name}': {count} 个向量，{len(documents)} 份文档")
    print(f"  ChromaDB Server: {config.CHROMA_SERVER_HOST}:{config.CHROMA_SERVER_PORT}")
    print(f"  下一步: 启动 MCP 服务器 → python mcp_server.py")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QwenKB 知识库构建工具")
    parser.add_argument(
        "--collection", "-c",
        type=str,
        default=None,
        help=f"集合名称 (默认: {config.COLLECTION_NAME})",
    )
    args = parser.parse_args()
    build_knowledge_base(collection_name=args.collection)
