""".dockerignore 生成節點 (Generate Dockerignore Node)。

根據偵測到的語言與框架，委派給 LLM 生成對應的 .dockerignore，
確保建立 Docker image 時排除不必要的檔案（開發工具、虛擬環境、快取等），
縮短 build context 傳輸時間並避免洩漏敏感資訊。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.dockerfile_state import DockerfileGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

DOCKERIGNORE_PROMPT_TEMPLATE = """\
你是一位 DevOps 專家。請根據以下專案資訊，產出一份完整的 .dockerignore 檔案。

已偵測的專案資訊：
- 主要語言：{language}
- 框架：{framework}

.dockerignore 撰寫要求：
1. 僅輸出純 .dockerignore 文字內容，**不要**使用 Markdown code fence。
2. 每行一條規則，可加入簡短的行內中文註解（以 # 開頭）。
3. 必須涵蓋以下通用類別（依語言選擇對應規則）：
   - 版本控制：.git、.gitignore
   - 開發環境：.env、.env.*（保留 .env.example 說明除外）
   - 虛擬環境 / 套件目錄：venv、.venv、node_modules、vendor、target
   - 編譯產物快取：__pycache__、*.pyc、*.pyo、.next、dist、build、target
   - IDE / Editor 設定：.vscode、.idea、*.swp
   - 測試與覆蓋率：.pytest_cache、coverage、.nyc_output
   - OS 快取：.DS_Store、Thumbs.db
   - 文件：docs、*.md（README.md 保留）
4. 以分類區塊輸出，每個區塊前加入 # === 類別名稱 === 的分隔標題。

=== 請在下方直接輸出純 .dockerignore 內容 ===
"""


async def generate_dockerignore_node(state: DockerfileGraphState, config: Any) -> dict[str, Any]:
    """執行 .dockerignore 生成的 LangGraph 節點。

    依據偵測到的語言與框架呼叫 LLM，將結果寫入 ``dockerignore_content``。

    Args:
        state: Dockerfile Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含 ``dockerignore_content`` 更新的字典；若發生錯誤則回傳通用預設值。
    """
    logger.info("[generate_dockerignore_node] 開始呼叫 LLM 產出 .dockerignore...")

    language: str = state.get("detected_language", "unknown")
    framework: str | None = state.get("detected_framework")

    prompt = DOCKERIGNORE_PROMPT_TEMPLATE.format(
        language=language,
        framework=framework or "未偵測到特定框架",
    )

    llm = LLMClient()
    try:
        raw_result = await llm.complete(prompt)
        # 清理可能誤加的 code fence
        content = raw_result.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        dockerignore_content = content.strip()

        logger.info(
            "[generate_dockerignore_node] 生成完成，.dockerignore 長度: %d 字元。",
            len(dockerignore_content),
        )
        return {"dockerignore_content": dockerignore_content}
    except Exception as exc:
        logger.error("[generate_dockerignore_node] LLM 生成發生錯誤: %s", exc, exc_info=True)
        # 回傳通用安全的 fallback .dockerignore
        fallback = (
            "# === 版本控制 ===\n.git\n.gitignore\n\n"
            "# === 環境變數 ===\n.env\n.env.*\n\n"
            "# === 虛擬環境 ===\nvenv\n.venv\nnode_modules\n\n"
            "# === 快取 ===\n__pycache__\n*.pyc\n.next\ndist\nbuild\n\n"
            "# === IDE ===\n.vscode\n.idea\n\n"
            "# === OS ===\n.DS_Store\nThumbs.db"
        )
        return {"dockerignore_content": fallback, "error": str(exc)}
