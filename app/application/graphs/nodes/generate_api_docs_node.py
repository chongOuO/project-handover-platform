"""LangGraph 節點 2：AI 生成 API 使用文件（分批生成版）。

將整個生成流程拆分為三階段，解决單次 LLM 呼叫輸出 Token 上限（~8k tokens）導致文件被截斷的問題：

**階段 1 — 提取端點清單**
    呼叫 LLM 擃戗所有 HTTP 端點，輸出為紧湊格式的純文字清單（輸出 < 1k tokens）。

**階段 2 — 生成概述與端點表格**
    利用階段 1 的清單生成 ‘專案概述 + Base URL + 認證機制 + API 端點列表’（輸出 < 3k tokens）。

**階段 3 — 分批展開端點詳細說明**
    每次 ``BATCH_SIZE`` (預設 4) 個端點發起一次 LLM 呼叫，
    將輸出量控制在 ~3k tokens 以內，最後將所有片段拼接。

**容錯設計**：若端點提取失敗（輸出無法解析），
降級為強制單次呼叫模式（保留旧行為）。
"""

from __future__ import annotations

import logging
import re
from math import ceil
from typing import Generator, List, Tuple

from app.application.graphs.state import GraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

_llm = LLMClient()

#: TPM 安全上限（每個團隊輸入上限）。
_TPM_SAFE_INPUT_LIMIT: int = 100_000

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

#: 每批處理的端點數量（控制單次輸出不超過 LLM 輸出 Token 上限）。
BATCH_SIZE: int = 4

# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

_EXTRACT_ENDPOINTS_PROMPT = """\
分析以下專案原始碼報告，列出它所有的 HTTP API 端點。

輸出規則：
1. 每行一個端點，格式必須為：`METHOD /path`
2. 禁止添加任何說明、標題、空行或其他內容，只輸出端點清單。
3. 若將 GET/POST/PUT/DELETE 共用同一路徑，分行列出。
4. 若找不到明確定義，根據功能推斷並在路徑後標注 (推斷)。

輸出範例：
GET /api/users
POST /api/users
GET /api/users/{{user_id}}
DELETE /api/users/{{user_id}}

---

{markdown_content}
"""

_HEADER_PROMPT = """\
根據以下專案原始碼報告與端點清單，生成 API 文件的開頭處章節。

## 輸出要求

只生成以下四個章節，禁止生成端點詳細說明：

```
# API 使用文件

## 專案概述
(簡介此專案的核心功能與定位，2-3 句)

## Base URL
(推斷或列出 API 的基礎路徑)

## 認證機制
(說明是否需要 Token / API Key)

## API 端點列表
(以表格呈現所有端點，栏位：Method | Path | 說明，說明保持簡短)
```

端點清單（必須全部呈現於表格內）：
{endpoint_list}

---

專案原始碼報告：
{markdown_content}
"""

_DETAIL_BATCH_PROMPT = """\
根據以下專案原始碼報告，為指定的 API 端點撰寫詳細文件。

## 本次要處理的端點（共 {batch_count} 個）：

{endpoints_batch}

## 輸出要求

1. **直接從第一個端點的 `###` 標題開始輸出，禁止添加任何前言、說明性文字或章節介紹。**
2. 只撰寫上方列出的端點詳細說明，不要加入其他端點。
3. 每個端點必須包含：
   - `### {section_offset}. 端點名稱` 標題（N 為階段 3 內的編號，初始値 = {section_offset}）
   - **請求格式**（Request Body / Params，含必填/選填說明）
   - **回應格式**（Response Body，含每個欄位的類型說明）
   - **錯誤代碼對照表**（status_code | error_code | 說明）
   - **完整的 `curl` 範例**
4. 若該端點在原始碼中找不到定義，根據功能推斷並標注「（推斷）」。
5. 禁止說「格式相同不再重複」等省略語句。
6. 使用繁體中文撰寫。

---

專案原始碼報告：
{markdown_content}
"""

_FALLBACK_PROMPT = """\
你是一位精通技術文件撰寫的資深工程師，請根據以下專案原始碼報告，生成一份完整、專業的 **API 使用文件**。

# 生成流程（必須嚴格依序執行）

**第一步（枚舉）**：將找到的「每一個」 HTTP 端點以無序列表輸出。
**第二步（展開）**：依照第一步清單逐一展開，禁止跳過任何端點。
**禁止**以「其餘端點格式相同，不再重複」等語句省略任何端點。

# 輸出格式

   - **專案概述**：簡介此專案的核心功能與定位（2-3句）。
   - **Base URL**：推斷或列出 API 的基礎路徑。
   - **認證機制**：說明是否需要 Token / API Key，若無則明確標注「無需認證」。
   - **API 端點列表**：以表格呈現所有端點（Method | Path | 說明）。
   - **端點詳細說明**：依第二步結果逐一展開。
4. 若原始碼中找不到 API 定義，請根據推斷的功能生成範例章節，並標注「（推斷）」。

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


def _prepare_content(state: GraphState) -> str:
    """根據管線狀態決定送入 LLM 的內容字串。

    優先使用 Map-Reduce 精煉摘要（若已觸發），否則讀取原始
    markdown_content 並在超限時執行緊急截斷。

    Args:
        state: 當前圖狀態。

    Returns:
        準備好送入 Prompt 的內容字串。
    """
    if state.get("use_map_reduce"):
        content = state["map_reduce_summary"]
        logger.info(
            "[generate_api_docs_node] 使用 Map-Reduce 精煉摘要（%d 字元）。",
            len(content),
        )
        return content

    content = state["markdown_content"]
    token_estimate = state.get("content_token_estimate", _estimate_tokens(content))

    if token_estimate > _TPM_SAFE_INPUT_LIMIT:
        logger.warning(
            "[generate_api_docs_node] Token 估算 %d 超過安全上限 %d，執行緊急截斷。",
            token_estimate,
            _TPM_SAFE_INPUT_LIMIT,
        )
        target_chars = int(_TPM_SAFE_INPUT_LIMIT * _CHARS_PER_TOKEN)
        content = content[:target_chars]
        content += "\n\n<!-- [Emergency Truncation] 內容已被緊急截斷以符合 TPM 限制 -->"

    return content


def _parse_endpoints(raw: str) -> List[Tuple[str, str]]:
    """解析 LLM 回傳的端點清單文字，提取 (method, path) 元組列表。

    支援格式：每行一個端點，格式為 ``METHOD /path``（允許行首空白）。

    Args:
        raw: LLM 回傳的純文字端點清單。

    Returns:
        解析出的 (method, path) 元組列表。若無有效端點則回傳空列表。
    """
    endpoints: List[Tuple[str, str]] = []
    pattern = re.compile(
        r"^\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT|TRACE)\s+(\S+)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in pattern.finditer(raw):
        method = match.group(1).upper()
        path = match.group(2).rstrip(",.")
        endpoints.append((method, path))
    return endpoints


def _chunk(items: list, size: int) -> Generator[list, None, None]:
    """將列表切分成固定大小的批次。

    Args:
        items: 要切分的完整列表。
        size: 每批的最大元素數量。

    Yields:
        每次 yield 一個子列表，最後一批可能不滿 size。
    """
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _sanitize_output(text: str) -> str:
    """清理 LLM 輸出文字，消除造成「空白區域」的常見問題。

    問題來源：LLM 有時為了對齊 Markdown 表格，在 cell 內填入大量空格；
    或在段落間插入過多空行，都會在渲染後造成視覺上的大塊空白。

    Args:
        text: LLM 回傳的原始 Markdown 文字。

    Returns:
        清理後的 Markdown 文字。
    """
    # 1. 壓縮表格 cell 內的連續空白，以及任何超長行
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # 表格行（以 | 開頭）或超長行（LLM 填充空格造成），均壓縮連續空格
        if stripped.startswith("|") or len(line) > 2000:
            line = re.sub(r" {2,}", " ", line)
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 2. 壓縮超過 2 個連續空行 → 最多 2 個
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


async def generate_api_docs_node(state: GraphState) -> GraphState:
    """三階段分批生成 API 使用文件。

    **階段 1 — 提取端點清單**（1 次 LLM 呼叫）：
        掃描內容，以簡潔格式列出所有 HTTP 端點，輸出 < 1k tokens。

    **階段 2 — 生成概述與端點表格**（1 次 LLM 呼叫）：
        利用階段 1 清單生成文件 Header 部分，輸出 < 3k tokens。

    **階段 3 — 分批展開詳細說明**（ceil(N/BATCH_SIZE) 次 LLM 呼叫）：
        每 BATCH_SIZE 個端點發起一次 LLM 呼叫，每次輸出 < 4k tokens，
        最後拼接所有片段形成完整文件。

    **容錯降級**：若階段 1 端點解析失敗，降級為單次呼叫的 Fallback Prompt。

    Args:
        state: 需包含 ``markdown_content`` 或 ``map_reduce_summary``。

    Returns:
        更新後的 :class:`~app.application.graphs.state.GraphState`，
        新增了 ``api_docs_content`` 欄位。
    """
    logger.info("[generate_api_docs_node] 開始分批生成 API 使用文件...")

    content = _prepare_content(state)

    # ── 階段 1：提取端點清單 ───────────────────────────────────────────────
    logger.info("[generate_api_docs_node] 階段 1：提取端點清單...")
    extract_prompt = _EXTRACT_ENDPOINTS_PROMPT.format(markdown_content=content)
    endpoint_list_raw = await _llm.complete(extract_prompt)
    endpoints = _parse_endpoints(endpoint_list_raw)

    if not endpoints:
        # 容錯降級：解析失敗，回退到單次呼叫模式
        logger.warning(
            "[generate_api_docs_node] 端點提取失敗（解析到 0 個端點），降級為單次呼叫 Fallback 模式。"
        )
        fallback_prompt = _FALLBACK_PROMPT.format(markdown_content=content)
        api_docs = await _llm.complete(fallback_prompt)
        logger.info(
            "[generate_api_docs_node] Fallback 完成，輸出長度：%d 字元", len(api_docs)
        )
        return {"api_docs_content": api_docs}

    logger.info(
        "[generate_api_docs_node] 階段 1 完成，提取到 %d 個端點。", len(endpoints)
    )

    # ── 階段 2：生成概述 + 認證 + 端點表格 ──────────────────────────────────
    logger.info("[generate_api_docs_node] 階段 2：生成概述與端點表格...")
    endpoint_list_str = "\n".join(f"- {m} {p}" for m, p in endpoints)
    header_prompt = _HEADER_PROMPT.format(
        endpoint_list=endpoint_list_str,
        markdown_content=content,
    )
    header_md = await _llm.complete(header_prompt)
    logger.info(
        "[generate_api_docs_node] 階段 2 完成，Header 長度：%d 字元。", len(header_md)
    )

    # ── 階段 3：分批展開端點詳細說明 ─────────────────────────────────────────
    total_batches = ceil(len(endpoints) / BATCH_SIZE)
    logger.info(
        "[generate_api_docs_node] 階段 3：分批展開 %d 個端點，共 %d 批...",
        len(endpoints),
        total_batches,
    )

    detail_sections: List[str] = []
    section_offset = 1

    for batch_idx, batch in enumerate(_chunk(endpoints, BATCH_SIZE), start=1):
        batch_lines = "\n".join(f"{i}. {m} {p}" for i, (m, p) in enumerate(batch, start=section_offset))
        detail_prompt = _DETAIL_BATCH_PROMPT.format(
            batch_count=len(batch),
            endpoints_batch=batch_lines,
            section_offset=section_offset,
            markdown_content=content,
        )
        logger.info(
            "[generate_api_docs_node] 階段 3 批次 %d/%d（端點 %d~%d）...",
            batch_idx,
            total_batches,
            section_offset,
            section_offset + len(batch) - 1,
        )
        section_md = await _llm.complete(detail_prompt)
        detail_sections.append(_sanitize_output(section_md))
        section_offset += len(batch)

    # ── 組裝完整文件 ──────────────────────────────────────────────────────
    api_docs = _sanitize_output(header_md) + "\n\n## 端點詳細說明\n\n" + "\n\n".join(detail_sections)

    logger.info(
        "[generate_api_docs_node] 完成。端點數：%d | 批次數：%d | 總輸出：%d 字元",
        len(endpoints),
        total_batches,
        len(api_docs),
    )
    return {"api_docs_content": api_docs}
