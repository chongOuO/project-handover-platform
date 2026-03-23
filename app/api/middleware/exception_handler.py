"""專案交接平台專屬的 FastAPI 全域異常與錯誤處理中介層 (Middleware)。

將自訂異常例外與 FastAPI 原生流程做綁定：將 :class:`~app.domain.exceptions.AppBaseException`
的客製化邏輯、及一般未被程式語言自行攔截處理的系統級 :class:`Exception`，給予統一標準格式的
JSON 返回回應，以達成程式執行失敗後的對外資料安全與介面一致性。
"""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import AppBaseException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """初始化並將所有異常攔截邏輯掛載綁定至指定的 FastAPI *app* 給予保護。

    建議此方法應該在專案系統服務開始啟動的最初流程時即被初始化。
    範例用法：

        from app.api.middleware.exception_handler import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)

    Args:
        app: 將要受到監視與異常攔截保護機制的 FastAPI 核心實例物件。
    """

    @app.exception_handler(AppBaseException)
    async def handle_app_exception(
        request: Request, exc: AppBaseException
    ) -> JSONResponse:
        """專職處理 Domain 領域層級拋出的各種自定義異常機制。

        任何由 :class:`~app.domain.exceptions.AppBaseException` 為基底衍生的類別報錯，
        將會由這裡被格式化成一致架構之標準回傳，當中將包括物件本身夾帶之狀態屬性：包括
        ``status_code``, ``error_code``, ``message``, 還有具體額外資訊 ``detail``。

        Args:
            request: 導致產生異常進入之 HTTP 原始存取請求 (FastAPI 標準固定參數所需)。
            exc: 從程式運行時實際引發回拋的應用領域錯誤異常本身。

        Returns:
            回傳一個已經妥善轉換過並準備被外界客戶端接收之
            :class:`~fastapi.responses.JSONResponse` HTTP json 返回包裹。
        """
        logger.warning(
            "Application exception [%s]: %s — detail=%s",
            exc.error_code,
            exc.message,
            exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """作為系統最終屏障，對接未曾受預見或控制的異常報錯。

        任何一般非預期性漏接的底層等級 :class:`Exception` 若觸發異常至最外圍系統層界定，將被此全域函式捕捉以進行內部封裝；統一以 500 error 不洩露程式內在代碼具體堆疊或暴露實作資訊的情境下，提供客戶端通用的友善字面訊息提醒。

        Args:
            request: 引發此失誤狀況存取的 Web 原請求內容 (FastAPI 開發要求參數)。
            exc: 所有未受到特例自訂保護所引起的失控系統級異常。

        Returns:
            以通用內部無法提供服務錯誤的 JSON 包裝結構 500 status_code，作為回應前端之
            :class:`~fastapi.responses.JSONResponse`。
        """
        logger.error(
            "Unhandled exception on %s %s:\n%s",
            request.method,
            request.url,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "發生了非預期的內部伺服器錯誤 (An unexpected error occurred)，請稍後再試。",
                "detail": None,
            },
        )
