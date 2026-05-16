# HNSW Index Persistence Bug — Step 3: Workaround Test
#
# Demonstrates that sync_threshold=100000 prevents the bug.
# Run this, then restart server, then run test_step2_verify.py again.

import chromadb
import random

HOST = "127.0.0.1"
PORT = 9898
COLLECTION = "hnsw_bug_test"

print("=" * 60)
print("  HNSW Persistence Bug — Step 3: Workaround")
print("=" * 60)
print("  Using sync_threshold=100000 (> total items)")
print()

client = chromadb.HttpClient(host=HOST, port=PORT)

# Clean up and recreate with workaround
try:
    client.delete_collection(COLLECTION)
except Exception:
    pass

col = client.create_collection(
    name=COLLECTION,
    metadata={
        "hnsw:space": "cosine",
        "hnsw:sync_threshold": 100000,  # Fix: prevent compaction
    },
)

n = 1200
dim = 2560
print(f"  Adding {n} random embeddings ({dim}-dim)...")
ids = [f"id_{i}" for i in range(n)]
embs = [[random.random() for _ in range(dim)] for _ in range(n)]
col.add(ids=ids, embeddings=embs)

print(f"  Count: {col.count()}")
r = col.query(query_embeddings=[embs[0]], n_results=2)
print(f"  Query: OK")

print()
print("=" * 60)
print("  Now restart the server and run test_step2_verify.py")
print("  Expected: OK (sync_threshold=100000 prevents compaction)")
print("=" * 60)
