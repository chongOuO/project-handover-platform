"""docker-compose.yml 生成節點 (Generate Compose Node)。

固定執行節點，依據 has_database 與 detected_db_type 決定
docker-compose.yml 是否包含獨立的 DB service 區塊。
委派給 LLM 產出可直接使用的 docker-compose.yml 文字。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.dockerfile_state import DockerfileGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: 各 DB 類型對應的 Docker 官方 image 推薦版本。
_DB_IMAGE_MAP: dict[str, str] = {
    "postgresql": "postgres:16-alpine",
    "mysql": "mysql:8.4",
    "redis": "redis:7-alpine",
    "mongodb": "mongo:7",
}

COMPOSE_PROMPT_TEMPLATE = """\
你是一位 DevOps 專家。請根據以下專案資訊，產出一份完整可用的 docker-compose.yml（版本格式需相容 Docker Compose v2）。

已偵測的專案資訊：
- 主要語言：{language}
- 框架：{framework}
- 是否有資料庫服務：{has_database}
- 資料庫類型：{db_type}
- 資料庫 Docker Image：{db_image}

撰寫要求：
1. 僅輸出純 docker-compose.yml 文字，**不要**使用 Markdown code fence（禁止 ```yaml ... ```）。
2. 必須包含 `services:` 區塊，並定義 `api` service：
   - `build: .`（使用當前目錄的 Dockerfile）
   - `ports: - "8000:8000"`（若有其他慣用 port 請依語言調整）
   - `environment:` 區塊，以 KEY=value 格式列出常見環境變數（例如 DATABASE_URL、SECRET_KEY 等）
   - `restart: unless-stopped`
3. 若 has_database 為 True：
   - 新增對應的 DB service，使用指定的 db_image。
   - `api` service 加入 `depends_on: [db]`。
   - DB service 加入 `volumes:` 以持久化資料。
   - 在檔案末尾加入對應的 `volumes:` 區塊宣告。
4. 若 has_database 為 False：
   - 只輸出 `api` service 即可，無需 DB service。
5. 在關鍵設定前加入簡短的繁體中文行內註解（以 # 開頭）。
6. 環境變數的值請使用佔位符格式（例如 your_password_here）並加入 # TODO 提示。

=== 請在下方直接輸出純 docker-compose.yml 內容 ===
"""


async def generate_compose_node(state: DockerfileGraphState, config: Any) -> dict[str, Any]:
    """執行 docker-compose.yml 生成的 LangGraph 節點。

    依據 has_database 與 detected_db_type 組建 Prompt，
    呼叫 LLM 生成完整的 docker-compose.yml，並將結果寫入 ``compose_content``。

    Args:
        state: Dockerfile Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含 ``compose_content`` 更新的字典；若發生錯誤則回傳 fallback 基本版本。
    """
    logger.info("[generate_compose_node] 開始呼叫 LLM 產出 docker-compose.yml...")

    language: str = state.get("detected_language", "unknown")
    framework: str | None = state.get("detected_framework")
    has_database: bool = state.get("has_database", False)
    detected_db_type: str | None = state.get("detected_db_type")
    db_image: str = _DB_IMAGE_MAP.get(detected_db_type or "", "")

    prompt = COMPOSE_PROMPT_TEMPLATE.format(
        language=language,
        framework=framework or "未偵測到特定框架",
        has_database="是" if has_database else "否",
        db_type=detected_db_type or "無",
        db_image=db_image or "無",
    )

    llm = LLMClient()
    try:
        raw_result = await llm.complete(prompt)
        # 清理可能誤加的 code fence
        content = raw_result.strip()
        for prefix in ("```yaml", "```yml", "```"):
            if content.startswith(prefix):
                content = content[len(prefix):]
                break
        if content.endswith("```"):
            content = content[:-3]
        compose_content = content.strip()

        logger.info(
            "[generate_compose_node] 生成完成，docker-compose.yml 長度: %d 字元。",
            len(compose_content),
        )
        return {"compose_content": compose_content}
    except Exception as exc:
        logger.error("[generate_compose_node] LLM 生成發生錯誤: %s", exc, exc_info=True)
        # 回傳最小化 fallback compose
        fallback = (
            "services:\n"
            "  api:\n"
            "    build: .\n"
            "    ports:\n"
            '      - "8000:8000"\n'
            "    restart: unless-stopped\n"
            f"    # 錯誤：docker-compose.yml 生成失敗 — {exc}\n"
        )
        return {"compose_content": fallback, "error": str(exc)}
