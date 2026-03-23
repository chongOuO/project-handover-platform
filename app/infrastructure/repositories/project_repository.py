"""Infrastructure 層的 Repository：專案檔案的輸入輸出 (I/O)。

提供針對解壓縮後專案檔案操作的非同步抽象層。
如此能確保應用層 (Appication Service) 專注在業務邏輯，不被底層 I/O 細節所干擾。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List


class ProjectRepository:
    """針對已經解壓縮之 ZIP 專案的非同步檔案讀取器。

    Args:
        root_dir: ZIP 被解壓縮的目標目錄之絕對路徑。

    Example::

        repo = ProjectRepository(root_dir="/tmp/handover_xyz")
        files = await repo.list_files()
        content = await repo.read_file("app/main.py")
    """

    def __init__(self, root_dir: str) -> None:
        """透過解壓縮根目錄來初始化 Repository。

        Args:
            root_dir: ZIP 檔被解壓縮的目標目錄之絕對路徑。
        """
        self._root = Path(root_dir)

    async def list_files(self) -> List[str]:
        """回傳目錄中所有的檔案路徑 (皆為相對於根目錄的路徑)。

        純目錄結構本身會從列表中被排除。

        Returns:
            已排序的相對路徑字串列表 (例如：``["app/main.py"]``)。
        """
        return await asyncio.to_thread(self._list_files_sync)

    async def read_file(self, relative_path: str) -> str:
        """讀取並回傳單一檔案的文字內容。

        任何編碼錯誤都將被置換為 Unicode Replacement Character
        (``U+FFFD``)，以確保那些偽裝為純文字的二進位檔案不會導致管線崩潰。

        Args:
            relative_path: 相對於解壓縮根目錄的路徑。

        Returns:
            編碼為 UTF-8 的檔案內容字串。
        """
        return await asyncio.to_thread(self._read_file_sync, relative_path)

    # ------------------------------------------------------------------
    # 私有 / 同步的輔助函式 (Private / sync helpers)
    # ------------------------------------------------------------------

    def _list_files_sync(self) -> List[str]:
        """阻斷式地實作 :meth:`list_files` 的細節。

        Returns:
            排序過後的相對路徑字串列表。
        """
        result: List[str] = []
        for path in self._root.rglob("*"):
            if path.is_file():
                result.append(str(path.relative_to(self._root)))
        return sorted(result)

    def _read_file_sync(self, relative_path: str) -> str:
        """阻斷式地實作 :meth:`read_file` 的細節。

        Args:
            relative_path: 相對於解壓縮根目錄的路徑。

        Returns:
            已將無法解碼字元做替換的 UTF-8 文字內容。
        """
        full_path = self._root / relative_path
        return full_path.read_text(encoding="utf-8", errors="replace")
