"""Application 層 Service：Q&A Session 生命週期管理。

此 Service 是 Q&A 功能的業務邏輯核心，介於 API Router 與底層基礎設施之間，
負責編排以下三個職責：

1. **建立 Session**：呼叫 Phase 1（ZIP 解析）+ Map-Reduce 預計算 + 存入 SessionStore。
2. **問答**：查詢 Session + 驅動 QA LangGraph 管線 + 回傳 QAResult。
3. **刪除 Session**：手動清理 SessionStore 中的指定 Session。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from app.application.graphs.qa_graph import build_qa_graph
from app.domain.entities.qa_models import QAResult, QuestionType, SessionInfo
from app.domain.exceptions import SessionExpiredError, SessionNotFoundError
from app.infrastructure.adapters.map_reduce_summarizer import (
    MAP_REDUCE_THRESHOLD,
    MapReduceSummarizer,
    _estimate_tokens,
)
from app.infrastructure.adapters.session_store import InMemorySessionStore, SessionData
from app.application.services.project_analysis_service import ProjectAnalysisService
from app.infrastructure.adapters.file_filter import FilterMode

logger = logging.getLogger(__name__)

# 模組層級共享的 LangGraph 編譯圖（避免每次呼叫重新編譯）
_qa_graph = build_qa_graph()


class QAService:
    """Q&A Session 生命週期的業務邏輯服務。

    應在 FastAPI 啟動時實例化一次，透過 ``Depends`` 注入各 Router。
    ``InMemorySessionStore`` 由外部傳入，支援測試時替換 Mock。

    Args:
        session_store: Session 儲存實例（預設為 ``InMemorySessionStore``）。

    Example::

        service = QAService(session_store=InMemorySessionStore())
        session = await service.create_session(zip_bytes, "project.zip")
        result = await service.ask(session.session_id, "認證機制是什麼？")
    """

    def __init__(self, session_store: InMemorySessionStore) -> None:
        self._store = session_store
        self._analysis_service = ProjectAnalysisService()
        self._summarizer = MapReduceSummarizer()

    async def create_session(self, zip_bytes: bytes, filename: str) -> SessionData:
        """上傳 ZIP，執行 Phase 1 解析，並建立 Q&A Session。

        **流程**：
        1. `ProjectAnalysisService.analyze()` 解壓 ZIP、過濾、讀取內容
           → 回傳 `ProjectStructure`（含 `project_files`）。
        2. `render_markdown()` 生成對應的 Markdown 報告字串。
        3. `MapReduceSummarizer.summarize()` 對 Markdown 進行摘要：
           - 小型專案（< 60K Token）：直接 passthrough，無 LLM 呼叫。
           - 大型專案（≥ 60K Token）：執行 Map-Reduce，需額外 LLM 呼叫。
        4. 將所有結果存入 `InMemorySessionStore`。

        Args:
            zip_bytes: 上傳的 ZIP 原始位元組。
            filename: 原始檔名（例如 ``"my-project.zip"``）。

        Returns:
            已建立的 :class:`~SessionData` 實例。

        Raises:
            FileSizeLimitExceededError: ZIP 超過 50 MB。
            InvalidZipFileError: 不是有效的 ZIP 檔案。
            EmptyProjectError: 過濾後沒有任何程式碼檔案。
        """
        logger.info("[QAService] 開始建立 Session，檔案：%s，大小：%d bytes。", filename, len(zip_bytes))

        # Phase 1：ZIP 解析
        structure = await self._analysis_service.analyze(
            zip_bytes=zip_bytes,
            filename=filename,
            filter_mode=FilterMode.DEFAULT,
        )
        markdown_content = self._analysis_service.render_markdown(structure)

        logger.info(
            "[QAService] Phase 1 完成：%d 個程式碼檔案，Markdown %d 字元（約 %d token）。",
            len(structure.files),
            len(markdown_content),
            _estimate_tokens(markdown_content),
        )

        # Map-Reduce 預計算（小型專案 passthrough）
        token_estimate = _estimate_tokens(markdown_content)
        map_reduce_summary: str | None = None

        if token_estimate > MAP_REDUCE_THRESHOLD:
            logger.info(
                "[QAService] 大型專案（%d token > 閾值 %d），觸發 Map-Reduce...",
                token_estimate,
                MAP_REDUCE_THRESHOLD,
            )
            try:
                summary = await self._summarizer.summarize(markdown_content)
                map_reduce_summary = summary
                logger.info(
                    "[QAService] Map-Reduce 完成，摘要 %d 字元。",
                    len(summary),
                )
            except Exception as exc:
                logger.warning(
                    "[QAService] Map-Reduce 失敗，Session 將以無摘要模式建立：%s",
                    exc,
                    exc_info=True,
                )
        else:
            logger.info(
                "[QAService] 小型專案（%d token ≤ 閾值 %d），跳過 Map-Reduce。",
                token_estimate,
                MAP_REDUCE_THRESHOLD,
            )

        # 存入 Session Store
        session = await self._store.create_session(
            project_name=structure.project_name,
            project_files=structure.files,
            markdown_content=markdown_content,
            map_reduce_summary=map_reduce_summary,
        )

        logger.info("[QAService] Session %s 已建立。", session.session_id)
        return session

    async def ask(self, session_id: str, question: str) -> QAResult:
        """對已建立的 Session 提問。

        Args:
            session_id: 目標 Session 識別碼。
            question: 使用者輸入的問題字串。

        Returns:
            :class:`~QAResult` 實例，包含答案、問題分類、參考檔案等。

        Raises:
            SessionNotFoundError: Session 不存在。
            SessionExpiredError: Session 已過期。
        """
        # 查詢 Session
        session = await self._store.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        if session.is_expired():
            raise SessionExpiredError(session_id)

        logger.info(
            "[QAService] 開始問答。Session=%s，問題：%s",
            session_id,
            question[:100],
        )

        # 序列化 project_files（dataclass → dict → JSON）
        project_files_json = json.dumps(
            [asdict(pf) for pf in session.project_files],
            ensure_ascii=False,
        )

        # 驅動 QA LangGraph
        result_state = await _qa_graph.ainvoke(
            {
                "question": question,
                "project_files_json": project_files_json,
                "markdown_content": session.markdown_content,
                "map_reduce_summary": session.map_reduce_summary,
            }
        )

        logger.info(
            "[QAService] 問答完成。type=%s，參考檔案=%d，Token=%d。",
            result_state.get("question_type", "unknown"),
            len(result_state.get("referenced_files", [])),
            result_state.get("context_token_count", 0),
        )

        return QAResult(
            answer=result_state.get("answer", "無法生成答案，請稍後再試。"),
            question_type=result_state.get("question_type", QuestionType.GENERAL),
            referenced_files=result_state.get("referenced_files", []),
            context_token_count=result_state.get("context_token_count", 0),
            used_map_reduce_summary=result_state.get("used_map_reduce_summary", False),
        )

    async def delete_session(self, session_id: str) -> bool:
        """手動刪除指定 Session。

        Args:
            session_id: 要刪除的 Session 識別碼。

        Returns:
            若成功刪除回傳 ``True``；Session 不存在時回傳 ``False``。
        """
        deleted = await self._store.delete_session(session_id)
        if deleted:
            logger.info("[QAService] Session %s 已手動刪除。", session_id)
        return deleted

    def get_session_info(self, session_data: SessionData) -> SessionInfo:
        """將 SessionData 轉換為對外安全的 SessionInfo（不含原始碼內容）。

        Args:
            session_data: 內部的 Session 資料物件。

        Returns:
            :class:`~SessionInfo` 實例。
        """
        return SessionInfo(
            session_id=session_data.session_id,
            project_name=session_data.project_name,
            file_count=len(session_data.project_files),
            expires_at=session_data.expires_at.isoformat(),
            has_map_reduce_summary=session_data.map_reduce_summary is not None,
        )
