"""DB 偵測節點 (Detect DB Node)。

負責掃描 Markdown 全文，以關鍵字快篩專案內是否包含資料庫相關程式碼，
例如 SQLAlchemy, Entity, schemas, models.py, migration 等。
不呼叫 LLM，藉以節省成本及加速執行。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.graphs.diagram_state import DiagramGraphState

logger = logging.getLogger(__name__)

# 常見資料庫使用與 ORM 相關關鍵字列表（轉換至小寫比對）
DB_KEYWORDS = [
    "sqlalchemy",
    "alembic",
    "migration",
    "models.py",
    "schema",
    "@entity",
    "create table",
    "database_url",
    "pymysql",
    "psycopg2",
    "django.db",
    "typeorm",
    "prisma",
    "mongoose",
]


async def detect_db_node(state: DiagramGraphState, config: Any) -> dict[str, Any]:
    """分析原始內容，判斷專案是否包含資料庫。

    將結果回寫至 ``has_database`` 屬性中。

    Args:
        state: Diagram Graph 的當前狀態字典。
        config: LangGraph 執行環境設定（通常不用在此操作）。

    Returns:
        包含局部更新的回傳字典，將合併至下一個狀態中。
    """
    logger.info("[detect_db_node] 開始偵測專案是否使用資料庫...")

    markdown_content = state.get("markdown_content", "")
    content_lower = markdown_content.lower()

    has_db = False
    for kw in DB_KEYWORDS:
        if kw in content_lower:
            has_db = True
            logger.info("[detect_db_node] 偵測到關鍵字 '%s'，判定有使用資料庫。", kw)
            break
    
    # 也可用正則來找類似 SQL 語法 (以備不時之需)
    if not has_db:
        if re.search(r"insert\s+into", content_lower) or re.search(r"select\s+\*\s+from", content_lower):
            has_db = True
            logger.info("[detect_db_node] 偵測到 SQL 語法，判定有使用資料庫。")

    if not has_db:
        logger.info("[detect_db_node] 未偵測到資料庫相關關鍵字。")

    return {"has_database": has_db}
