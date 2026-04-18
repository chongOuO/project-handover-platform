"""Infrastructure 層的 Adapter：智慧檔案過濾。

實作智慧過濾器 (smart filter)，決定解壓縮後的 ZIP 檔案中，
有哪些檔案有價值被包含在最後的 Markdown 報告裡。

支援兩種過濾模式：

- ``FilterMode.DEFAULT``：納入所有原始碼（保留現有行為）。
- ``FilterMode.API_DOCS``：在 DEFAULT 基礎上額外排除前端相關檔案與目錄，
  讓送入 API Docs LLM 的 Markdown 只含後端路由相關訊號，降低 Token 噪音。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import FrozenSet


class FilterMode(str, Enum):
    """過濾器模式。

    Attributes:
        DEFAULT: 標準模式，採納所有原始碼（現有行為）。
        API_DOCS: API 文件模式，在 DEFAULT 基礎上額外排除純前端檔案與目錄。
    """

    DEFAULT = "default"
    API_DOCS = "api_docs"


# ---------------------------------------------------------------------------
# 過濾器設定 (Filter configuration)
# ---------------------------------------------------------------------------

#: 應被完全忽略的目錄名稱 (包含其下的所有子目錄與檔案)。
IGNORED_DIRS: FrozenSet[str] = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".build",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".next",
        ".nuxt",
        "out",
        "target",  # Rust / Java Maven
        "vendor",  # Go / PHP
    }
)

#: API_DOCS 模式下額外排除的純前端目錄名稱。
#: 這些目錄幾乎不含 HTTP 路由定義，排除後可顯著降低 Token 噪音。
API_DOCS_FRONTEND_DIRS: FrozenSet[str] = frozenset(
    {
        "components",
        "pages",        # 注意：Next.js App Router 中 pages/ 含 API routes，
                        # 但在純前端情境下此目錄僅含 UI。保守排除。
        "hooks",
        "styles",
        "assets",
        "public",
        "static",
        "__tests__",
        "__mocks__",
        "stories",      # Storybook
        "storybook",
        "ui",
        "theme",
    }
)

#: API_DOCS 模式下額外排除的純前端副檔名。
#: 這些副檔名幾乎不含後端路由定義。
API_DOCS_FRONTEND_EXTENSIONS: FrozenSet[str] = frozenset(
    {
        ".tsx",
        ".jsx",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".htm",
    }
)

#: 要忽略的檔案副檔名 (例如：二進位檔、媒體檔、Lock files 等)。
IGNORED_EXTENSIONS: FrozenSet[str] = frozenset(
    {
        # 圖片 (Images)
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".bmp", ".webp",
        ".tiff", ".tif",
        # 字型 (Fonts)
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        # 音訊 / 影音 (Audio / Video)
        ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".ogg", ".flac",
        # 壓縮檔 (Archives)
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        # 文件 / 數據檔 (Documents / data)
        ".pdf", ".docx", ".xlsx", ".pptx",
        # Lock files
        ".lock",
        # 編譯檔 / 二進位檔 (Compiled / binary)
        ".pyc", ".pyo", ".class", ".o", ".obj", ".exe", ".dll", ".so",
        ".dylib", ".a", ".lib", ".wasm",
        # 資料庫 (Database)
        ".sqlite", ".db", ".sqlite3",
    }
)

#: 被視為原始碼的副檔名 (以及精確的比對名稱)。
ACCEPTED_EXTENSIONS: FrozenSet[str] = frozenset(
    {
        ".py", ".pyi",
        ".js", ".mjs", ".cjs",
        ".ts", ".tsx", ".jsx",
        ".java", ".kt", ".kts",
        ".go",
        ".rs",
        ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".sh", ".bash", ".zsh", ".fish",
        ".yaml", ".yml",
        ".toml",
        ".json",
        ".xml",
        ".md", ".rst",
        ".html", ".htm",
        ".css", ".scss", ".sass", ".less",
        ".sql",
        ".graphql", ".gql",
        ".tf", ".tfvars",  # Terraform
        ".env.example",
    }
)

#: 無論副檔名為何，只要檔名精確符合都會被採納的集合。
ACCEPTED_BASENAMES: FrozenSet[str] = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "Procfile",
        ".env.example",
        ".gitignore",
        "Jenkinsfile",
        "Vagrantfile",
    }
)


class FileFilter:
    """決定 ZIP 檔案內的某個路徑是否應被包含在報告中。

    Example::

        filt = FileFilter()
        accepted = [p for p in all_paths if filt.is_accepted(p)]
    """

    def is_accepted(self, relative_path: str, mode: FilterMode = FilterMode.DEFAULT) -> bool:
        """若 *relative_path* 處的檔案應被包含，則回傳 ``True``。

        當符合以下 **所有** 條件時，該檔案才會被採納：

        1. 它的任何一層父目錄名稱皆不在 ``IGNORED_DIRS`` 中。
        2. 它的副檔名不在 ``IGNORED_EXTENSIONS`` 中。
        3. 它的副檔名在 ``ACCEPTED_EXTENSIONS`` 中，*或者* 其檔名精確符合
           ``ACCEPTED_BASENAMES`` 內的值。

        在 ``FilterMode.API_DOCS`` 模式下，額外排除：

        4. 任何一層父目錄名稱在 ``API_DOCS_FRONTEND_DIRS`` 中的路徑。
        5. 副檔名在 ``API_DOCS_FRONTEND_EXTENSIONS`` 中的檔案。

        Args:
            relative_path: 相對於 ZIP 根目錄的路徑字串 (例如：``"app/main.py"``)。
            mode: 過濾模式，預設為 ``FilterMode.DEFAULT``（保留現有行為）。

        Returns:
            若檔案應被包含在報告中，則回傳 ``True``。
        """
        path = Path(relative_path)

        # 略過看起來像純目錄的項目 (以斜線結尾)
        if relative_path.endswith("/"):
            return False

        # 檢查路徑中的每一層目錄（通用規則）
        for part in path.parts[:-1]:  # exclude the filename itself
            if part in IGNORED_DIRS:
                return False

        # API_DOCS 模式：額外排除純前端目錄
        if mode == FilterMode.API_DOCS:
            for part in path.parts[:-1]:
                if part in API_DOCS_FRONTEND_DIRS:
                    return False

        basename = path.name
        suffix = path.suffix.lower()

        # 明確定義在忽略清單的副檔名優先排除
        if suffix in IGNORED_EXTENSIONS:
            return False

        # API_DOCS 模式：額外排除純前端副檔名
        if mode == FilterMode.API_DOCS and suffix in API_DOCS_FRONTEND_EXTENSIONS:
            return False

        # 採納明確定義的檔名 (例如：Dockerfile)
        if basename in ACCEPTED_BASENAMES:
            return True

        # 根據副檔名決定是否採納
        return suffix in ACCEPTED_EXTENSIONS

    def infer_language(self, relative_path: str) -> str:
        """根據副檔名推斷 Markdown 程式碼區塊所需的語言標記。

        Args:
            relative_path: 相對於 ZIP 根目錄的路徑字串。

        Returns:
            適合用於 Markdown 程式碼區塊標記的語言字串
            (例如：``"python"``, ``"javascript"``)。
            對於未知的副檔名將回傳空字串 ``""``。
        """
        ext_to_lang: dict[str, str] = {
            ".py": "python", ".pyi": "python",
            ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
            ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
            ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
            ".go": "go",
            ".rs": "rust",
            ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
            ".cxx": "cpp", ".hpp": "cpp",
            ".cs": "csharp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "fish",
            ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml",
            ".json": "json",
            ".xml": "xml",
            ".md": "markdown", ".rst": "rst",
            ".html": "html", ".htm": "html",
            ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
            ".sql": "sql",
            ".graphql": "graphql", ".gql": "graphql",
            ".tf": "hcl", ".tfvars": "hcl",
        }
        path = Path(relative_path)
        return ext_to_lang.get(path.suffix.lower(), "")
