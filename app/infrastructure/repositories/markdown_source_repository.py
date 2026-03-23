"""AI 分析管線的 Markdown 來源文件存取層 (Repository)。

負責從本地磁碟非同步讀取 Phase 1 產出的 ``.md`` 格式來源報告文件，
並在路徑不合法或讀取失敗時拋出適當的 Domain 例外，確保錯誤在Infrastructure 層就被明確攔截。
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiofiles

from app.domain.exceptions import MarkdownSourceNotFoundError

logger = logging.getLogger(__name__)


class MarkdownSourceRepository:
    """提供對本地 Markdown 報告檔案的讀取存取能力。

    此 Repository 屬於 Infrastructure 層，負責將「讀取 .md 文件」這一
    I/O 副作用行為與 Application 業務邏輯完全解耦。

    Example::

        repo = MarkdownSourceRepository()
        content = await repo.read(Path("/path/to/report.md"))
        print(content[:200])
    """

    async def read(self, path: Path) -> str:
        """非同步讀取指定路徑的 Markdown 文件全文內容。

        Args:
            path: 目標 Markdown 文件的絕對或相對 :class:`~pathlib.Path`。

        Returns:
            以 UTF-8 解碼的完整 Markdown 原始字串。

        Raises:
            MarkdownSourceNotFoundError: 當指定路徑不存在或無法讀取時。
        """
        if not path.exists() or not path.is_file():
            raise MarkdownSourceNotFoundError(
                path=str(path),
                detail=f"路徑 '{path}' 不存在或並非一般檔案。",
            )

        logger.info("讀取 Markdown 來源文件：%s (大小：%d bytes)", path, path.stat().st_size)

        try:
            async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
                content = await f.read()
        except OSError as exc:
            raise MarkdownSourceNotFoundError(
                path=str(path),
                detail=f"檔案讀取失敗：{exc}",
            ) from exc

        return content
