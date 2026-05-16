> **Note**: This issue report was generated with AI assistance (OpenCode + DeepSeek-V4). All test data, reproduction steps, and gradient testing results are real and independently verifiable.

---

# HNSW index not surviving server restart in C/S mode when collection exceeds ~1000 embeddings (ChromaDB 1.5.9)

## Environment

- **chromadb version**: 1.5.9
- **Python**: 3.11
- **OS**: Windows 10
- **Mode**: Client-Server (chroma server via `chromadb.server.fastapi.FastAPI`)
- **Client**: `chromadb.HttpClient` for writes, `chromadb.AsyncHttpClient` for queries
- **Persistence**: local disk, `is_persistent=True`

## Summary

When a collection exceeds approximately 1000 embeddings, the HNSW index becomes **permanently corrupted after any server restart** (including graceful shutdown). Below ~1000 items, persistence works correctly. The bug renders the knowledge base unusable after a machine reboot.

## Error

```
chromadb.errors.InternalError: Error executing plan: Error sending backfill request to compactor:
Error constructing hnsw segment reader: Error creating hnsw segment reader:
Error loading hnsw index
```

## Reproduction (minimal)

Start a ChromaDB server on port 9898:

```bash
python -c "import uvicorn; from chromadb.server.fastapi import FastAPI; from chromadb.config import Settings; s=Settings(chroma_server_host='127.0.0.1',chroma_server_http_port=9898,persist_directory='./chroma_db',is_persistent=True,anonymized_telemetry=False); server=FastAPI(s); uvicorn.run(server.app(),host='127.0.0.1',port=9898)"
```

Then run:

```python
import chromadb, random

c = chromadb.HttpClient(host="127.0.0.1", port=9898)

# Default HNSW config (sync_threshold=1000)
col = c.create_collection(name="test_repro", metadata={"hnsw:space": "cosine"})

# Add 1200 random embeddings
n, dim = 1200, 2560
ids = [f"id_{i}" for i in range(n)]
embs = [[random.random() for _ in range(dim)] for _ in range(n)]
col.add(ids=ids, embeddings=embs)

print(col.count())  # 1200 OK
col.query(query_embeddings=[embs[0]], n_results=2)  # OK
```

Restart the ChromaDB server (Ctrl+C, then start again).

After restart:

```python
c2 = chromadb.HttpClient(host="127.0.0.1", port=9898)
col2 = c2.get_collection("test_repro")
col2.count()  # ❌ InternalError: Error loading hnsw index
```

### Runnable reproduction scripts

Available at [github.com/ppyy233/qwen-embedding-MCP-/tree/master/tests](https://github.com/ppyy233/qwen-embedding-MCP-/tree/master/tests):

| Script | Purpose |
|--------|---------|
| `tests/test_step1_setup.py` | Create collection, add 1200 items, verify query works |
| `tests/test_step2_verify.py` | After server restart: verifies the HNSW crash |
| `tests/test_step3_workaround.py` | Rebuilds with `sync_threshold=100000`, restart-safe |

## Gradient Testing Results

Systematically tested different dataset sizes and `sync_threshold` values:

| sync_threshold | items | Compactions | Restart |
|---|---|---|---|
| 1000 (default) | 50   | 0 | ✅ |
| 1000 (default) | 500  | 0 | ✅ |
| 1000 (default) | 1000 | 1 | ❌ |
| 1000 (default) | 1200 | 1+ | ❌ |
| 1000 (default) | 1500 | 1+ | ❌ |
| 1000 (default) | 2000 | 2 | ❌ |
| 50   | 5000 | many | ❌ |
| 100  | 100  | 1 | ❌ |
| 100  | 120  | 1+ | ❌ |
| 200  | 200  | 1 | ❌ |
| 2000 | 5022 | 2+ | ❌ |
| **10000** | **5022** | **0** | **✅** |

**Key finding**: The bug is triggered whenever the HNSW Compactor runs at least once (i.e. `total_items >= sync_threshold`). Data amount and divisibility don't matter. The only surviving case is `sync_threshold > total_items` (Compactor never runs).

## Root Cause Hypothesis

Based on the analysis of related issue [#7069](https://github.com/chroma-core/chroma/issues/7069) and local Rust binary strings extraction:

1. The Rust backend's HNSW Compactor writes `index_metadata.pickle` with a **buggy serialization format** in 1.5.9
2. On server restart, the Rust backend tries to load this pickle → deserialization fails → `HnswIndexLoadError`
3. Since the Compactor also **purges WAL entries** after writing the pickle, there is no fallback data to rebuild from
4. When `sync_threshold > total_items`, the Compactor **never runs**, no pickle is written, all data stays in WAL, and the server successfully rebuilds HNSW from WAL on restart

Evidence from [#7069](https://github.com/chroma-core/chroma/issues/7069): the `length.bin` HNSW file had its first 4 bytes as the IEEE 754 representation of `float 1.0` instead of the expected `u32` count value, strongly suggesting a **float/int serialization mismatch** in the Rust compactor.

Related: [#6852](https://github.com/chroma-core/chroma/issues/6852), [#1355](https://github.com/chroma-core/chroma/issues/1355)

## Workaround

Set `sync_threshold` to a value larger than the expected total embeddings:

```python
collection = chroma_client.create_collection(
    name="my_collection",
    metadata={
        "hnsw:space": "cosine",
        "hnsw:sync_threshold": 100000,   # > expected total items
    },
)
```

**Tradeoffs**: WAL is never purged (vectors stored twice), ~2s restart latency per 5000 items for WAL replay. Acceptable for collections under ~100k items.

## Expected Behavior

HNSW index should be correctly persisted to disk and loadable after server restart, regardless of collection size or `sync_threshold` value.
