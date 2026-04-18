"""LangGraph 節點 3：AI 生成環境建置指南。

讀取 ``markdown_content``（或 Map-Reduce 精煉摘要）並構建專注於開發環境架設的 Prompt，
呼叫 :class:`~app.infrastructure.adapters.llm_client.LLMClient`
生成一份開發者可直接跟著操作的環境建置指南 Markdown 文件。

**Map-Reduce 模式**：若上游 ``map_reduce_node`` 已觸發 Map-Reduce，
改用 ``map_reduce_summary``（已包含全部內容的精煉摘要）作為 Prompt 輸入，
確保 LLM 能看到全局將而非被截斷的內容。

**Token Budget Gate**：小型專案（未觸發 Map-Reduce）仍檢查 ``content_token_estimate``，
超限時執行緊急截斷，確保不觸發 TPM 限制。
"""


from __future__ import annotations

import logging

from app.application.graphs.state import GraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

#: TPM 安全上限（保障單一請求輸入上限，以容納兩次序列呼叫於 250k TPM 中）。
_TPM_SAFE_INPUT_LIMIT: int = 100_000

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

#: 環境指南生成的系統 Prompt 模板。
_ENV_GUIDE_PROMPT_TEMPLATE = """\
你是一位精通 DevOps 與後端環境架設的資深工程師，請根據以下專案原始碼報告，
生成一份完整、可直接操作的 **環境建置指南**。

# 撰寫要求

1. 使用 Markdown 格式（繁體中文撰寫）。
2. 文件頂部需包含 `# 環境建置指南` 一級標題。
3. 依以下章節架構撰寫：
   - **系統需求**：列出所需作業系統、執行階段（如 Python 版本、Node.js 版本）、資料庫版本等。
   - **安裝步驟**：以編號清單 + Shell 指令區塊的方式，呈現從零開始的安裝步驟（請包含 venv 或 conda 等虛擬環境建置）。
   - **環境變數設定**：列出所有必要及選填的環境變數，並說明其用途，範例以 `.env` 格式呈現。
   - **依賴安裝**：列出安裝套件的完整指令（如 `pip install -r requirements.txt`）。
   - **啟動服務**：提供啟動開發伺服器的完整指令。
   - **驗證服務正常運作**：提供一個簡易的驗證方法（如 `curl` 或瀏覽器訪問）。
   - **常見問題排除 (Troubleshooting)**：至少列出 3 個常見問題與解法。
4. 所有 Shell 指令必須放在 ```bash 程式碼區塊內。
5. 若原始碼未提供完整資訊，請基於技術推斷補全，並標注「（推斷）」。

---

# 以下是待分析的專案原始碼報告：

{markdown_content}

---

請直接輸出完整的 Markdown 文件，不要包含任何前言或後記說明。
"""


def _estimate_tokens(text: str) -> int:
    """估算文字的 Token 數量。

    Args:
        text: 欲估算的文字。

    Returns:
        估算的 Token 數量。
    """
    return int(len(text) / _CHARS_PER_TOKEN)


def _emergency_truncate(content: str, token_limit: int) -> str:
    """緊急截斷內容至指定 Token 上限。

    Args:
        content: 原始 Markdown 內容。
        token_limit: 目標 Token 上限。

    Returns:
        截斷後的內容。
    """
    target_chars = int(token_limit * _CHARS_PER_TOKEN)
    truncated = content[:target_chars]
    truncated += "\n\n<!-- [Emergency Truncation] 內容已被緊急截斷以符合 TPM 限制 -->"
    return truncated


async def generate_env_guide_node(state: GraphState) -> GraphState:
    """呼叫 LLM 分析原始碼並生成環境建置指南。

    **邏輯重點**：若上游 ``map_reduce_node`` 已觸發 Map-Reduce，
    改用 ``map_reduce_summary``（精煉摘要）作為 Prompt 輸入；
    否則使用原始 ``markdown_content`` 並保留緊急截斷作為最後防線。

    Args:
        state: 需包含 ``markdown_content`` 或 ``map_reduce_summary``。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        新增了 ``env_guide_content`` 欄位。
    """
    logger.info("[generate_env_guide_node] 開始生成環境建置指南...")

    use_map_reduce: bool = state.get("use_map_reduce", False)

    if use_map_reduce:
        # Map-Reduce 模式：使用精煉摘要，無需截斷
        content = state["map_reduce_summary"]
        logger.info(
            "[generate_env_guide_node] 使用 Map-Reduce 精煉摘要（%d 字元）作為輸入。",
            len(content),
        )
    else:
        # 標準模式：使用原始 Markdown，保留緊急截斷作為最後防線
        content = state["markdown_content"]
        token_estimate = state.get("content_token_estimate", _estimate_tokens(content))

        if token_estimate > _TPM_SAFE_INPUT_LIMIT:
            logger.warning(
                "[generate_env_guide_node] Token 估算 %d 超過安全上限 %d，執行緊急截斷。",
                token_estimate,
                _TPM_SAFE_INPUT_LIMIT,
            )
            content = _emergency_truncate(content, _TPM_SAFE_INPUT_LIMIT)
            logger.info(
                "[generate_env_guide_node] 緊急截斷後 Token 估算：%d",
                _estimate_tokens(content),
            )

    prompt = _ENV_GUIDE_PROMPT_TEMPLATE.format(markdown_content=content)
    env_guide = await _llm.complete(prompt)

    logger.info("[generate_env_guide_node] 完成，輸出長度：%d 字元", len(env_guide))
    return {"env_guide_content": env_guide}
