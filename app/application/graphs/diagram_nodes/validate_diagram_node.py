"""語法驗證與修正節點 (Validate Diagram Node)。

將已生成的 Mermaid 圖表交由 LLM 作二次確認，修正常見的排版語法錯誤，
如標點不對稱、特殊字元與未跳脫的非法字元等，確保前端正確渲染。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.diagram_state import DiagramGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

VALIDATE_PROMPT_TEMPLATE = """
你是一個 Mermaid 語法專家。
這裏有一段或多段 Mermaid 語法（可能是 graph TD 架構圖，或 erDiagram 資料庫 ER 圖）。
請你檢查語法是否正確，並修正任何可能導致渲染失敗的錯誤。

常見錯誤：
1. 括號、角括號沒配對。
2. `<` 或 `>` 在節點文字內沒跳脫 (例如需轉換為 `&lt;` 與 `&gt;`，或利用引號包裝字串 `["Text<T>"]`)。
3. 節點名稱帶有特殊符號卻沒有使用引號包裝。
4. 關係連接線上未依語法規範。

請直接且唯一輸出**修正過後的對應純 Mermaid 語法字串**(不要附帶任何說明與 markdown 標籤，例如 ```mermaid)。
如果原始語法已經完全合法，則直接輸出原字串。

=== 待驗證圖表： ===
{diagram_content}
"""


async def validate_diagram_node(state: DiagramGraphState, config: Any) -> dict[str, Any]:
    """執行 Mermaid 語法修復與驗證的 LangGraph 節點。

    如果修正成功，覆寫原本的 architecture_diagram 與 er_diagram。

    Args:
        state: Diagram Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含更新的分部字典。
    """
    logger.info("[validate_diagram_node] 開始作 Mermaid 語法驗證修正...")
    llm = LLMClient()
    updates = {}

    # 驗證 架構圖
    arch_diagram = state.get("architecture_diagram")
    if arch_diagram and not arch_diagram.startswith("graph TD\n  Empty[No"):
        prompt = VALIDATE_PROMPT_TEMPLATE.format(diagram_content=arch_diagram)
        try:
            res = await llm.complete(prompt)
            res = _clean_code_fence(res)
            updates["architecture_diagram"] = res
            logger.info("[validate_diagram_node] 架構圖修正完畢。")
        except Exception as e:
            logger.warning("[validate_diagram_node] 架構圖修正失敗，退回原版: %s", e)

    # 驗證 ER 圖
    er_diagram = state.get("er_diagram")
    if er_diagram and not er_diagram.startswith("erDiagram\n  Error {"):
        prompt = VALIDATE_PROMPT_TEMPLATE.format(diagram_content=er_diagram)
        try:
            res = await llm.complete(prompt)
            res = _clean_code_fence(res)
            updates["er_diagram"] = res
            logger.info("[validate_diagram_node] ER圖修正完畢。")
        except Exception as e:
            logger.warning("[validate_diagram_node] ER圖修正失敗，退回原版: %s", e)

    return updates


def _clean_code_fence(text: str) -> str:
    """清理由 LLM 不小心包裝的 markdown fence。"""
    text = text.strip()
    if text.startswith("```mermaid"):
        text = text[10:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
