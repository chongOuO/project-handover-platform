"""專案交接平台的 Domain 實體 (Entities)。

這些資料類別 (dataclasses) 代表流經 Clean Architecture 每一層的
核心業務物件，確保專案結構資料有單一來源 (Single source of truth)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ProjectFile:
    """代表經過分析的專案中的單一程式碼檔案。

    Attributes:
        relative_path: 相對於 ZIP 根目錄的檔案路徑 (例如：``app/main.py``)。
        language: 推斷出的程式語言，用於 Markdown 的程式碼區塊標示 (例如：``"python"``, ``"javascript"``)。
        content: 檔案的完整 (或被截斷的) 原始碼內容。
        is_truncated: 若內容因超過 Token 限制而被截斷，則為 ``True``。
        token_estimate: 粗略估算的 Token 數量，用於決定是否截斷。
    """

    relative_path: str
    language: str
    content: str
    is_truncated: bool = False
    token_estimate: int = 0


@dataclass
class ProjectStructure:
    """聚合了整個 ZIP 專案分析後的資料結構。

    Attributes:
        project_name: 由 ZIP 檔名衍生而來 (不含副檔名)。
        root_tree: 文字格式的目錄樹狀圖 (將用於 Markdown 報告開頭)。
        files: 包含所有的 :class:`ProjectFile` 實例列表 (僅包含過濾後的程式碼檔案)。
        total_files_in_zip: 在進行過濾前，ZIP 檔案內找到的項目總數。
        skipped_files: 被智慧過濾器忽略的項目數量。
    """

    project_name: str
    root_tree: str
    files: List[ProjectFile] = field(default_factory=list)
    total_files_in_zip: int = 0
    skipped_files: int = 0

    @property
    def code_file_count(self) -> int:
        """回傳被包含在報告中的程式碼檔案數量。

        Returns:
            被採納的程式碼檔案數量 (整數)。
        """
        return len(self.files)
