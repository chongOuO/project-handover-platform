"""資料庫 ER 圖生成節點 (Generate ER Node)。

僅在偵測到資料庫相關程式碼時觸發，委派 LLM 生成 Mermaid.js 的 `erDiagram` 語法，
描繪資料表結構及關聯。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.diagram_state import DiagramGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: TPM 安全上限。
_TPM_SAFE_INPUT_LIMIT: int = 90_000
_CHARS_PER_TOKEN: float = 3.5


def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


def _emergency_truncate(content: str, token_limit: int) -> str:
    target_chars = int(token_limit * _CHARS_PER_TOKEN)
    return content[:target_chars] + "\n\n<!-- [Emergency Truncation] 內容已被緊急截斷以符合 TPM 限制 -->"

ER_PROMPT_TEMPLATE = """
請你根據以下軟體專案的程式碼綱要報告，產出一份關聯式資料庫實體關聯圖 (ER Diagram)。
請使用 Mermaid.js 的 `erDiagram` 語法來描繪。

要求與規範：
1. 僅輸出純包含 Mermaid 語法的字串即可，**絕對不要**使用 Markdown code fence (例如 ```mermaid ... ```)。
2. 從程式碼中識別 Models 或 Schema 定義（如 SQLAlchemy、Django Models 等）。
3. 明確定義出 Table 與 Table 之間的關係：一對多 (||--o{{)、多對多 (}}o--o{{)、一對一 (||--||) 等。
4. 在每個實體中試著條列主要欄位與屬性（如有）。

=== 專案結構與文件內容 ===
{markdown_content}

=== 請在下方直接輸出純 Mermaid 語法 ===
"""


async def generate_er_node(state: DiagramGraphState, config: Any) -> dict[str, Any]:
    """執行 ER 圖生成的 LangGraph 節點。

    將結果回寫至 ``er_diagram``。

    Args:
        state: Diagram Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含更新的分部字典。
    """
    if not state.get("has_database", False):
        logger.info("[generate_er_node] 專案無資料庫特徵，跳過 ER 圖產生。")
        return {"er_diagram": None}

    logger.info("[generate_er_node] 開始呼叫 LLM 產出 ER 圖 (Mermaid)...")

    markdown_content = state.get("markdown_content", "")
    token_estimate = state.get("content_token_estimate", _estimate_tokens(markdown_content))
    if token_estimate > _TPM_SAFE_INPUT_LIMIT:
        logger.warning(
            "[generate_er_node] Token 估算 %d 超過安全上限 %d，執行緊急截斷。",
            token_estimate, _TPM_SAFE_INPUT_LIMIT,
        )
        markdown_content = _emergency_truncate(markdown_content, _TPM_SAFE_INPUT_LIMIT)
    prompt = ER_PROMPT_TEMPLATE.format(markdown_content=markdown_content)

    llm = LLMClient()
    try:
        result = await llm.complete(prompt)
        result = result.strip()
        if result.startswith("```mermaid"):
            result = result[10:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]

        compiled_diagram = result.strip()
        logger.info("[generate_er_node] ER 產出完成，圖表長度: %d", len(compiled_diagram))
        return {"er_diagram": compiled_diagram}
    except Exception as e:
        logger.error("[generate_er_node] LLM 生成 ER 圖發生錯誤: %s", e, exc_info=True)
        return {"error": str(e), "er_diagram": "erDiagram\n  Error {\n    string message\n  }"}
