# ChromaDB 1.5.9 HNSW 索引持久化 Bug 技术分析

**项目**: QwenKB / local-database
**日期**: 2026-05-16
**版本**: chromadb==1.5.9

---

## 问题概述

ChromaDB 1.5.9 在 C/S（Client-Server）模式下，单集合数据量超过约 1000 条后，HNSW 向量索引在服务器重启后无法加载，报错：

```
InternalError: Error executing plan: Error sending backfill request to compactor:
Error constructing hnsw segment reader: Error creating hnsw segment reader:
Error loading hnsw index
```

**影响**: 电脑重启后知识库完全不可用，必须重新建库。

---

## 架构背景

### ChromaDB 本地 C/S 模式数据流

```
collection.add(embeddings)
    │
    ├── ① SQLite embedding 表 ─── 同步写入，持久化  ✓
    ├── ② embeddings_queue (WAL) ─ 同步写入，持久化  ✓
    └── ③ HNSW 索引 ──────────── 异步 Compactor 构建
              │
              ├── 攒够 sync_threshold 条后触发 compaction
              ├── 写 index_metadata.pickle 到磁盘
              └── purge WAL 中已 compacted 的条目
```

**关键**：HNSW 索引在 Rust 进程内存中一直可用（查询正常），但持久化依赖于 Compactor 后台线程。Compactor 触发后，HNSW 索引从"纯内存"变成"磁盘 + 剩余 WAL"，进入混合状态。

### ChromaDB 1.5.x 后端

1.5.0 起默认使用 Rust 原生后端 (`chromadb_rust_bindings.pyd`)。HNSW 索引的序列化/反序列化逻辑在编译后的二进制文件中，Python 侧无法干预。

---

## 根因分析

### 核心 Bug

**1.5.9 Rust 后端的 HNSW Compactor 写出的 `index_metadata.pickle` 二进制格式存在 bug，自己反序列化时会失败。**

#### 独立验证证据

GitHub Issue [#7069](https://github.com/chroma-core/chroma/issues/7069) 报告同类问题，关键发现：

- HNSW `length.bin` 文件 8604 字节（预期 ~4 字节的 u32 计数值）
- 前 4 字节解析为 u32 = 1,065,353,217
- **该值是 IEEE 754 单精度浮点数 1.0 的二进制表示**
- 说明 Rust 序列化代码将 float 误写入本应为 int 的字段（内存对齐/类型错误）

关联 Issue:
- [#6852](https://github.com/chroma-core/chroma/issues/6852): macOS ARM64 segfault
- [#1355](https://github.com/chroma-core/chroma/issues/1355): Rust binding segfault in count()

### 损坏触发条件

```
Compactor 触发 → 写错误格式的 pickle 文件 → purge WAL
                                            ↓
        重启 → load pickle（反序列化失败）→ 无 WAL 可回退 → 永久损坏
```

### 为什么无 Compaction 时正常

```
sync_threshold > 总数据量 → Compactor 从不触发
    ├── 无 pickle 文件
    └── WAL 保留所有数据
         ↓
    重启 → 从 WAL 逐条重放 → 完整重建 HNSW → 正常
```

**ChromaDB 设计上支持从 WAL 重建 HNSW 索引**。这是合法的回退路径，不是绕过。

---

## 梯度测试结果

| sync_threshold | 数据量 | Compaction | 重启 |
|---------------|---|---|------|
| 1000（默认） | 50   | 0 次       | ✅ |
| 1000（默认） | 500  | 0 次       | ✅ |
| 1000（默认） | 1000 | 1 次(整除) | ❌ |
| 1000（默认） | 1200 | 1 次+余量  | ❌ |
| 1000（默认） | 1500 | 1 次+余量  | ❌ |
| 1000（默认） | 2000 | 2 次(整除) | ❌ |
| 50           | 5000 | 多次       | ❌ |
| 100          | 100  | 1 次(整除) | ❌ |
| 100          | 120  | 1 次+余量  | ❌ |
| 200          | 200  | 1 次(整除) | ❌ |
| 2000         | 5022 | 2 次+余量  | ❌ |
| **10000**    | **5022** | **0 次** | **✅** |

**结论**: 只要 Compactor 触发过就该 Bug 也，与数据量、整除、sync_threshold 值都无关。唯一幸存条件是 Compactor 从未触发。

---

## 当前修复

### 方案

`build_kb.py` 建库时将 `sync_threshold` 设为大于预期最大数据量的值：

```python
collection = chroma_client.create_collection(
    name=collection_name,
    metadata={
        "hnsw:space": "cosine",
        "hnsw:sync_threshold": 100000,
    },
)
```

**原理**: `sync_threshold=100000` ≫ 当前 5022 条 + 预留增长空间，确保 Compactor 永不触发。HNSW 保持初始状态，重启时 ChromaDB 从 WAL 完整重建索引。

### 副作用

| 影响 | 规模 | 评估 |
|------|------|------|
| 重启延迟 | WAL 重放 5022 条 ~2s | 可接受 |
| 磁盘占用 | WAL 永不 purge，Embedding 向量存两份 | 5022 条时 ~32MB，可接受 |
| 内存占用 | 无影响（HNSW 索引大小不变） | 无 |

### 当前数据量验证

- 文档数: 84 份
- 向量数: 5022 条
- 重启测试: 硬杀 → 重启 → 查询正常 ✅

---

## 相关架构决策

### 为什么不退回 PersistentClient

当前架构 `HttpClient(建库) + AsyncHttpClient(查询) + ChromaDB Server(存储)` 解决了：

1. **进程隔离**: 旧 MCP Service (nssm Windows Service) 用 PersistentClient 与新 Server 同时争抢 chroma_db/ 文件锁的问题
2. **异步查询**: MCP Server 通过 AsyncHttpClient 非阻塞访问向量库
3. **关注点分离**: Embedding（LM Studio）、存储（ChromaDB Server）、查询（MCP Server）三者解耦

### 关于旧 Windows Service (PID 9032)

发现并停用了以 nssm 注册的旧 `QwenKB-MCP` Windows Service。该 Service 使用旧版 PersistentClient 代码，与新 ChromaDB Server 同时持有 chroma_db/ 文件句柄，是 HNSW 损坏的加重因素。已通过 `nssm stop` + `nssm remove` 彻底注销。

---

## 未来展望

### 版本升级

ChromaDB 1.5.10+ 预计修复 HNSW 序列化 bug。修复后：

```python
# 恢复正常的 compaction 配置
metadata={"hnsw:space": "cosine", "hnsw:sync_threshold": 1000}
```

### 数据量增长

| 规模 | 建议 |
|------|------|
| < 10 万条 | sync_threshold = 10x 数据量，WAL 重建可接受 |
| 10-50 万条 | 升级 ChromaDB 版本，恢复正常 compaction |
| > 50 万条 | 拆分多集合 + ChromaDB 分布式模式 |

### 长期推荐方案

```
建库阶段: PersistentClient 直接写（HNSW 同步落盘，备选方案）
服务阶段: ChromaDB Server + AsyncHttpClient（当前架构）
```

---

## 相关链接

- [ChromaDB Issue #7069](https://github.com/chroma-core/chroma/issues/7069) — 同根 bug（length.bin 格式损坏）
- [ChromaDB Releases](https://github.com/chroma-core/chroma/releases) — 关注 1.5.10+ 版本
- [ChromaDB Configure Collections](https://docs.trychroma.com/docs/collections/configure) — HNSW 参数文档
- [ChromaDB Serverless Architecture](https://www.trychroma.com/engineering/serverless) — Compactor 设计原理
