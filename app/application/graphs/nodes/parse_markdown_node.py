"""LangGraph 節點 1：解析 Markdown 來源文件。

從圖的初始 State 中取得 ``source_md_path``，
透過 :class:`~app.infrastructure.repositories.markdown_source_repository.MarkdownSourceRepository`
非同步讀取檔案全文，並將結果存入 ``markdown_content`` 欄位後傳遞至下一節點。

同時估算 ``markdown_content`` 的 Token 數量，寫入 ``content_token_estimate``，
作為後續節點進行 Token Budget Gate 檢查的依據。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.application.graphs.state import GraphState
from app.infrastructure.repositories.markdown_source_repository import MarkdownSourceRepository

logger = logging.getLogger(__name__)

_repo = MarkdownSourceRepository()

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

#: 安全閾值：超過此值時記錄 warning（GLOBAL_TOKEN_BUDGET 的 120%）。
_SAFETY_THRESHOLD: int = 108_000


def _estimate_tokens(text: str) -> int:
    """估算文字的 Token 數量。

    Args:
        text: 欲估算的文字。

    Returns:
        估算的 Token 數量。
    """
    return int(len(text) / _CHARS_PER_TOKEN)


async def parse_markdown_node(state: GraphState) -> GraphState:
    """讀取並解析 Markdown 來源報告，存入圖狀態。

    **邏輯重點**：支援兩種模式：
    - **檔案模式**（獨立使用）：從 ``source_md_path`` 讀取磁碟上的 .md 檔案。
    - **直傳模式**（整合管線）：若呼叫端已在 state 填入 ``markdown_content``，
      則跳過 I/O 讀取直接 passthrough，避免不必要的磁碟操作。

    兩種模式結束後都會估算 Token 數量並寫入 ``content_token_estimate``。

    Args:
        state: 目前的圖狀態，需包含 ``source_md_path``
            或已填入的 ``markdown_content``。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        確保 ``markdown_content``、``content_token_estimate`` 欄位已有有效內容。
    """
    content: str

    # 整合管線直傳模式：content 已由外部填入，直接 passthrough
    if state.get("markdown_content"):
        content = state["markdown_content"]
        logger.info(
            "[parse_markdown_node] 偵測到直傳內容（%d 字元），跳過磁碟讀取。",
            len(content),
        )
    else:
        # 獨立模式：從磁碟路徑讀取
        path = Path(state["source_md_path"])
        logger.info("[parse_markdown_node] 讀取來源文件：%s", path)
        content = await _repo.read(path)
        logger.info("[parse_markdown_node] 讀取完成，共 %d 字元", len(content))

    # Token 估算與安全檢查
    token_estimate = _estimate_tokens(content)
    compression_applied = state.get("compression_applied", False)

    if token_estimate > _SAFETY_THRESHOLD:
        logger.warning(
            "[parse_markdown_node] Token 估算 %d 超過安全閾值 %d，"
            "後續 LLM 節點可能觸發緊急截斷。",
            token_estimate,
            _SAFETY_THRESHOLD,
        )

    logger.info(
        "[parse_markdown_node] Token 估算：%d | 壓縮已套用：%s",
        token_estimate,
        compression_applied,
    )

    return {
        "markdown_content": content,
        "content_token_estimate": token_estimate,
        "compression_applied": compression_applied,
    }
