"""AI 語言模型的基礎設施適配器 (Adapter)。

將 LangChain Google Generative AI（Gemini）的呼叫細節封裝於此，
讓上層的 LangGraph 節點不需直接依賴任何特定的 LLM SDK，
僅需透過 ``LLMClient.complete()`` 即可取得回應文字。

**速率保護**：內建 ``asyncio.Semaphore`` 限制並行呼叫數為 1，
以及指數退避重試機制（最多 3 次），避免同時觸發 RPM / TPM 限制。

環境變數需求：
    - ``GOOGLE_API_KEY``: Google Gemini API 金鑰。
    - ``LLM_MODEL_NAME``: (選填) 模型名稱，預設為 ``gemini-2.5-flash``。
"""

from __future__ import annotations

import asyncio
import logging
import os

from google.api_core.client_options import ClientOptions
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from app.domain.exceptions import LLMCallError

logger = logging.getLogger(__name__)

#: 若未透過環境變數指定時使用的預設 Gemini 模型。
DEFAULT_MODEL_NAME: str = "gemini-2.5-flash"

#: 最大並行 LLM 呼叫數量（序列化以避免 RPM 衝突）。
MAX_CONCURRENT_CALLS: int = 1

#: 重試次數上限。
MAX_RETRIES: int = 3

#: 指數退避的基底等待秒數（第 N 次重試等待 BASE * 2^N 秒）。
RETRY_BASE_WAIT_SECONDS: float = 30.0

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

# 模組層級的 Semaphore，所有 LLMClient 實例共享同一個並行限制。
_call_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)


def _estimate_prompt_tokens(prompt: str) -> int:
    """粗估 Prompt 的 Token 數量。

    Args:
        prompt: 完整的提示字串。

    Returns:
        估算的 Token 數量。
    """
    return int(len(prompt) / _CHARS_PER_TOKEN)


def _is_retryable_error(exc: Exception) -> bool:
    """判斷例外是否屬於可重試的暫時性錯誤。

    涵蓋 HTTP 429 (Rate Limit) 與 5xx (Server Error) 類型的錯誤。

    Args:
        exc: 捕捉到的例外。

    Returns:
        若為可重試錯誤則回傳 ``True``。
    """
    error_str = str(exc).lower()
    retryable_keywords = [
        "429",
        "rate limit",
        "resource exhausted",
        "quota",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "internal server error",
        "service unavailable",
        "gateway",
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


class LLMClient:
    """封裝 Google Gemini LLM API 呼叫的基礎設施適配器。

    **速率保護機制**：
    - ``asyncio.Semaphore``：限制並行呼叫數為 1，序列化所有 LLM 請求。
    - 指數退避重試：捕捉 429 / 5xx 錯誤，分別等待 30s / 60s / 120s 後重試。
    - Prompt Token 估算日誌：每次呼叫前記錄估算 Token 數，方便排查 TPM 超限。

    採用延遲初始化策略 (Lazy initialization)，在第一次呼叫 ``complete()``
    時才建立真正的 LLM 連線，以避免在模組載入時就因缺少 API Key 而報錯。

    Example::

        client = LLMClient()
        result = await client.complete("請列出 Python 專案的常見依賴管理工具。")
        print(result)

    Attributes:
        _model_name: 使用的語言模型名稱（由環境變數決定）。
        _llm: 實際的 LangChain LLM 實例（延遲建立）。
    """

    def __init__(self) -> None:
        """透過讀取環境變數初始化 LLMClient。"""
        self._model_name: str = os.getenv("LLM_MODEL_NAME", DEFAULT_MODEL_NAME)
        self._base_url: str | None = os.getenv("GEMINI_BASE_URL")
        self._llm: ChatGoogleGenerativeAI | None = None

    def _get_llm(self) -> ChatGoogleGenerativeAI:
        """延遲初始化並取得 LLM 實例。

        Returns:
            已初始化的 :class:`~langchain_google_genai.ChatGoogleGenerativeAI` 實例。

        Raises:
            LLMCallError: 當 ``GOOGLE_API_KEY`` 環境變數未設定時。
        """
        if self._llm is None:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise LLMCallError(
                    detail="環境變數 'GOOGLE_API_KEY' 未設定，無法連線至 Google Gemini。"
                )
            
            kwargs = {}
            if self._base_url:
                kwargs["client_options"] = ClientOptions(api_endpoint=self._base_url)
                kwargs["transport"] = "rest"

            self._llm = ChatGoogleGenerativeAI(
                model=self._model_name,
                google_api_key=api_key,
                temperature=0.3,  # 技術文件需要低溫度確保輸出穩定
                **kwargs
            )
            logger.info("LLMClient 已初始化，使用模型：%s", self._model_name)
        return self._llm

    async def complete(self, prompt: str) -> str:
        """非同步向 LLM 發送提示並取得回應文字。

        內建 Semaphore 並行控制與指數退避重試機制。
        進入 Semaphore 前會記錄等待狀態，方便排查並行瓶頸。

        Args:
            prompt: 要傳送給語言模型的完整提示字串。

        Returns:
            LLM 回應的純文字內容字串。

        Raises:
            LLMCallError: 當 API 呼叫在所有重試嘗試後仍然失敗時。
        """
        estimated_tokens = _estimate_prompt_tokens(prompt)
        logger.info(
            "準備發送 LLM 請求 | Prompt 長度：%d 字元 | 估算 Token：%d",
            len(prompt),
            estimated_tokens,
        )

        # Semaphore 排隊：序列化所有 LLM 呼叫
        logger.debug("等待 Semaphore 取得呼叫權限...")
        async with _call_semaphore:
            return await self._invoke_with_retry(prompt, estimated_tokens)

    async def _invoke_with_retry(
        self,
        prompt: str,
        estimated_tokens: int,
    ) -> str:
        """帶有指數退避重試邏輯的 LLM 呼叫內部方法。

        Args:
            prompt: 完整的提示字串。
            estimated_tokens: 預估的 Token 數量（用於日誌記錄）。

        Returns:
            LLM 回應的純文字內容字串。

        Raises:
            LLMCallError: 當所有重試嘗試均失敗時。
        """
        llm = self._get_llm()
        last_exception: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "LLM 呼叫嘗試 %d/%d | 估算 Token：%d",
                    attempt,
                    MAX_RETRIES,
                    estimated_tokens,
                )
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                result = str(response.content).strip()
                logger.info(
                    "LLM 呼叫成功（第 %d 次嘗試）| 回應長度：%d 字元",
                    attempt,
                    len(result),
                )
                return result

            except Exception as exc:
                last_exception = exc

                if not _is_retryable_error(exc):
                    logger.error(
                        "LLM 呼叫失敗（不可重試）：%s",
                        exc,
                        exc_info=True,
                    )
                    raise LLMCallError(detail=str(exc)) from exc

                if attempt < MAX_RETRIES:
                    wait_seconds = RETRY_BASE_WAIT_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM 呼叫失敗（可重試，第 %d/%d 次）：%s | "
                        "等待 %.0f 秒後重試...",
                        attempt,
                        MAX_RETRIES,
                        exc,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)
                else:
                    logger.error(
                        "LLM 呼叫在 %d 次重試後仍失敗：%s",
                        MAX_RETRIES,
                        exc,
                        exc_info=True,
                    )

        raise LLMCallError(
            detail=f"LLM 呼叫在 {MAX_RETRIES} 次重試後仍失敗：{last_exception}"
        ) from last_exception
