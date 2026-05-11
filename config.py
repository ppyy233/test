# ============================================================
# QwenKB V1.0 — 集中配置文件
# 所有参数在这里改，代码文件不需要动
# ============================================================

# ====== LM Studio 本地嵌入服务 ======
# 你在 LM Studio 启动的 Qwen3-Embedding 服务
EMBEDDING_API_URL = "http://127.0.0.1:5000/v1/embeddings"
EMBEDDING_API_KEY = "sk-lm-BBuRxqql:eF7OaGux1FP7KQyrT9Re"
EMBEDDING_MODEL  = "text-embedding-qwen3-embedding-4b"
EMBEDDING_DIM    = 2560   # Qwen3-Embedding-4B 的向量维度

# ====== DeepSeek 对话 API（opencode 后端用，本脚本不直接调用） ======
DEEPSEEK_API_KEY = "sk-b952a6cbba5f445ba3372d33cd160dde"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ====== 文档和存储路径 ======
# 这些是相对于本 config.py 所在目录的路径
DOCS_DIR   = "docs"         # 放 PDF/Word/TXT 的文件夹
CHROMA_DIR = "chroma_db"    # 向量数据库存储文件夹

# ====== 文档切片参数 ======
CHUNK_SIZE    = 500   # 每块最多 500 字（中文一个汉字 = 1 字）
CHUNK_OVERLAP = 50    # 相邻块重叠 50 字，防止关键句被切断

# 中文分隔符优先级：先按段落/句子边界切，切不动再按字数硬切
CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", " "]

# ====== 检索参数 ======
RETRIEVAL_K          = 5     # 每次搜索返回多少条结果
RETRIEVAL_FETCH_K    = 15    # MMR 检索时先粗筛多少条（通常 k × 3）
RETRIEVAL_LAMBDA     = 0.7   # MMR 权重：0=最多样化 1=最相似
RETRIEVAL_THRESHOLD  = 0.3   # 相似度最低阈值，低于这个的不要

# ====== MCP 服务器参数 ======
MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8766

# ====== LLM 问答提示词 ======
# 知识库优先 + 不禁止外部知识 + 标注来源
ANSWER_PROMPT = """你是一个专业的问答助手。回答用户问题时请遵循以下规则：

1. 优先参考提供的【知识库资料】来回答问题。
2. 如果知识库中有相关答案，用它回答，并注明来源。
3. 如果知识库信息不足以回答，可以结合你的通用知识补充，但要明确区分：
   - 【来自知识库：xxx】
   - 【来自通用知识：xxx】
4. 如果知识库信息与通用知识矛盾，指出来，让用户自行判断。
5. 保持回答简洁、准确、客观。

【知识库资料】
{context}

【用户问题】
{question}

【回答】"""
