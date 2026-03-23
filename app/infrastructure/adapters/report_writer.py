"""AI 報告文件的輸出層適配器 (ReportWriter)。

負責將 AI 生成的報告實體 :class:`~app.domain.entities.ai_report.AIReport`
序列化並分別寫出為兩份獨立的 Markdown 文件 (``.md``)：
一份 API 使用文件，一份環境建置指南，絕不合併。
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiofiles

from app.domain.entities.ai_report import AIReport

logger = logging.getLogger(__name__)


class ReportWriter:
    """將 AIReport 實體拆分並分別序列化輸出為兩份 Markdown 檔案。

    設計原則：兩份報告永遠分開儲存，讓接收方可以獨立分發或版本控制
    API 文件與環境指南，而無需再做二次拆分。

    Example::

        writer = ReportWriter()
        api_path, env_path = await writer.write(report, output_dir=Path("/tmp/output"))
        print(api_path)   # /tmp/output/my_project_api_docs.md
        print(env_path)   # /tmp/output/my_project_env_guide.md
    """

    async def write(self, report: AIReport, output_dir: Path) -> tuple[Path, Path]:
        """將報告中的兩個區塊分別非同步寫入兩個 Markdown 文件。

        輸出檔名規則：
            - API 文件：``{project_name}_api_docs.md``
            - 環境指南：``{project_name}_env_guide.md``

        Args:
            report: 包含 ``api_docs`` 與 ``env_guide`` 兩個區塊的完整 AI 報告實體。
            output_dir: 輸出的目錄路徑，若目錄不存在將自動建立。

        Returns:
            一個 tuple ``(api_docs_path, env_guide_path)``，各自為
            :class:`~pathlib.Path` 物件，指向寫入完成的文件。

        Raises:
            OSError: 若目錄建立或檔案寫入時發生作業系統層級的 I/O 錯誤。
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = report.project_name.replace(" ", "_").replace("/", "_")

        api_docs_path = output_dir / f"{safe_name}_api_docs.md"
        env_guide_path = output_dir / f"{safe_name}_env_guide.md"

        # ── 寫出 API 文件 ─────────────────────────────────────────────────────
        async with aiofiles.open(api_docs_path, mode="w", encoding="utf-8") as f:
            await f.write(report.api_docs.content)
        logger.info("已寫出 API 文件：%s (%d bytes)", api_docs_path, api_docs_path.stat().st_size)

        # ── 寫出環境指南 ────────────────────────────────────────────────────────
        async with aiofiles.open(env_guide_path, mode="w", encoding="utf-8") as f:
            await f.write(report.env_guide.content)
        logger.info("已寫出環境指南：%s (%d bytes)", env_guide_path, env_guide_path.stat().st_size)

        return api_docs_path, env_guide_path
