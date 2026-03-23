"""LangGraph 節點 1：解析 Markdown 來源文件。

從圖的初始 State 中取得 ``source_md_path``，
透過 :class:`~app.infrastructure.repositories.markdown_source_repository.MarkdownSourceRepository`
非同步讀取檔案全文，並將結果存入 ``markdown_content`` 欄位後傳遞至下一節點。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.application.graphs.state import GraphState
from app.infrastructure.repositories.markdown_source_repository import MarkdownSourceRepository

logger = logging.getLogger(__name__)

_repo = MarkdownSourceRepository()


async def parse_markdown_node(state: GraphState) -> GraphState:
    """讀取並解析 Markdown 來源報告，存入圖狀態。

    **邏輯重點**：支援兩種模式：
    - **檔案模式**（獨立使用）：從 ``source_md_path`` 讀取磁碟上的 .md 檔案。
    - **直傳模式**（整合管線）：若呼叫端已在 state 填入 ``markdown_content``，
      則跳過 I/O 讀取直接 passthrough，避免不必要的磁碟操作。

    Args:
        state: 目前的圖狀態，需包含 ``source_md_path``
            或已填入的 ``markdown_content``。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        確保 ``markdown_content`` 欄位已有有效內容。
    """
    # 整合管線直傳模式：content 已由外部填入，直接 passthrough
    if state.get("markdown_content"):
        logger.info(
            "[parse_markdown_node] 偵測到直傳內容（%d 字元），跳過磁碟讀取。",
            len(state["markdown_content"]),
        )
        return state

    # 獨立模式：從磁碟路徑讀取
    path = Path(state["source_md_path"])
    logger.info("[parse_markdown_node] 讀取來源文件：%s", path)

    content = await _repo.read(path)
    logger.info("[parse_markdown_node] 讀取完成，共 %d 字元", len(content))

    return {"markdown_content": content}
