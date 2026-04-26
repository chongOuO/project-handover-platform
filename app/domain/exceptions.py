"""專案交接平台的 Domain 層自定義例外 (Exceptions)。

所有與業務邏輯相關的錯誤都繼承自 ``AppBaseException``，
以便 FastAPI 的例外處理器 (Exception Handler) 能夠統一捕捉
並將其格式化為標準的回應格式。
"""

from typing import Optional


class AppBaseException(Exception):
    """所有應用程式等級例外的基底類別 (Base class)。

    Attributes:
        error_code: 供機器讀取的錯誤識別碼 (例如：``"INVALID_ZIP"``)。
        message: 供人類閱讀的錯誤描述。
        status_code: 回傳給客戶端的對應 HTTP 狀態碼。
        detail: 選擇性的額外上下文 (例如：堆疊追蹤、欄位名稱等)。
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
        detail: Optional[str] = None,
    ) -> None:
        """初始化基底例外。

        Args:
            error_code: 機器可讀的錯誤代碼字串。
            message: 人類可讀的錯誤訊息。
            status_code: 回應的 HTTP 狀態碼 (預設為 400)。
            detail: 選擇性的額外上下文或追蹤資訊。
        """
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# 具體的例外類別 (Concrete exceptions)
# ---------------------------------------------------------------------------


class InvalidZipFileError(AppBaseException):
    """當上傳的檔案不是有效的 ZIP 壓縮檔時拋出。"""

    def __init__(self, detail: Optional[str] = None) -> None:
        """初始化 InvalidZipFileError。

        Args:
            detail: 選擇性的底層錯誤細節 (例如：``zipfile.BadZipFile`` 的原始訊息)。
        """
        super().__init__(
            error_code="INVALID_ZIP_FILE",
            message="上傳的檔案不是一個有效的 ZIP 壓縮檔。",
            status_code=422,
            detail=detail,
        )


class FileSizeLimitExceededError(AppBaseException):
    """當上傳的 ZIP 檔案超過允許的大小限制時拋出。"""

    def __init__(self, max_mb: int = 50, detail: Optional[str] = None) -> None:
        """初始化 FileSizeLimitExceededError。

        Args:
            max_mb: 允許的最大檔案大小 (單位：MB)。
            detail: 選擇性的額外上下文。
        """
        super().__init__(
            error_code="FILE_SIZE_LIMIT_EXCEEDED",
            message=f"上傳的檔案已超過最大允許大小限制 ({max_mb} MB)。",
            status_code=413,
            detail=detail,
        )


class EmptyProjectError(AppBaseException):
    """當經過智慧過濾後，專案內找不到任何程式碼檔案時拋出。"""

    def __init__(self, detail: Optional[str] = None) -> None:
        """初始化 EmptyProjectError。

        Args:
            detail: 選擇性的額外上下文。
        """
        super().__init__(
            error_code="EMPTY_PROJECT",
            message=(
                "套用智慧過濾後，在上傳的壓縮檔內找不到任何程式碼檔案。"
                "請確認 ZIP 檔案內包含實際的原始碼檔案。"
            ),
            status_code=422,
            detail=detail,
        )


class UnsupportedFileTypeError(AppBaseException):
    """當上傳的檔案格式不支援 (非 ZIP) 時拋出。"""

    def __init__(self, filename: str, detail: Optional[str] = None) -> None:
        """初始化 UnsupportedFileTypeError。

        Args:
            filename: 被拒絕的檔案名稱。
            detail: 選擇性的額外上下文。
        """
        super().__init__(
            error_code="UNSUPPORTED_FILE_TYPE",
            message=f"不支援檔案 '{filename}' 的格式，請上傳 .zip 壓縮檔。",
            status_code=415,
            detail=detail,
        )


class MarkdownSourceNotFoundError(AppBaseException):
    """當指定的 Markdown 來源檔案不存在或無法讀取時拋出。"""

    def __init__(self, path: str, detail: Optional[str] = None) -> None:
        """初始化 MarkdownSourceNotFoundError。

        Args:
            path: 找不到的 Markdown 文件路徑字串。
            detail: 選擇性的底層錯誤細節。
        """
        super().__init__(
            error_code="MARKDOWN_SOURCE_NOT_FOUND",
            message=f"找不到指定的 Markdown 來源檔案：'{path}'。",
            status_code=404,
            detail=detail,
        )


class LLMCallError(AppBaseException):
    """當呼叫 LLM API（如 Google Gemini）失敗或回應異常時拋出。"""

    def __init__(self, detail: Optional[str] = None) -> None:
        """初始化 LLMCallError。

        Args:
            detail: 選擇性的底層 LLM 錯誤訊息或 API 異常資訊。
        """
        super().__init__(
            error_code="LLM_CALL_ERROR",
            message="呼叫 AI 語言模型 API 時發生錯誤，請確認 API Key 設定或稍後再試。",
            status_code=502,
            detail=detail,
        )


class SessionNotFoundError(AppBaseException):
    """當查詢的 Q&A Session 不存在時拋出。

    可能原因：Session ID 錯誤，或 Session 從未建立。
    """

    def __init__(self, session_id: str, detail: Optional[str] = None) -> None:
        """初始化 SessionNotFoundError。

        Args:
            session_id: 查詢的 Session 識別碼。
            detail: 選擇性的額外上下文。
        """
        super().__init__(
            error_code="SESSION_NOT_FOUND",
            message=f"找不到 Session '{session_id}'，可能已過期或從未建立。",
            status_code=404,
            detail=detail,
        )


class SessionExpiredError(AppBaseException):
    """當查詢的 Q&A Session 已過期時拋出。

    Session 預設有效期限為 30 分鐘，過期後需重新上傳專案建立新的 Session。
    """

    def __init__(self, session_id: str, detail: Optional[str] = None) -> None:
        """初始化 SessionExpiredError。

        Args:
            session_id: 已過期的 Session 識別碼。
            detail: 選擇性的額外上下文。
        """
        super().__init__(
            error_code="SESSION_EXPIRED",
            message=f"Session '{session_id}' 已過期，請重新上傳專案建立新的 Session。",
            status_code=410,
            detail=detail,
        )
