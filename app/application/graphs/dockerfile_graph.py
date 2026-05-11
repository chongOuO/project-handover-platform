"""Dockerfile 生成 LangGraph 管線建構器。

本管線由四個節點線性串接：

1. **detect_language_node**（純函式）：keyword 掃描偵測語言/框架/DB。
2. **generate_dockerfile_node**（LLM）：依偵測結果生成 Dockerfile。
3. **generate_dockerignore_node**（LLM）：生成 .dockerignore。
4. **generate_compose_node**（LLM）：生成 docker-compose.yml。

設計考量：
    採線性拓撲而非條件分流，原因是四個節點均需固定執行。
    detect_language_node 的偵測結果作為後三個 LLM 節點的 Prompt 輸入，
    形成「純函式分析 → LLM 生成」的兩段式設計，兼顧速度與品質。
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.application.graphs.dockerfile_nodes.detect_language_node import detect_language_node
from app.application.graphs.dockerfile_nodes.generate_compose_node import generate_compose_node
from app.application.graphs.dockerfile_nodes.generate_dockerfile_node import generate_dockerfile_node
from app.application.graphs.dockerfile_nodes.generate_dockerignore_node import generate_dockerignore_node
from app.application.graphs.dockerfile_state import DockerfileGraphState

logger = logging.getLogger(__name__)


def build_dockerfile_graph() -> StateGraph:
    """建構並回傳編譯後的 Dockerfile LangGraph 管線實例。

    Returns:
        已編譯的 :class:`~langgraph.graph.StateGraph` 實例，可直接呼叫 ``ainvoke``。
    """
    builder = StateGraph(DockerfileGraphState)

    # 1. 註冊節點
    builder.add_node("detect_language_node", detect_language_node)
    builder.add_node("generate_dockerfile_node", generate_dockerfile_node)
    builder.add_node("generate_dockerignore_node", generate_dockerignore_node)
    builder.add_node("generate_compose_node", generate_compose_node)

    # 2. 定義線性邊界
    builder.set_entry_point("detect_language_node")
    builder.add_edge("detect_language_node", "generate_dockerfile_node")
    builder.add_edge("generate_dockerfile_node", "generate_dockerignore_node")
    builder.add_edge("generate_dockerignore_node", "generate_compose_node")
    builder.add_edge("generate_compose_node", END)

    logger.info("DockerfileGraph 建構完成（4 個節點線性管線）。")
    return builder.compile()
