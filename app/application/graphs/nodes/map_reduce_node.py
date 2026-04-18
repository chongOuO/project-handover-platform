"""LangGraph 節點：Map-Reduce 分批摘要前處理。

位於 ``parse_markdown_node`` 之後、兩個 AI 生成節點之前。
對超大型專案的 Markdown 報告執行 Map-Reduce 分批摘要，
將精煉後的技術摘要存入 State，供下游節點直接使用，
取代原始（可能因截斷而不完整的）Markdown 內容。

若內容不超過 ``MAP_REDUCE_THRESHOLD``，此節點為 no-op（passthrough），
對小型專案完全無延遲影響。
"""

from __future__ import annotations

import logging

from app.application.graphs.state import GraphState
from app.infrastructure.adapters.map_reduce_summarizer import (
    MAP_REDUCE_THRESHOLD,
    MapReduceSummarizer,
    _estimate_tokens,
)

logger = logging.getLogger(__name__)

_summarizer = MapReduceSummarizer()


async def map_reduce_node(state: GraphState) -> GraphState:
    """對大型 Markdown 報告執行 Map-Reduce 分批摘要。

    **邏輯重點**：
    - 若 ``content_token_estimate`` ≤ ``MAP_REDUCE_THRESHOLD``（60,000 token），
      直接設定 ``use_map_reduce = False`` 並跳過，下游節點仍使用 ``markdown_content``。
    - 超過閾值時，呼叫 :class:`~MapReduceSummarizer` 執行 Map + Reduce，
      將精煉摘要寫入 ``map_reduce_summary``，並設定 ``use_map_reduce = True``。

    **容錯設計**：若 Map-Reduce 過程中發生任何例外，
    記錄警告並設定 ``use_map_reduce = False``，管線將降級為原有的截斷策略，
    確保不因 Map-Reduce 失敗而導致整個請求失敗。

    Args:
        state: 需包含 ``markdown_content`` 與 ``content_token_estimate``。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        包含 ``map_reduce_summary`` 與 ``use_map_reduce`` 欄位。
    """
    markdown_content = state["markdown_content"]
    token_estimate = state.get("content_token_estimate", _estimate_tokens(markdown_content))

    logger.info(
        "[map_reduce_node] 內容 Token 估算：%d（閾值：%d）",
        token_estimate,
        MAP_REDUCE_THRESHOLD,
    )

    # 未超過閾值，跳過 Map-Reduce
    if token_estimate <= MAP_REDUCE_THRESHOLD:
        logger.info("[map_reduce_node] 跳過 Map-Reduce，直接使用原始 Markdown。")
        return {
            "use_map_reduce": False,
            "map_reduce_summary": None,
        }

    # 超過閾值，執行 Map-Reduce（帶容錯）
    logger.info("[map_reduce_node] 觸發 Map-Reduce 分批摘要...")
    try:
        summary = await _summarizer.summarize(markdown_content)
        logger.info(
            "[map_reduce_node] Map-Reduce 完成，精煉摘要 %d 字元（%d token）。",
            len(summary),
            _estimate_tokens(summary),
        )
        return {
            "use_map_reduce": True,
            "map_reduce_summary": summary,
        }
    except Exception as exc:
        logger.warning(
            "[map_reduce_node] Map-Reduce 執行失敗，降級為原有截斷策略：%s",
            exc,
            exc_info=True,
        )
        return {
            "use_map_reduce": False,
            "map_reduce_summary": None,
        }
