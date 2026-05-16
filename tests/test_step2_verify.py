# HNSW Index Persistence Bug Reproduction — Step 2: Verify
#
# Run this AFTER restarting the ChromaDB server following test_step1_setup.py.
# Expected: InternalError "Error loading hnsw index"

import chromadb
import sys

HOST = "127.0.0.1"
PORT = 9898
COLLECTION = "hnsw_bug_test"

print("=" * 60)
print("  HNSW Persistence Bug — Step 2: Verify (after restart)")
print("=" * 60)

client = chromadb.HttpClient(host=HOST, port=PORT)
col = client.get_collection(COLLECTION)

try:
    count = col.count()
    print(f"  Count: {count}")
    r = col.query(query_embeddings=[[0.0]*2560], n_results=2)
    print(f"  Query: OK (nearest: {r['ids'][0][:2]})")
    print()
    print("  Bug NOT reproduced — HNSW index survived restart.")
    print("  This is unexpected with default sync_threshold=1000.")
except chromadb.errors.InternalError as e:
    print(f"  Count: FAILED")
    print(f"  Error: {e}")
    print()
    print("=" * 60)
    print("  Bug CONFIRMED: HNSW index corrupted after restart.")
    print("  This is the ChromaDB 1.5.9 HNSW persistence bug.")
    print("=" * 60)
except Exception as e:
    print(f"  Unexpected error: {e}")
