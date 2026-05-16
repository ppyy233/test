# HNSW Index Persistence Bug Reproduction
# ChromaDB 1.5.9, Client-Server mode
#
# Step 1: Start a ChromaDB server on port 9898
#   python _run_server.py
#
# Step 2: Run this script
#   python tests/test_step1_setup.py
#
# Step 3: Restart the ChromaDB server (stop it, start it again)
#
# Step 4: Run the verification script
#   python tests/test_step2_verify.py
#   Expected: InternalError "Error loading hnsw index"
#
# Step 5 (optional): Reset and test workaround
#   python tests/test_step3_workaround.py
#   Restart server
#   python tests/test_step2_verify.py
#   Expected: OK (sync_threshold=100000 prevents compaction)

import chromadb
import random
import sys

HOST = "127.0.0.1"
PORT = 9898
COLLECTION = "hnsw_bug_test"

print("=" * 60)
print("  HNSW Persistence Bug — Step 1: Setup")
print("=" * 60)
print(f"  Server: {HOST}:{PORT}")
print(f"  chromadb version: {chromadb.__version__}")
print()

# Connect
try:
    client = chromadb.HttpClient(host=HOST, port=PORT)
    client.heartbeat()
    print("  Server: connected")
except Exception as e:
    print(f"  Server: NOT REACHABLE ({e})")
    print("  Make sure chroma server is running on port 9898")
    sys.exit(1)

# Clean up and create collection
try:
    client.delete_collection(COLLECTION)
except Exception:
    pass

col = client.create_collection(
    name=COLLECTION,
    metadata={"hnsw:space": "cosine"},  # default sync_threshold=1000
)

# Add 1200 random embeddings (2560-dim, like Qwen3-Embedding-4B)
n = 1200
dim = 2560
print(f"  Adding {n} random embeddings ({dim}-dim)...")

ids = [f"id_{i}" for i in range(n)]
embs = [[random.random() for _ in range(dim)] for _ in range(n)]
col.add(ids=ids, embeddings=embs)

print(f"  Count: {col.count()}")
r = col.query(query_embeddings=[embs[0]], n_results=2)
print(f"  Query: OK (nearest: {r['ids'][0][:2]})")

print()
print("=" * 60)
print("  Setup complete. Now:")
print("  1. Restart your ChromaDB server (stop it, start it)")
print("  2. Run: python tests/test_step2_verify.py")
print("=" * 60)
