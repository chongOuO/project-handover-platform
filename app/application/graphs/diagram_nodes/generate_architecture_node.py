"""系統架構圖生成節點 (Generate Architecture Node)。

根據專案的 Markdown 原始分析檔，委派給 LLM 生成 Mermaid.js 的 `graph TD` 語法，
描繪高階層級的組件與資料流關係。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.diagram_state import DiagramGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: TPM 安全上限（保障單一請求輸入上限）。
_TPM_SAFE_INPUT_LIMIT: int = 90_000

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

ARCHITECTURE_PROMPT_TEMPLATE = """
請你根據以下軟體專案的程式碼綱要報告，產出一份系統架構圖 (System Architecture Diagram)。
請使用 Mermaid.js 的 `graph TD` 或 `graph LR` 語法來描繪模組、組件或微服務之間的依賴與呼叫關係。

要求與規範：
1. 僅輸出純包含 Mermaid 語法的字串即可，**絕對不要**使用 Markdown code fence (例如 ```mermaid ... ```)。
2. 若節點名稱包含特殊字元，請務必用不含特殊符號的 ID，並利用 `[]`、`()` 加註文字，字串如果含有角括弧或引號請適當跳脫轉譯。
3. 根據專案結構，展現分層（如 Router -> Service -> Repository）或是微服務。
4. 提供足夠清晰的圖形能直觀表達此專案的組成。

=== 專案結構與文件內容 ===
{markdown_content}

=== 請在下方直接輸出純 Mermaid 語法 ===
"""


def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


def _emergency_truncate(content: str, token_limit: int) -> str:
    target_chars = int(token_limit * _CHARS_PER_TOKEN)
    return content[:target_chars] + "\n\n<!-- [Emergency Truncation] 內容已被緊急截斷以符合 TPM 限制 -->"


async def generate_architecture_node(state: DiagramGraphState, config: Any) -> dict[str, Any]:
    """執行架構圖生成的 LangGraph 節點。

    將結果回寫至 ``architecture_diagram``。

    Args:
        state: Diagram Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含更新的分部字典。
    """
    logger.info("[generate_architecture_node] 開始呼叫 LLM 產出 系統架構圖 (Mermaid)...")

    markdown_content = state.get("markdown_content", "")
    if not markdown_content:
        logger.warning("[generate_architecture_node] 收到空的 markdown_content，回傳預設結構。")
        return {"architecture_diagram": "graph TD\n  Empty[No Data Available]"}

    token_estimate = state.get("content_token_estimate", _estimate_tokens(markdown_content))
    if token_estimate > _TPM_SAFE_INPUT_LIMIT:
        logger.warning(
            "[generate_architecture_node] Token 估算 %d 超過安全上限 %d，執行緊急截斷。",
            token_estimate, _TPM_SAFE_INPUT_LIMIT,
        )
        markdown_content = _emergency_truncate(markdown_content, _TPM_SAFE_INPUT_LIMIT)

    prompt = ARCHITECTURE_PROMPT_TEMPLATE.format(markdown_content=markdown_content)
    
    llm = LLMClient()
    try:
        result = await llm.complete(prompt)
        # 清理可能被誤加的 code fence
        result = result.strip()
        if result.startswith("```mermaid"):
            result = result[10:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        
        compiled_diagram = result.strip()
        logger.info("[generate_architecture_node] 產出完成，圖表長度: %d", len(compiled_diagram))
        return {"architecture_diagram": compiled_diagram}
    except Exception as e:
        logger.error("[generate_architecture_node] LLM 生成架構圖發生錯誤: %s", e, exc_info=True)
        return {"error": str(e), "architecture_diagram": "graph TD\n  Error[Generation Error]"}
