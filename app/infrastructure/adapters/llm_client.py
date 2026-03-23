"""AI 語言模型的基礎設施適配器 (Adapter)。

將 LangChain Google Generative AI（Gemini）的呼叫細節封裝於此，
讓上層的 LangGraph 節點不需直接依賴任何特定的 LLM SDK，
僅需透過 ``LLMClient.complete()`` 即可取得回應文字。

環境變數需求：
    - ``GOOGLE_API_KEY``: Google Gemini API 金鑰。
    - ``LLM_MODEL_NAME``: (選填) 模型名稱，預設為 ``gemini-2.5-flash``。
"""

from __future__ import annotations

import logging
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from app.domain.exceptions import LLMCallError

logger = logging.getLogger(__name__)

#: 若未透過環境變數指定時使用的預設 Gemini 模型。
DEFAULT_MODEL_NAME: str = "gemini-2.5-flash"


class LLMClient:
    """封裝 Google Gemini LLM API 呼叫的基礎設施適配器。

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
            self._llm = ChatGoogleGenerativeAI(
                model=self._model_name,
                google_api_key=api_key,
                temperature=0.3,  # 技術文件需要低溫度確保輸出穩定
            )
            logger.info("LLMClient 已初始化，使用模型：%s", self._model_name)
        return self._llm

    async def complete(self, prompt: str) -> str:
        """非同步向 LLM 發送提示並取得回應文字。

        Args:
            prompt: 要傳送給語言模型的完整提示字串。

        Returns:
            LLM 回應的純文字內容字串。

        Raises:
            LLMCallError: 當 API 呼叫過程中發生任何網路或服務異常時。
        """
        llm = self._get_llm()
        logger.info("發送 LLM 請求，Prompt 長度：%d 字元", len(prompt))

        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = str(response.content).strip()
            logger.info("收到 LLM 回應，回應長度：%d 字元", len(result))
            return result
        except Exception as exc:
            logger.error("LLM API 呼叫失敗：%s", exc, exc_info=True)
            raise LLMCallError(detail=str(exc)) from exc
