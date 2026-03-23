"""Infrastructure 層的 Adapter：ZIP 檔案解壓縮。

透過將阻塞式的 I/O 操作交由 :func:`asyncio.to_thread` 的執行緒池 (thread pool) 處理，
將 Python 內建的 :mod:`zipfile` 模組包裝成非同步的介面。
"""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple

from app.domain.exceptions import InvalidZipFileError


class ZipExtractor:
    """非同步地將 ZIP 壓縮檔解壓縮至暫存目錄中。

    呼叫端需自行負責清理這個暫存目錄。典型的使用模式如下：

        extractor = ZipExtractor()
        tmp_dir, names = await extractor.extract(zip_bytes, "my_project.zip")
        try:
            # 處理檔案流程 …
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    """

    async def extract(
        self, zip_bytes: bytes, original_filename: str
    ) -> Tuple[str, list[str]]:
        """將 *zip_bytes* 解壓縮至暫存目錄。

        Args:
            zip_bytes: 上傳之 ZIP 檔案的原始位元組 (bytes)。
            original_filename: 原始檔名 (僅用於錯誤訊息中顯示)。

        Returns:
            回傳一個 tuple，格式為 ``(tmp_dir_path, namelist)``，其中
            *tmp_dir_path* 是解壓縮根目錄的絕對路徑，而 *namelist* 則是該壓縮檔內
            所有成員的路徑列表。

        Raises:
            InvalidZipFileError: 當 *zip_bytes* 無法被解析為 ZIP 檔案時拋出。
        """
        return await asyncio.to_thread(
            self._extract_sync, zip_bytes, original_filename
        )

    # ------------------------------------------------------------------
    # 私有輔助函式 (Private helpers)
    # ------------------------------------------------------------------

    def _extract_sync(
        self, zip_bytes: bytes, original_filename: str
    ) -> Tuple[str, list[str]]:
        """阻塞式的解壓縮邏輯 — 於執行緒池內的 worker 中執行。

        Args:
            zip_bytes: ZIP 檔案的原始位元組。
            original_filename: 用於錯誤訊息的原始檔名。

        Returns:
            包含 ``(tmp_dir_path, namelist)`` 的 tuple。

        Raises:
            InvalidZipFileError: 當位元組無法構成一個有效的 ZIP 檔案時。
        """
        import io

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                namelist = zf.namelist()
                tmp_dir = tempfile.mkdtemp(prefix="handover_")
                zf.extractall(tmp_dir)
                return tmp_dir, namelist
        except zipfile.BadZipFile as exc:
            raise InvalidZipFileError(detail=str(exc)) from exc
