"""Application 層的 Service：專案分析流程的編排協調。

此服務層介於 API 層與基礎設施的 Adapter 之間，負責協調整個 Phase-1
的管線流程 (Pipeline)：

    上傳檔案位元組 → 解壓縮 ZIP → 過濾檔案 → 讀取內容 → 產生 Markdown 報告

此架構採用了 Clean Architecture 的依賴反轉 (Dependency Inversion) 特性：
Application Service 所依賴的是抽象的行為 (非同步方法本身)，而非實際具體的實作細節。
"""

from __future__ import annotations

import shutil
from typing import List

from app.domain.entities.project import ProjectFile, ProjectStructure
from app.domain.exceptions import EmptyProjectError, FileSizeLimitExceededError
from app.infrastructure.adapters.file_filter import FileFilter, FilterMode
from app.infrastructure.adapters.markdown_generator import (
    MarkdownGenerator,
    TOKEN_LIMIT,
    _estimate_tokens,
    _truncate_content,
    build_directory_tree,
)
from app.infrastructure.adapters.zip_extractor import ZipExtractor
from app.infrastructure.repositories.project_repository import ProjectRepository

#: 允許的 ZIP 最大位元組大小 (50 MB)。
MAX_ZIP_SIZE_BYTES: int = 50 * 1024 * 1024


class ProjectAnalysisService:
    """協調編排「上傳 ZIP → 轉換為 Markdown 報告」的完整管線。

    Example::

        service = ProjectAnalysisService()
        structure = await service.analyze(zip_bytes=b"...", filename="project.zip")
        print(structure.code_file_count)

    Attributes:
        _extractor: 用於 ZIP 解壓縮的 Adapter。
        _filter: 用於智慧檔案過濾的 Adapter。
        _generator: 用於產生 Markdown 的 Adapter。
    """

    def __init__(self) -> None:
        """透過預設基礎設施的 Adapters 來初始化這項服務。"""
        self._extractor = ZipExtractor()
        self._filter = FileFilter()
        self._generator = MarkdownGenerator()

    async def analyze(
        self,
        zip_bytes: bytes,
        filename: str,
        filter_mode: FilterMode = FilterMode.DEFAULT,
    ) -> ProjectStructure:
        """執行 Phase-1 完整的分析管線。

        Args:
            zip_bytes: 上傳的 ZIP 檔案之原始位元組資料。
            filename: 上傳時的原始檔名 (例如：``"my_project.zip"``)。
            filter_mode: 檔案過濾模式，預設為 ``FilterMode.DEFAULT``（納入所有原始碼）。
                傳入 ``FilterMode.API_DOCS`` 可額外排除前端相關檔案，提升
                API 文件生成的信號品質。

        Returns:
            一個已經填好資料的 :class:`~app.domain.entities.project.ProjectStructure`
            實體，其內的 ``files`` 列表包含了經過過濾、且 (可能已被截斷的) 程式碼檔案。
            另外 ``root_tree`` 屬性中存放了文字格式的專案目錄樹。

        Raises:
            FileSizeLimitExceededError: 當 *zip_bytes* 的總容量超過 50 MB 時。
            InvalidZipFileError: 若位元組無法解析為有效的 ZIP 壓縮檔時。
            EmptyProjectError: 當套用智慧過濾器之後，找不到任何可用的程式碼時拋出。
        """
        # ── 檢查守衛 (Guard): 檔案大小限制 ────────────────────────────────────
        if len(zip_bytes) > MAX_ZIP_SIZE_BYTES:
            raise FileSizeLimitExceededError(max_mb=50)

        # ── 步驟 1: 從原始檔名中萃取出專案名稱 ─────────────────────────────────
        project_name = filename.removesuffix(".zip") if filename.endswith(".zip") else filename

        # ── 步驟 2: 將 ZIP 解壓縮至暫存目錄 ────────────────────────────────────
        tmp_dir, namelist = await self._extractor.extract(zip_bytes, filename)

        try:
            # ── 步驟 3: 基於所有的成員名單建立起目錄樹 ───────────────────────────
            root_tree = build_directory_tree(namelist, project_name)

            # ── 步驟 4: 過濾出有價值的程式碼檔案 ─────────────────────────────────
            repo = ProjectRepository(root_dir=tmp_dir)
            all_disk_files = await repo.list_files()

            accepted_paths: list[str] = [
                p for p in all_disk_files if self._filter.is_accepted(p, mode=filter_mode)
            ]
            skipped = len(all_disk_files) - len(accepted_paths)

            if not accepted_paths:
                raise EmptyProjectError(
                    detail=f"檢視了 {len(all_disk_files)} 個檔案；全數遭到過濾淘汰。"
                )

            # ── 步驟 5: 讀取並 (視情況) 截斷每份程式碼檔案內容 ──────────────────────
            project_files: List[ProjectFile] = []
            for rel_path in accepted_paths:
                raw_content = await repo.read_file(rel_path)
                content, was_truncated = _truncate_content(raw_content, TOKEN_LIMIT)
                token_est = _estimate_tokens(content)
                language = self._filter.infer_language(rel_path)

                project_files.append(
                    ProjectFile(
                        relative_path=rel_path,
                        language=language,
                        content=content,
                        is_truncated=was_truncated,
                        token_estimate=token_est,
                    )
                )

            # ── 步驟 6: 組裝出 Application Domain 領域的實體 ──────────────────────
            structure = ProjectStructure(
                project_name=project_name,
                root_tree=root_tree,
                files=project_files,
                total_files_in_zip=len(namelist),
                skipped_files=skipped,
            )
            return structure

        finally:
            # 不論過程是否發生錯誤，總是清空拋棄式的暫存目錄
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def render_markdown(self, structure: ProjectStructure) -> str:
        """將 :class:`ProjectStructure` 物件轉換並渲染為文字形式的 Markdown。

        這個部分獨立於 :meth:`analyze` 方法之外，以方便呼叫端在快取住
        structure 後若是參數有異動可重新進行渲染。

        Args:
            structure: 已經填滿整個專案資訊的結構資料物件。

        Returns:
            完整的 UTF-8 Markdown 報告字串內容。
        """
        return self._generator.generate(structure)
