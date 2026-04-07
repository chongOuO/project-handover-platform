"""Infrastructure 層的 Adapter：智慧內容壓縮器。

針對大型專案提供多策略漸進式壓縮，確保最終送入 LLM 的 Markdown 報告
能控制在 Token 預算範圍內。

壓縮策略按優先順序執行：
    1. AST Skeleton Extraction（僅保留函式簽章與 Docstring）
    2. Priority-Based File Selection（依重要性排序裁減低優先級檔案）
    3. Aggressive Truncation（強制截斷剩餘超限檔案）
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import List, Optional

from app.domain.entities.project import ProjectFile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 檔案優先級定義
# ---------------------------------------------------------------------------


class FilePriority(IntEnum):
    """檔案重要性等級（數值越小越重要）。

    用於 Token 預算不足時，決定哪些檔案優先保留、哪些優先裁減。
    """

    ENTRY_POINT = 1    # main.py, app.py, index.ts, manage.py
    ROUTER_API = 2     # router, controller, endpoint 相關
    SERVICE = 3        # service, use_case, handler
    DOMAIN_MODEL = 4   # model, entity, schema
    CONFIG = 5         # config, settings, .env.example
    INFRASTRUCTURE = 6  # adapter, repository, client
    UTILITY = 7        # utils, helpers, common
    TEST = 8           # test_, _test, spec
    DOCS = 9           # README, .md, .rst
    OTHER = 10         # 其他所有檔案


#: 用於判斷入口檔的檔名集合。
_ENTRY_POINT_NAMES = frozenset({
    "main.py", "app.py", "index.ts", "index.js", "index.tsx",
    "manage.py", "server.py", "server.ts", "server.js",
    "wsgi.py", "asgi.py",
})

#: 用於判斷檔案類別的路徑關鍵字對應表（正則模式 → 優先級）。
_PATH_PRIORITY_PATTERNS: list[tuple[re.Pattern[str], FilePriority]] = [
    (re.compile(r"(router|controller|endpoint|view|route)", re.IGNORECASE), FilePriority.ROUTER_API),
    (re.compile(r"(service|use_case|usecase|handler|interactor)", re.IGNORECASE), FilePriority.SERVICE),
    (re.compile(r"(model|entity|schema|domain)", re.IGNORECASE), FilePriority.DOMAIN_MODEL),
    (re.compile(r"(config|setting|\.env)", re.IGNORECASE), FilePriority.CONFIG),
    (re.compile(r"(adapter|repository|client|infra)", re.IGNORECASE), FilePriority.INFRASTRUCTURE),
    (re.compile(r"(util|helper|common|lib)", re.IGNORECASE), FilePriority.UTILITY),
    (re.compile(r"(test_|_test\.|spec\.|__test)", re.IGNORECASE), FilePriority.TEST),
    (re.compile(r"(readme|\.md$|\.rst$)", re.IGNORECASE), FilePriority.DOCS),
]


def classify_file_priority(relative_path: str) -> FilePriority:
    """根據檔案路徑推斷其重要性等級。

    Args:
        relative_path: 相對於專案根目錄的路徑字串。

    Returns:
        該檔案的 :class:`FilePriority` 等級。
    """
    basename = Path(relative_path).name

    if basename in _ENTRY_POINT_NAMES:
        return FilePriority.ENTRY_POINT

    for pattern, priority in _PATH_PRIORITY_PATTERNS:
        if pattern.search(relative_path):
            return priority

    return FilePriority.OTHER


# ---------------------------------------------------------------------------
# AST Skeleton Extraction
# ---------------------------------------------------------------------------


def extract_python_skeleton(source_code: str) -> Optional[str]:
    """從 Python 原始碼中提取 AST Skeleton。

    僅保留：
    - import 語句
    - 類別定義（含 Docstring）
    - 函式 / 方法簽章（含 Docstring）
    - 全域變數賦值

    移除所有函式 / 方法的實作本體，以大幅壓縮 Token 量。

    Args:
        source_code: 完整的 Python 原始碼字串。

    Returns:
        壓縮後的 Skeleton 字串，若解析失敗則回傳 ``None``。
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        logger.debug("AST 解析失敗，跳過 Skeleton 提取。")
        return None

    lines: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(ast.unparse(node))

        elif isinstance(node, ast.ClassDef):
            _render_class_skeleton(node, lines, indent=0)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _render_function_skeleton(node, lines, indent=0)

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            lines.append(ast.unparse(node))

    if not lines:
        return None

    return "\n".join(lines)


def _render_function_skeleton(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    indent: int,
) -> None:
    """將函式節點渲染為僅含簽章與 Docstring 的 Skeleton。

    Args:
        node: AST 函式定義節點。
        lines: 收集輸出行的列表。
        indent: 當前縮排層級。
    """
    prefix = "    " * indent
    async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""

    # 函式簽章
    decorators = "".join(
        f"{prefix}@{ast.unparse(d)}\n" for d in node.decorator_list
    )
    signature = f"{prefix}{async_prefix}def {node.name}({ast.unparse(node.args)})"
    if node.returns:
        signature += f" -> {ast.unparse(node.returns)}"
    signature += ":"

    lines.append(f"{decorators}{signature}")

    # Docstring
    docstring = ast.get_docstring(node)
    if docstring:
        inner_prefix = "    " * (indent + 1)
        lines.append(f'{inner_prefix}"""')
        for doc_line in docstring.split("\n"):
            lines.append(f"{inner_prefix}{doc_line}")
        lines.append(f'{inner_prefix}"""')

    lines.append(f"{'    ' * (indent + 1)}...")
    lines.append("")


def _render_class_skeleton(
    node: ast.ClassDef,
    lines: list[str],
    indent: int,
) -> None:
    """將類別節點渲染為含方法簽章的 Skeleton。

    Args:
        node: AST 類別定義節點。
        lines: 收集輸出行的列表。
        indent: 當前縮排層級。
    """
    prefix = "    " * indent

    # 類別定義行
    decorators = "".join(
        f"{prefix}@{ast.unparse(d)}\n" for d in node.decorator_list
    )
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    class_line = f"{prefix}class {node.name}"
    if bases:
        class_line += f"({bases})"
    class_line += ":"

    lines.append(f"{decorators}{class_line}")

    # 類別 Docstring
    docstring = ast.get_docstring(node)
    if docstring:
        inner_prefix = "    " * (indent + 1)
        lines.append(f'{inner_prefix}"""')
        for doc_line in docstring.split("\n"):
            lines.append(f"{inner_prefix}{doc_line}")
        lines.append(f'{inner_prefix}"""')

    # 類別屬性與方法
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _render_function_skeleton(child, lines, indent=indent + 1)
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            lines.append(f"{'    ' * (indent + 1)}{ast.unparse(child)}")

    lines.append("")


def extract_js_ts_skeleton(source_code: str) -> Optional[str]:
    """從 JavaScript / TypeScript 原始碼中提取函式簽章與 export 語句。

    使用正則表達式擷取，非完整 AST 解析，涵蓋範圍：
    - import / export 語句
    - function / class / const 宣告（僅首行）
    - 箭頭函式宣告（僅首行）

    Args:
        source_code: 完整的 JS/TS 原始碼字串。

    Returns:
        壓縮後的 Skeleton 字串，若無有效擷取則回傳 ``None``。
    """
    patterns = [
        # import / export 語句
        re.compile(r"^(?:import|export)\s+.*$", re.MULTILINE),
        # function 宣告（含 async）
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)[^{]*", re.MULTILINE),
        # class 宣告
        re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+\w+[^{]*", re.MULTILINE),
        # const / let / var 箭頭函式或物件
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+\w+\s*(?::\s*[^=]+)?\s*=", re.MULTILINE),
        # interface / type 宣告
        re.compile(r"^(?:export\s+)?(?:interface|type)\s+\w+[^{]*", re.MULTILINE),
    ]

    extracted_lines: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(source_code):
            line = match.group(0).strip()
            if line and line not in extracted_lines:
                extracted_lines.append(line)

    if not extracted_lines:
        return None

    return "\n".join(extracted_lines)


# ---------------------------------------------------------------------------
# ContentCompressor 主類別
# ---------------------------------------------------------------------------

#: Token 估算常數：基於字元數的探測法，對 Gemini 而言較精準 (1 Token 約 3.5 字元)。
_CHARS_PER_TOKEN: float = 3.5


def _estimate_tokens(text: str) -> int:
    """估算文字的 Token 數量。

    Args:
        text: 欲估算的文字。

    Returns:
        估算的 Token 數量。
    """
    return int(len(text) / _CHARS_PER_TOKEN)


@dataclass
class CompressionResult:
    """壓縮執行結果的資料容器。

    Attributes:
        files: 壓縮後的檔案列表。
        original_token_estimate: 壓縮前的估算 Token 總量。
        compressed_token_estimate: 壓縮後的估算 Token 總量。
        strategies_applied: 已套用的壓縮策略名稱列表。
        files_skeleton_extracted: AST Skeleton 提取的檔案數。
        files_dropped: 被裁減的檔案數。
        files_truncated: 被強制截斷的檔案數。
    """

    files: List[ProjectFile] = field(default_factory=list)
    original_token_estimate: int = 0
    compressed_token_estimate: int = 0
    strategies_applied: List[str] = field(default_factory=list)
    files_skeleton_extracted: int = 0
    files_dropped: int = 0
    files_truncated: int = 0


class ContentCompressor:
    """多策略漸進式內容壓縮器。

    依序套用 AST Skeleton、優先級裁減、強制截斷三種策略，
    將檔案列表的總 Token 量壓縮至指定的 ``token_budget`` 以內。

    Args:
        token_budget: 目標 Token 上限，預設 100,000。
        per_file_limit: 單檔 Token 上限（截斷用），預設 1,500。

    Example::

        compressor = ContentCompressor(token_budget=100_000)
        result = compressor.compress(project_files)
        print(result.compressed_token_estimate)
    """

    def __init__(
        self,
        token_budget: int = 100_000,
        per_file_limit: int = 1_500,
    ) -> None:
        self._token_budget = token_budget
        self._per_file_limit = per_file_limit

    def compress(self, files: List[ProjectFile]) -> CompressionResult:
        """執行漸進式壓縮。

        策略執行順序：
            1. AST Skeleton Extraction
            2. Priority-Based File Selection（裁減低優先級檔案）
            3. Aggressive Truncation（截斷剩餘超限檔案）

        Args:
            files: 原始的 :class:`ProjectFile` 列表。

        Returns:
            :class:`CompressionResult` 包含壓縮後的檔案與統計資訊。
        """
        result = CompressionResult()
        result.original_token_estimate = sum(
            _estimate_tokens(f.content) for f in files
        )

        logger.info(
            "[ContentCompressor] 原始 Token 估算：%d，預算：%d",
            result.original_token_estimate,
            self._token_budget,
        )

        # 若原始量已在預算內，直接回傳
        if result.original_token_estimate <= self._token_budget:
            result.files = list(files)
            result.compressed_token_estimate = result.original_token_estimate
            logger.info("[ContentCompressor] 未超過預算，跳過壓縮。")
            return result

        # ── 策略 1：AST Skeleton Extraction ────────────────────────────────
        working_files = self._apply_skeleton_extraction(files, result)
        current_tokens = sum(_estimate_tokens(f.content) for f in working_files)

        if current_tokens <= self._token_budget:
            result.files = working_files
            result.compressed_token_estimate = current_tokens
            return result

        # ── 策略 2：Priority-Based File Selection ─────────────────────────
        working_files = self._apply_priority_selection(working_files, result)
        current_tokens = sum(_estimate_tokens(f.content) for f in working_files)

        if current_tokens <= self._token_budget:
            result.files = working_files
            result.compressed_token_estimate = current_tokens
            return result

        # ── 策略 3：Aggressive Truncation ──────────────────────────────────
        working_files = self._apply_truncation(working_files, result)
        result.files = working_files
        result.compressed_token_estimate = sum(
            _estimate_tokens(f.content) for f in working_files
        )

        logger.info(
            "[ContentCompressor] 壓縮完成：%d → %d Token（策略：%s）",
            result.original_token_estimate,
            result.compressed_token_estimate,
            ", ".join(result.strategies_applied),
        )

        return result

    def _apply_skeleton_extraction(
        self,
        files: List[ProjectFile],
        result: CompressionResult,
    ) -> List[ProjectFile]:
        """策略 1：對支援的語言執行 AST Skeleton 提取。

        Args:
            files: 輸入檔案列表。
            result: 寫入統計資訊的 :class:`CompressionResult`。

        Returns:
            處理後的檔案列表（部分檔案內容已被替換為 Skeleton）。
        """
        result.strategies_applied.append("AST Skeleton")
        output: List[ProjectFile] = []

        for f in files:
            skeleton: Optional[str] = None

            if f.language == "python":
                skeleton = extract_python_skeleton(f.content)
            elif f.language in ("javascript", "typescript", "tsx", "jsx"):
                skeleton = extract_js_ts_skeleton(f.content)

            if skeleton and _estimate_tokens(skeleton) < _estimate_tokens(f.content):
                result.files_skeleton_extracted += 1
                output.append(ProjectFile(
                    relative_path=f.relative_path,
                    language=f.language,
                    content=f"# [AST Skeleton] 原始 {_estimate_tokens(f.content)} Token → 壓縮後 {_estimate_tokens(skeleton)} Token\n{skeleton}",
                    is_truncated=True,
                    token_estimate=_estimate_tokens(skeleton),
                ))
            else:
                output.append(f)

        logger.info(
            "[ContentCompressor] AST Skeleton 提取：%d 個檔案",
            result.files_skeleton_extracted,
        )
        return output

    def _apply_priority_selection(
        self,
        files: List[ProjectFile],
        result: CompressionResult,
    ) -> List[ProjectFile]:
        """策略 2：依優先級排序，從低優先級開始裁減直到低於預算。

        Args:
            files: 輸入檔案列表。
            result: 寫入統計資訊的 :class:`CompressionResult`。

        Returns:
            裁減後的檔案列表。
        """
        result.strategies_applied.append("Priority Selection")

        # 按優先級排序（重要的在前）
        sorted_files = sorted(
            files,
            key=lambda f: classify_file_priority(f.relative_path),
        )

        selected: List[ProjectFile] = []
        accumulated_tokens = 0

        for f in sorted_files:
            f_tokens = _estimate_tokens(f.content)
            if accumulated_tokens + f_tokens <= self._token_budget:
                selected.append(f)
                accumulated_tokens += f_tokens
            else:
                result.files_dropped += 1
                logger.debug(
                    "[ContentCompressor] 裁減檔案：%s（優先級 %s，%d Token）",
                    f.relative_path,
                    classify_file_priority(f.relative_path).name,
                    f_tokens,
                )

        logger.info(
            "[ContentCompressor] 優先級裁減：移除 %d 個低優先級檔案",
            result.files_dropped,
        )
        return selected

    def _apply_truncation(
        self,
        files: List[ProjectFile],
        result: CompressionResult,
    ) -> List[ProjectFile]:
        """策略 3：對每個檔案強制截斷至 per_file_limit。

        Args:
            files: 輸入檔案列表。
            result: 寫入統計資訊的 :class:`CompressionResult`。

        Returns:
            截斷後的檔案列表。
        """
        result.strategies_applied.append("Aggressive Truncation")
        output: List[ProjectFile] = []

        for f in files:
            f_tokens = _estimate_tokens(f.content)
            if f_tokens > self._per_file_limit:
                target_chars = int(self._per_file_limit * _CHARS_PER_TOKEN)
                truncated_content = f.content[:target_chars]
                truncated_content += "\n\n<!-- [Content Truncated] 強制截斷 -->"
                result.files_truncated += 1
                output.append(ProjectFile(
                    relative_path=f.relative_path,
                    language=f.language,
                    content=truncated_content,
                    is_truncated=True,
                    token_estimate=self._per_file_limit,
                ))
            else:
                output.append(f)

        logger.info(
            "[ContentCompressor] 強制截斷：%d 個檔案",
            result.files_truncated,
        )
        return output
