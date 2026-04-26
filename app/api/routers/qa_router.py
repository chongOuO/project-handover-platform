"""Q&A API 路由器。

提供以下三個端點：
- POST /qa/sessions             ：上傳 ZIP，建立 Q&A Session。
- POST /qa/sessions/{id}/ask    ：基於 Session 進行問答。
- DELETE /qa/sessions/{id}      ：手動刪除 Session。

所有 Response 均遵循現有平台的統一訊息格式（`success` + `data`）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.schemas.qa_schemas import (
    AskRequest,
    AskResponse,
    DeleteSessionResponse,
    SessionCreatedResponse,
)
from app.application.services.qa_service import QAService
from app.domain.exceptions import (
    FileSizeLimitExceededError,
    InvalidZipFileError,
    EmptyProjectError,
    SessionExpiredError,
    SessionNotFoundError,
)
from app.infrastructure.adapters.session_store import InMemorySessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["Q&A"])

# ---------------------------------------------------------------------------
# 依賴注入
# ---------------------------------------------------------------------------

# 模組層級 Session Store 單例，在 main.py lifespan 中建立並注入
_session_store: InMemorySessionStore | None = None


def get_session_store() -> InMemorySessionStore:
    """FastAPI Depends：取得 InMemorySessionStore 單例。

    Returns:
        模組層級的 InMemorySessionStore 實例。

    Raises:
        RuntimeError: 若 Session Store 尚未初始化（lifespan 未正確設定）。
    """
    if _session_store is None:
        raise RuntimeError("SessionStore 尚未初始化，請確認 FastAPI lifespan 設定正確。")
    return _session_store


def set_session_store(store: InMemorySessionStore) -> None:
    """在 main.py lifespan 中設定 Session Store 單例。

    Args:
        store: 啟動時建立的 InMemorySessionStore 實例。
    """
    global _session_store
    _session_store = store


def get_qa_service(
    store: InMemorySessionStore = Depends(get_session_store),
) -> QAService:
    """FastAPI Depends：建立 QAService 並注入 Session Store。"""
    return QAService(session_store=store)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionCreatedResponse,
    summary="上傳 ZIP 建立 Q&A Session",
    description=(
        "上傳專案 ZIP 檔案，觸發 Phase 1 解析（解壓、過濾、讀取程式碼）。"
        "大型專案（> 60K Token）會額外執行 Map-Reduce 精煉摘要。"
        "建立成功後回傳 session_id，後續可憑此 ID 多次提問（Session 有效期 30 分鐘）。"
    ),
)
async def create_session(
    file: UploadFile = File(..., description="專案 ZIP 壓縮檔（最大 50 MB）。"),
    service: QAService = Depends(get_qa_service),
) -> SessionCreatedResponse:
    """建立 Q&A Session。"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=415, detail="僅支援 .zip 格式的壓縮檔。")

    zip_bytes = await file.read()

    try:
        session = await service.create_session(zip_bytes=zip_bytes, filename=file.filename)
    except FileSizeLimitExceededError as exc:
        raise HTTPException(status_code=413, detail=exc.message) from exc
    except InvalidZipFileError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except EmptyProjectError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except Exception as exc:
        logger.error("[qa_router] 建立 Session 發生未預期例外：%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="建立 Session 時發生內部錯誤，請稍後再試。") from exc

    return SessionCreatedResponse(
        session_id=session.session_id,
        project_name=session.project_name,
        file_count=len(session.project_files),
        expires_at=session.expires_at.isoformat(),
        has_map_reduce_summary=session.map_reduce_summary is not None,
        message="Session 建立成功，可開始提問。",
    )


@router.post(
    "/sessions/{session_id}/ask",
    response_model=AskResponse,
    summary="對 Session 提問",
    description=(
        "基於已建立的 Session 進行自然語言問答。"
        "系統會自動分類問題、篩選相關程式碼片段，並呼叫 LLM 生成答案。"
    ),
)
async def ask_question(
    session_id: str,
    body: AskRequest,
    service: QAService = Depends(get_qa_service),
) -> AskResponse:
    """對指定 Session 提問。"""
    try:
        result = await service.ask(session_id=session_id, question=body.question)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=exc.message) from exc
    except Exception as exc:
        logger.error("[qa_router] 問答發生未預期例外：%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="問答時發生內部錯誤，請稍後再試。") from exc

    return AskResponse(
        answer=result.answer,
        question_type=result.question_type.value,
        referenced_files=result.referenced_files,
        context_token_count=result.context_token_count,
        used_map_reduce_summary=result.used_map_reduce_summary,
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
    summary="刪除 Q&A Session",
    description="手動刪除指定的 Session，釋放記憶體。Session 也會在到期後自動清理。",
)
async def delete_session(
    session_id: str,
    service: QAService = Depends(get_qa_service),
) -> DeleteSessionResponse:
    """手動刪除指定 Session。"""
    deleted = await service.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"找不到 Session '{session_id}'，可能已過期或從未建立。",
        )
    return DeleteSessionResponse(
        session_id=session_id,
        message="Session 已成功刪除。",
    )
