"""Dockerfile 生成節點 (Generate Dockerfile Node)。

根據偵測到的語言、框架與專案原始碼摘要，委派給 LLM 生成
完整且可直接使用的 Dockerfile。LLM 依據 needs_build_stage 欄位
自行判斷是否採用 multi-stage build 格式。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.graphs.dockerfile_state import DockerfileGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

#: TPM 安全上限（保障單一請求輸入上限）。
_TPM_SAFE_INPUT_LIMIT: int = 90_000

#: Token 估算常數。
_CHARS_PER_TOKEN: float = 3.5

DOCKERFILE_PROMPT_TEMPLATE = """\
你是一位 DevOps 專家。請根據以下軟體專案的程式碼綱要，產出一份完整且可直接使用的 Dockerfile。

已偵測的專案資訊：
- 主要語言：{language}
- 框架：{framework}
- 建議 Base Image：{base_image}
- 是否需要 Multi-stage Build（含編譯步驟）：{needs_build_stage}

Dockerfile 撰寫要求：
1. 僅輸出純 Dockerfile 內容，**不要**使用 Markdown code fence（禁止 ```dockerfile ... ```）。
2. 若 needs_build_stage 為 True，必須使用 multi-stage build（兩個 FROM 指令以上），\
第一個 stage 負責編譯/打包，最後一個 stage 只複製最終產物，以縮小 image 體積。
3. 若 needs_build_stage 為 False，使用單階段即可。
4. 必須包含：FROM、WORKDIR、COPY 依賴描述檔、安裝相依套件、COPY 原始碼、EXPOSE（若有 HTTP 服務）、CMD/ENTRYPOINT。
5. 加入適當的 Build 優化（例如 Python 的 --no-cache-dir、Node 的 npm ci、分層 COPY 以善用 Docker layer cache）。
6. 在關鍵步驟加入簡短的繁體中文行內註解（以 # 開頭），方便使用者理解每個步驟的用途。
7. 若無法判斷服務 Port，預設 EXPOSE 8000。

=== 專案結構與文件內容 ===
{markdown_content}

=== 請在下方直接輸出純 Dockerfile 內容 ===
"""


def _estimate_tokens(text: str) -> int:
    """粗估文字的 Token 數量。"""
    return int(len(text) / _CHARS_PER_TOKEN)


def _emergency_truncate(content: str, token_limit: int) -> str:
    """緊急截斷超長內容以符合 TPM 上限。"""
    target_chars = int(token_limit * _CHARS_PER_TOKEN)
    return content[:target_chars] + "\n\n<!-- [Emergency Truncation] 內容已被截斷以符合 TPM 限制 -->"


def _strip_code_fence(text: str) -> str:
    """清理 LLM 可能誤加的 Markdown code fence。"""
    text = text.strip()
    for prefix in ("```dockerfile", "```Dockerfile", "```docker", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def generate_dockerfile_node(state: DockerfileGraphState, config: Any) -> dict[str, Any]:
    """執行 Dockerfile 生成的 LangGraph 節點。

    依據 detect_language_node 填入的語言/框架資訊與 needs_build_stage 旗標，
    構建 Prompt 並呼叫 LLM 生成 Dockerfile，將結果寫入 ``dockerfile_content``。

    Args:
        state: Dockerfile Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含 ``dockerfile_content`` 更新的字典；若發生錯誤則同時設定 ``error``。
    """
    logger.info("[generate_dockerfile_node] 開始呼叫 LLM 產出 Dockerfile...")

    markdown_content: str = state.get("markdown_content", "")
    language: str = state.get("detected_language", "unknown")
    framework: str | None = state.get("detected_framework")
    base_image: str = state.get("base_image", "debian:bookworm-slim")
    needs_build_stage: bool = state.get("needs_build_stage", False)

    if not markdown_content:
        logger.warning("[generate_dockerfile_node] markdown_content 為空，回傳最小化 Dockerfile。")
        return {
            "dockerfile_content": (
                f"FROM {base_image}\n"
                "WORKDIR /app\n"
                "COPY . .\n"
                "# 警告：未能解析專案結構，此為最小化 Dockerfile，請手動補充安裝與啟動指令。\n"
                'CMD ["sh"]'
            )
        }

    # Token 安全截斷
    token_estimate: int = state.get("content_token_estimate", _estimate_tokens(markdown_content))
    if token_estimate > _TPM_SAFE_INPUT_LIMIT:
        logger.warning(
            "[generate_dockerfile_node] Token 估算 %d 超過上限 %d，執行緊急截斷。",
            token_estimate, _TPM_SAFE_INPUT_LIMIT,
        )
        markdown_content = _emergency_truncate(markdown_content, _TPM_SAFE_INPUT_LIMIT)

    prompt = DOCKERFILE_PROMPT_TEMPLATE.format(
        language=language,
        framework=framework or "未偵測到特定框架",
        base_image=base_image,
        needs_build_stage="是（請使用 multi-stage build）" if needs_build_stage else "否（單階段即可）",
        markdown_content=markdown_content,
    )

    llm = LLMClient()
    try:
        raw_result = await llm.complete(prompt)
        dockerfile_content = _strip_code_fence(raw_result)
        logger.info(
            "[generate_dockerfile_node] 生成完成，Dockerfile 長度: %d 字元。",
            len(dockerfile_content),
        )
        return {"dockerfile_content": dockerfile_content}
    except Exception as exc:
        logger.error("[generate_dockerfile_node] LLM 生成發生錯誤: %s", exc, exc_info=True)
        return {
            "error": str(exc),
            "dockerfile_content": (
                f"FROM {base_image}\n"
                "WORKDIR /app\n"
                "COPY . .\n"
                f"# 錯誤：Dockerfile 生成失敗 — {exc}\n"
                'CMD ["sh"]'
            ),
        }
