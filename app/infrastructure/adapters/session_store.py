"""Infrastructure 層 Adapter：記憶體型 Q&A Session 儲存。

Session 模式的核心元件，負責儲存已上傳專案的解析結果，
讓後續多次提問可重複使用，而不需每次重新處理 ZIP 檔案。

架構定位：
    此模組為 Infrastructure 層，只被 Application Service 呼叫，
    不直接被 API 路由或 LangGraph 節點依賴。

生命週期管理：
    - Session 建立後有效期限預設為 ``SESSION_TTL_MINUTES`` 分鐘（預設 30 分鐘）。
    - 需在 FastAPI ``lifespan`` 中啟動背景 ``asyncio.Task``，
      定期呼叫 ``cleanup_expired()`` 清除過期 Session。
    - 若未來需水平擴展至多實例部署，可將 ``InMemorySessionStore``
      替換為 Redis 實作（Interface 協議相同）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from app.domain.entities.project import ProjectFile

logger = logging.getLogger(__name__)

#: Session 有效期限（分鐘）。過期後自動清理，提問時也會觸發 SessionExpiredError。
SESSION_TTL_MINUTES: int = 30

#: 背景清理任務的執行間隔（秒）。
CLEANUP_INTERVAL_SECONDS: int = 300  # 5 分鐘


@dataclass
class SessionData:
    """單一 Q&A Session 的完整快取資料。

    建立 Session 時由 ``InMemorySessionStore.create_session()`` 填入，
    後續提問時直接讀取，不再重新解析 ZIP。

    Attributes:
        session_id: Session 的唯一識別碼（UUID4 字串）。
        project_name: 上傳的專案名稱（取自 ZIP 檔名去除副檔名）。
        project_files: Phase 1 解析後的程式碼檔案列表。
        markdown_content: Phase 1 生成的完整 Markdown 報告字串。
        map_reduce_summary: Map-Reduce 精煉摘要（大型專案才有值；小型專案為 None）。
        created_at: Session 建立時間（UTC）。
        expires_at: Session 過期時間（UTC），超過此時間後 Session 視為失效。
    """

    session_id: str
    project_name: str
    project_files: List[ProjectFile]
    markdown_content: str
    map_reduce_summary: Optional[str]
    created_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        """判斷 Session 是否已過期。

        Returns:
            若當前 UTC 時間已超過 ``expires_at``，回傳 ``True``。
        """
        return datetime.now(tz=timezone.utc) >= self.expires_at


class InMemorySessionStore:
    """記憶體型 Session 儲存，以 dict 實作 O(1) 查詢。

    **執行緒安全性**：本實作使用 ``asyncio.Lock`` 保護 ``_store``，
    適合 FastAPI 單一 event loop 的 async 環境。
    若需多 worker（多 event loop）環境請改用 Redis。

    Example::

        store = InMemorySessionStore()
        session = await store.create_session(
            project_name="my-project",
            project_files=files,
            markdown_content=md,
            map_reduce_summary=summary,
        )
        retrieved = await store.get_session(session.session_id)
    """

    def __init__(self) -> None:
        """初始化空的 Session 儲存與互斥鎖。"""
        self._store: Dict[str, SessionData] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        project_name: str,
        project_files: List[ProjectFile],
        markdown_content: str,
        map_reduce_summary: Optional[str] = None,
        ttl_minutes: int = SESSION_TTL_MINUTES,
    ) -> SessionData:
        """建立並儲存新的 Session。

        Args:
            project_name: 專案名稱（取自 ZIP 檔名）。
            project_files: Phase 1 解析後的程式碼檔案列表。
            markdown_content: 完整的 Markdown 報告字串。
            map_reduce_summary: Map-Reduce 精煉摘要（大型專案才有值）。
            ttl_minutes: Session 有效期限（分鐘），預設使用 ``SESSION_TTL_MINUTES``。

        Returns:
            新建立的 :class:`SessionData` 實例。
        """
        now = datetime.now(tz=timezone.utc)
        session = SessionData(
            session_id=str(uuid.uuid4()),
            project_name=project_name,
            project_files=project_files,
            markdown_content=markdown_content,
            map_reduce_summary=map_reduce_summary,
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        async with self._lock:
            self._store[session.session_id] = session

        logger.info(
            "[SessionStore] 已建立 Session %s（專案：%s，檔案數：%d，"
            "Map-Reduce 摘要：%s，過期時間：%s）",
            session.session_id,
            project_name,
            len(project_files),
            "有" if map_reduce_summary else "無",
            session.expires_at.isoformat(),
        )
        return session

    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """查詢 Session，不自動刪除過期 Session（由呼叫端決定是否拋出例外）。

        Args:
            session_id: Session 的唯一識別碼。

        Returns:
            若存在（不論是否過期）回傳 :class:`SessionData`；否則回傳 ``None``。
        """
        async with self._lock:
            return self._store.get(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """手動刪除指定 Session。

        Args:
            session_id: 要刪除的 Session 識別碼。

        Returns:
            若成功刪除回傳 ``True``；若 Session 不存在回傳 ``False``。
        """
        async with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                logger.info("[SessionStore] 手動刪除 Session %s。", session_id)
                return True
        return False

    async def cleanup_expired(self) -> int:
        """掃描並清除所有已過期的 Session。

        應由 FastAPI ``lifespan`` 中的背景 ``asyncio.Task`` 定期呼叫。

        Returns:
            本次清除的 Session 數量。
        """
        expired_ids = []
        async with self._lock:
            for sid, session in self._store.items():
                if session.is_expired():
                    expired_ids.append(sid)
            for sid in expired_ids:
                del self._store[sid]

        if expired_ids:
            logger.info(
                "[SessionStore] 自動清理 %d 個過期 Session：%s",
                len(expired_ids),
                expired_ids,
            )
        return len(expired_ids)

    @property
    def active_count(self) -> int:
        """回傳當前儲存中的 Session 總數（含已過期但尚未清理者）。"""
        return len(self._store)


async def run_cleanup_loop(store: InMemorySessionStore) -> None:
    """背景清理迴圈，供 FastAPI ``lifespan`` 作為 asyncio.Task 執行。

    每隔 ``CLEANUP_INTERVAL_SECONDS`` 秒呼叫一次 ``cleanup_expired()``，
    確保記憶體不因大量過期 Session 而持續累積。

    Args:
        store: 需要定期清理的 :class:`InMemorySessionStore` 實例。

    Example（在 main.py lifespan 中使用）::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            task = asyncio.create_task(run_cleanup_loop(session_store))
            yield
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    """
    logger.info(
        "[SessionStore] 背景清理任務已啟動，間隔 %d 秒。",
        CLEANUP_INTERVAL_SECONDS,
    )
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            count = await store.cleanup_expired()
            if count:
                logger.debug("[SessionStore] 定期清理完成，移除 %d 個過期 Session。", count)
        except Exception as exc:
            logger.error("[SessionStore] 清理任務發生例外：%s", exc, exc_info=True)
