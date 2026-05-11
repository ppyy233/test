# -*- coding: utf-8 -*-
"""
QwenKB V1.0 — 知识库构建脚本
读取 docs/ 中的文档 → 中文友好切片 → 调用 LM Studio 向量化 → 存入 ChromaDB
支持：PDF / Word / TXT，含编码兜底、缓存检测、批量处理
"""
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import List, Optional

from openai import OpenAI
import chromadb
from pypdf import PdfReader
from docx import Document as DocxDocument
import chromadb.utils.embedding_functions as ef

import config

def get_base_dir() -> Path:
    """获取 config.py 所在目录（即项目根目录）"""
    return Path(__file__).resolve().parent

def read_pdf(filepath: str) -> str:
    """读取 PDF 文件，返回纯文本"""
    reader = PdfReader(filepath)
    texts = []
    for i, page in enumerate(reader.pages):
        t = page.extract_text()
        if t:
            texts.append(t)
    return "\n".join(texts)

def read_docx(filepath: str) -> str:
    """读取 Word 文件，返回纯文本"""
    doc = DocxDocument(filepath)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def read_txt(filepath: str) -> str:
    """读取 TXT 文件，自动尝试 UTF-8 / GBK 编码"""
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""

def read_md(filepath: str) -> str:
    """读取 Markdown 文件"""
    return read_txt(filepath)

SUPPORTED_EXT = {
    ".pdf":  read_pdf,
    ".docx": read_docx,
    ".txt":  read_txt,
    ".md":   read_md,
}

def load_all_documents(docs_dir: Path) -> List[dict]:
    """遍历文件夹，加载所有支持的文档，返回 [{path, text}] 列表"""
    documents = []
    for ext in SUPPORTED_EXT:
        for f in docs_dir.glob(f"*{ext}"):
            try:
                text = SUPPORTED_EXT[ext](str(f))
                if text.strip():
                    documents.append({"path": str(f), "text": text})
                    print(f"  [OK] {f.name} ({len(text)} 字)")
                else:
                    print(f"  [跳过] {f.name} (无文字内容)")
            except Exception as e:
                print(f"  [失败] {f.name}: {e}")
    print(f"\n共加载 {len(documents)} 份文档")
    return documents

def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    中文友好文本切片：
    1. 先按中文标点 + 换行符切段
    2. 每段接近 chunk_size 的时候作为一个 chunk
    3. 相邻 chunk 保留 overlap 的尾部内容
    """
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

class LMStudioEmbeddingFunction(ef.EmbeddingFunction):
    """ChromaDB 兼容的 LM Studio 嵌入函数"""
    def __init__(self, openai_client: OpenAI, model: str, dim: int):
        self._client = openai_client
        self._model = model
        self._dim = dim

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        embeddings = []
        batch_size = 20
        for i in range(0, len(input), batch_size):
            batch = input[i:i+batch_size]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            for item in resp.data:
                vec = item.embedding
                if len(vec) > self._dim:
                    vec = vec[:self._dim]
                embeddings.append(vec)
        return embeddings

def build_knowledge_base():
    """主流程：建库"""
    base_dir = get_base_dir()
    docs_dir = base_dir / config.DOCS_DIR
    chroma_dir = base_dir / config.CHROMA_DIR

    print("=" * 60)
    print("  QwenKB V1.0 — 知识库构建")
    print("=" * 60)

    if not docs_dir.exists():
        print(f"\n创建文档文件夹: {docs_dir}")
        docs_dir.mkdir(parents=True, exist_ok=True)
    if not chroma_dir.exists():
        chroma_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n文档目录: {docs_dir}")
    print(f"数据库目录: {chroma_dir}")

    print("\n[1/4] 加载文档...")
    documents = load_all_documents(docs_dir)
    if not documents:
        print("没有找到任何文档，请将 PDF/Word/TXT 文件放入 docs/ 文件夹后重试。")
        return

    print("\n[2/4] 文本切片...")
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

    print("\n[3/4] 向量化（调用 LM Studio）...")
    print(f"  地址: {config.EMBEDDING_API_URL}")
    print(f"  模型: {config.EMBEDDING_MODEL}")

    oai_client = OpenAI(
        api_key=config.EMBEDDING_API_KEY,
        base_url=config.EMBEDDING_API_URL.rsplit("/v1/", 1)[0] + "/v1/",
    )

    emb_fn = LMStudioEmbeddingFunction(oai_client, config.EMBEDDING_MODEL, config.EMBEDDING_DIM)

    print("\n[4/4] 存入 ChromaDB...")
    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))

    collection_name = "qwenkb_docs"
    try:
        chroma_client.delete_collection(collection_name)
        print("  已清空旧数据库，重新构建")
    except Exception:
        pass

    collection = chroma_client.create_collection(
        name=collection_name,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"},
    )

    batch_size = 50
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i+batch_size]
        ids   = [c["id"]   for c in batch]
        texts = [c["text"] for c in batch]
        metas = [{"source": c["source"], "chunk_index": c["chunk_index"]} for c in batch]
        collection.add(ids=ids, documents=texts, metadatas=metas)
        pct = min(100, int((i + len(batch)) / len(all_chunks) * 100))
        print(f"  进度: {i+len(batch)}/{len(all_chunks)} ({pct}%)")

    count = collection.count()
    print(f"\n" + "=" * 60)
    print(f"  建库完成！共 {count} 个向量，{len(documents)} 份文档")
    print(f"  数据库位置: {chroma_dir}")
    print(f"  下一步: 启动 MCP 服务器 → python mcp_server.py")
    print("=" * 60)

if __name__ == "__main__":
    build_knowledge_base()
