"""Infrastructure 層的 Adapter：Map-Reduce 分批摘要器。

針對超大型專案的 Markdown 報告，採用 Map-Reduce 策略進行摘要：

1. **Map 階段**：將原始 Markdown 切分為 N 個固定大小的 chunk，
   對每個 chunk 獨立呼叫 LLM 提取關鍵技術資訊（局部摘要）。

2. **Reduce 階段**：將所有局部摘要合併後，呼叫一次 LLM 生成精煉的
   整體技術摘要，作為最終 API 文件 / 環境指南節點的輸入。

切割邊界對齊段落邊界（`\\n\\n`），確保不截斷 code block 或函式定義中間。
僅在內容超過 ``MAP_REDUCE_THRESHOLD`` 時才觸發，小型專案完全繞過。
"""

from __future__ import annotations

import logging
from typing import List

from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token 預算常數
# ---------------------------------------------------------------------------

#: Token 估算常數（1 Token ≈ 3.5 字元）。
_CHARS_PER_TOKEN: float = 3.5

#: 每個 Map chunk 的目標 token 大小（30k token ≈ 105,000 字元）。
CHUNK_TOKEN_SIZE: int = 30_000

#: 觸發 Map-Reduce 的最低 token 門檻（60k token）。
MAP_REDUCE_THRESHOLD: int = 60_000


def _estimate_tokens(text: str) -> int:
    """估算文字的 Token 數量。

    Args:
        text: 欲估算的文字。

    Returns:
        估算的 Token 數量。
    """
    return int(len(text) / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Chunk 切割
# ---------------------------------------------------------------------------


def split_into_chunks(content: str, chunk_token_size: int = CHUNK_TOKEN_SIZE) -> List[str]:
    """將長文本依 token 大小切分為多個 chunk，切割邊界對齊段落邊界。

    策略：
    1. 累積字元直到接近 ``chunk_token_size``。
    2. 在最近的 ``\\n\\n`` 段落邊界切割，避免截斷程式碼區塊中間。
    3. 若找不到段落邊界（例如超長的單一程式碼區塊），則在 ``\\n`` 行邊界切割。
    4. 若仍找不到，才在字元邊界強制切割（最後手段）。

    Args:
        content: 要切分的完整 Markdown 字串。
        chunk_token_size: 每個 chunk 的目標 token 大小。

    Returns:
        切分後的 chunk 字串列表，每個元素均為非空字串。
    """
    target_chars = int(chunk_token_size * _CHARS_PER_TOKEN)
    chunks: List[str] = []
    start = 0
    total_len = len(content)

    while start < total_len:
        end = min(start + target_chars, total_len)

        if end >= total_len:
            # 最後一個 chunk，直接取剩餘所有內容
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            break

        # 嘗試在段落邊界（\n\n）切割
        boundary = content.rfind("\n\n", start, end)
        if boundary != -1 and boundary > start + target_chars * 0.5:
            # 找到段落邊界且退讓不超過 50%
            end = boundary + 2  # 包含 \n\n 本身
        else:
            # 嘗試在行邊界（\n）切割
            boundary = content.rfind("\n", start, end)
            if boundary != -1 and boundary > start + target_chars * 0.7:
                end = boundary + 1
            # 否則維持字元邊界強制切割

        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end

    logger.info(
        "[split_into_chunks] 切分完成：原始 %d token → %d 個 chunk（目標每批 %d token）",
        _estimate_tokens(content),
        len(chunks),
        chunk_token_size,
    )
    return chunks


# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

_MAP_PROMPT_TEMPLATE = """\
你正在分析一個大型軟體專案原始碼報告的第 {chunk_index}/{total_chunks} 批次。

# 任務

請從以下內容中提取所有關鍵技術資訊，包含：
- **API 端點**：HTTP Method、路徑、Request Body / Query Params 格式、Response 格式
- **環境變數與設定項目**：變數名稱、用途、預設值
- **服務依賴與外部整合**：資料庫、快取、第三方 API、訊息佇列
- **技術棧與框架**：語言版本、主要框架、套件依賴

# 輸出格式

以 Markdown 條列格式輸出，不要生成完整文件，只要逐條列出找到的事實。
若某類資訊在本批次中不存在，直接省略該類別。

---

# 本批次原始碼內容：

{chunk_content}

---

請直接輸出提取結果，不要包含前言或後記。
"""

_REDUCE_PROMPT_TEMPLATE = """\
以下是同一個軟體專案分 {total_chunks} 批次分析的局部摘要。
部分資訊可能跨批次重複，請整合、去除重複、補全邏輯缺口，
輸出一份完整、一致的專案技術摘要。

# 整合要求

1. 去除重複的 API 端點或環境變數描述。
2. 補全因批次切割而造成的上下文缺口（如同一服務的不同端點分散在多個批次中）。
3. 輸出格式：Markdown，依以下章節組織：
   - **API 端點彙整**
   - **環境變數彙整**
   - **技術棧與依賴彙整**
   - **服務架構與外部整合彙整**

---

{summaries_block}

---

請直接輸出整合後的技術摘要，不要包含前言或後記。
"""


# ---------------------------------------------------------------------------
# MapReduceSummarizer 主類別
# ---------------------------------------------------------------------------


class MapReduceSummarizer:
    """對大型 Markdown 報告執行 Map-Reduce 分批摘要。

    **Map 階段**：將 Markdown 切分為 N 個 chunk，序列化呼叫 LLM 提取局部摘要。
    **Reduce 階段**：合併所有局部摘要，呼叫一次 LLM 生成精煉整體摘要。

    所有 LLM 呼叫均透過 :class:`~LLMClient` 的 Semaphore 序列化，
    確保不超過 RPM 限制。

    Args:
        chunk_token_size: 每個 Map chunk 的目標 token 大小，預設 30,000。

    Example::

        summarizer = MapReduceSummarizer()
        summary = await summarizer.summarize(large_markdown_content)
    """

    def __init__(self, chunk_token_size: int = CHUNK_TOKEN_SIZE) -> None:
        """初始化 MapReduceSummarizer。

        Args:
            chunk_token_size: 每個 chunk 的 token 大小上限。
        """
        self._chunk_token_size = chunk_token_size
        self._llm = LLMClient()

    async def summarize(self, content: str) -> str:
        """對長文本執行完整的 Map-Reduce 摘要流程。

        若內容不超過 ``MAP_REDUCE_THRESHOLD``，直接回傳原始內容（passthrough）。

        Args:
            content: 完整的 Markdown 報告字串。

        Returns:
            精煉後的技術摘要字串。若未觸發 Map-Reduce，則回傳原始內容。
        """
        token_estimate = _estimate_tokens(content)

        if token_estimate <= MAP_REDUCE_THRESHOLD:
            logger.info(
                "[MapReduceSummarizer] Token 估算 %d ≤ 閾值 %d，跳過 Map-Reduce。",
                token_estimate,
                MAP_REDUCE_THRESHOLD,
            )
            return content

        logger.info(
            "[MapReduceSummarizer] Token 估算 %d > 閾值 %d，觸發 Map-Reduce。",
            token_estimate,
            MAP_REDUCE_THRESHOLD,
        )

        # ── Map 階段 ────────────────────────────────────────────────────────
        chunks = split_into_chunks(content, self._chunk_token_size)
        local_summaries = await self._map_chunks(chunks)

        # ── Reduce 階段 ─────────────────────────────────────────────────────
        final_summary = await self._reduce_summaries(local_summaries)

        logger.info(
            "[MapReduceSummarizer] 完成：%d token → %d 個 chunk → 精煉摘要 %d 字元（%d token）",
            token_estimate,
            len(chunks),
            len(final_summary),
            _estimate_tokens(final_summary),
        )
        return final_summary

    async def _map_chunks(self, chunks: List[str]) -> List[str]:
        """Map 階段：對每個 chunk 序列化呼叫 LLM 生成局部摘要。

        受 :data:`~app.infrastructure.adapters.llm_client._call_semaphore`
        序列化保護，不會同時發出多個 LLM 請求。

        Args:
            chunks: 已切分的 chunk 列表。

        Returns:
            與輸入順序對應的局部摘要列表。
        """
        total = len(chunks)
        summaries: List[str] = []

        logger.info("[MapReduceSummarizer] Map 階段開始：共 %d 個 chunk。", total)

        for idx, chunk in enumerate(chunks, start=1):
            prompt = _MAP_PROMPT_TEMPLATE.format(
                chunk_index=idx,
                total_chunks=total,
                chunk_content=chunk,
            )
            logger.info(
                "[MapReduceSummarizer] Map chunk %d/%d（%d token）發送 LLM 請求...",
                idx,
                total,
                _estimate_tokens(chunk),
            )
            summary = await self._llm.complete(prompt)
            summaries.append(summary)
            logger.info(
                "[MapReduceSummarizer] Map chunk %d/%d 完成，局部摘要 %d 字元。",
                idx,
                total,
                len(summary),
            )

        logger.info(
            "[MapReduceSummarizer] Map 階段完成：%d 份局部摘要，合計 %d 字元。",
            len(summaries),
            sum(len(s) for s in summaries),
        )
        return summaries

    async def _reduce_summaries(self, summaries: List[str]) -> str:
        """Reduce 階段：將所有局部摘要合併後呼叫一次 LLM 生成精煉整體摘要。

        Args:
            summaries: Map 階段輸出的局部摘要列表。

        Returns:
            精煉後的整體技術摘要字串。
        """
        total = len(summaries)

        # 組裝每份局部摘要的分隔區塊
        summaries_block = "\n\n".join(
            f"--- 局部摘要 {i + 1}/{total} ---\n{s}"
            for i, s in enumerate(summaries)
        )

        prompt = _REDUCE_PROMPT_TEMPLATE.format(
            total_chunks=total,
            summaries_block=summaries_block,
        )

        combined_tokens = _estimate_tokens(summaries_block)
        logger.info(
            "[MapReduceSummarizer] Reduce 階段：合併摘要 %d token，發送 LLM 請求...",
            combined_tokens,
        )

        result = await self._llm.complete(prompt)

        logger.info(
            "[MapReduceSummarizer] Reduce 完成，精煉摘要 %d 字元（%d token）。",
            len(result),
            _estimate_tokens(result),
        )
        return result
