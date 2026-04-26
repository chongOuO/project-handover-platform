"""Q&A LangGraph 節點：上下文檢索。

此節點是 QA 管線的第二個節點，負責：
1. 依據 ``classify_question_node`` 的分類結果與關鍵字，
   從 Session 快取的 ``project_files`` 中篩選最相關的檔案。
2. 若 Session 存有 ``map_reduce_summary``（大型專案），
   優先將摘要納入上下文（確保全局資訊完整），再疊加相關檔案片段。
3. 組裝上下文字串，確保 Token 量在 ``CONTEXT_TOKEN_BUDGET`` 以內。

設計決策：
    純記憶體計算（關鍵字命中 + 加權排序），無 I/O，
    整個節點耗時通常在毫秒級。
"""

from __future__ import annotations

import json
import logging
from typing import List, Tuple

from app.application.graphs.qa_state import QAGraphState
from app.domain.entities.project import ProjectFile
from app.domain.entities.qa_models import QuestionType

logger = logging.getLogger(__name__)

#: 送入 generate_answer_node 的上下文 Token 上限。
#: Gemini 2.5 Flash 支援 1M Token，此預算保留足夠的空間給 Prompt + Answer。
CONTEXT_TOKEN_BUDGET: int = 60_000

#: Token 估算常數（與 map_reduce_summarizer 保持一致）。
_CHARS_PER_TOKEN: float = 3.5


def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# 類型加權表
# ---------------------------------------------------------------------------

#: 各 QuestionType 對應的目錄/路徑關鍵字加權乘數。
#: 若路徑包含以下關鍵字，會依 question_type 獲得額外分數提升。
_TYPE_PATH_BOOSTS: dict[QuestionType, list[str]] = {
    QuestionType.ARCHITECTURE: ["main", "config", "app", "core", "server", "startup"],
    QuestionType.API_USAGE: ["router", "route", "api", "endpoint", "handler", "controller", "view"],
    QuestionType.IMPLEMENTATION: ["service", "logic", "domain", "use_case", "business"],
    QuestionType.CONFIG: ["config", "setting", "env", ".env", "yaml", "yml", "toml"],
    QuestionType.GENERAL: [],
}


def _score_file(
    pf: ProjectFile,
    keywords: List[str],
    question_type: QuestionType,
) -> float:
    """計算單一 ProjectFile 對當前問題的相關性分數。

    **評分維度**：
    1. 路徑關鍵字命中：每命中 +3.0。
    2. 內容關鍵字命中：每命中（最多 5 次）+1.0。
    3. 類型路徑加權：路徑含類型相關詞彙時 *1.8 乘數。

    Args:
        pf: 要評分的程式碼檔案。
        keywords: 由 ``classify_question_node`` 提取的關鍵字列表。
        question_type: 問題類型，影響路徑乘數。

    Returns:
        浮點數相關性分數，0.0 代表完全不相關。
    """
    path_lower = pf.relative_path.lower()
    content_lower = pf.content.lower()
    score = 0.0

    # 關鍵字命中計分
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in path_lower:
            score += 3.0
        content_hits = min(content_lower.count(kw_lower), 5)
        score += float(content_hits)

    if score == 0.0:
        return 0.0

    # 類型路徑加權
    boost_terms = _TYPE_PATH_BOOSTS.get(question_type, [])
    for term in boost_terms:
        if term in path_lower:
            score *= 1.8
            break  # 只乘一次

    return score


def _build_context_string(
    selected: List[Tuple[ProjectFile, float]],
    map_reduce_summary: str | None,
    token_budget: int,
) -> Tuple[str, List[str], int, bool]:
    """將選中的檔案與摘要組裝為上下文字串。

    Args:
        selected: (ProjectFile, score) 的排序列表（分數高到低）。
        map_reduce_summary: Map-Reduce 精煉摘要（可為 None）。
        token_budget: 最大允許 Token 數。

    Returns:
        Tuple (context_str, referenced_files, total_tokens, used_summary)
    """
    parts: List[str] = []
    referenced: List[str] = []
    used_tokens = 0
    used_summary = False

    # 優先納入 Map-Reduce 摘要（若存在）
    if map_reduce_summary:
        summary_part = (
            "## 專案技術摘要（Map-Reduce 精煉）\n\n"
            + map_reduce_summary
        )
        summary_tokens = _estimate_tokens(summary_part)
        if used_tokens + summary_tokens <= token_budget:
            parts.append(summary_part)
            used_tokens += summary_tokens
            used_summary = True
            logger.info(
                "[retrieve_context_node] 納入 Map-Reduce 摘要：%d token。",
                summary_tokens,
            )

    # 依分數高到低納入相關檔案
    for pf, score in selected:
        file_part = (
            f"## 檔案：{pf.relative_path}（相關性：{score:.1f}）\n"
            f"```{pf.language}\n{pf.content}\n```"
        )
        file_tokens = _estimate_tokens(file_part)
        if used_tokens + file_tokens > token_budget:
            logger.info(
                "[retrieve_context_node] Token 預算不足，跳過 %s（需 %d token，剩餘 %d）。",
                pf.relative_path,
                file_tokens,
                token_budget - used_tokens,
            )
            break
        parts.append(file_part)
        referenced.append(pf.relative_path)
        used_tokens += file_tokens

    context_str = "\n\n---\n\n".join(parts)
    return context_str, referenced, used_tokens, used_summary


async def retrieve_context_node(state: QAGraphState) -> QAGraphState:
    """從 Session 快取中篩選最相關的程式碼片段作為上下文。

    **邏輯重點**：
    1. 反序列化 ``project_files_json``。
    2. 對每個 ProjectFile 計算相關性分數（純記憶體，毫秒級）。
    3. 按分數排序，依 Token 預算貪婪納入。
    4. 若有 ``map_reduce_summary``，優先置於上下文最前端。

    **容錯設計**：若反序列化或計算過程失敗，回傳空上下文而非拋出例外，
    ``generate_answer_node`` 將以有限資訊盡力回答。

    Args:
        state: 需包含 ``project_files_json``、``search_keywords``、
               ``question_type``、``map_reduce_summary``（可選）。

    Returns:
        更新後的 :class:`~QAGraphState`，包含 ``context_snippets``、
        ``referenced_files``、``context_token_count``、``used_map_reduce_summary``。
    """
    keywords: List[str] = state.get("search_keywords", [])
    question_type: QuestionType = state.get("question_type", QuestionType.GENERAL)
    map_reduce_summary: str | None = state.get("map_reduce_summary")

    logger.info(
        "[retrieve_context_node] 開始檢索。type=%s，keywords=%s，"
        "Map-Reduce 摘要：%s",
        question_type.value,
        keywords,
        "有" if map_reduce_summary else "無",
    )

    try:
        raw_files = json.loads(state.get("project_files_json", "[]"))
        project_files: List[ProjectFile] = [
            ProjectFile(**f) for f in raw_files
        ]
    except Exception as exc:
        logger.error(
            "[retrieve_context_node] 反序列化 project_files_json 失敗：%s",
            exc,
            exc_info=True,
        )
        return {
            "context_snippets": "",
            "referenced_files": [],
            "context_token_count": 0,
            "used_map_reduce_summary": False,
        }

    # 計算每個檔案的相關性分數
    scored: List[Tuple[ProjectFile, float]] = []
    for pf in project_files:
        score = _score_file(pf, keywords, question_type)
        if score > 0.0:
            scored.append((pf, score))

    # 按分數降序排列
    scored.sort(key=lambda x: x[1], reverse=True)

    logger.info(
        "[retrieve_context_node] 評分完成：%d 個相關檔案（共 %d 個）。",
        len(scored),
        len(project_files),
    )

    # 組裝上下文
    context_str, referenced, total_tokens, used_summary = _build_context_string(
        selected=scored,
        map_reduce_summary=map_reduce_summary,
        token_budget=CONTEXT_TOKEN_BUDGET,
    )

    logger.info(
        "[retrieve_context_node] 上下文組裝完成：%d 個檔案，%d token，"
        "使用 Map-Reduce 摘要：%s。",
        len(referenced),
        total_tokens,
        used_summary,
    )

    return {
        "context_snippets": context_str,
        "referenced_files": referenced,
        "context_token_count": total_tokens,
        "used_map_reduce_summary": used_summary,
    }
