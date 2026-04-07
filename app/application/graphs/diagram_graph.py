"""Diagram Graph：分析並生成 Mermaid.js 架構圖的 LangGraph 管線。

本圖表生成管線由三個核心階段所組成：
1. **detect_db_node**（純函式判斷）：偵測是否存在 ORM / Schema 等字眼，決定後續路由。
2. **generate_architecture_node**（LLM 生成）：必定執行，生成總體系統架構圖 (graph TD)。
3. **generate_er_node**（LLM 生成）：依據是否具備資料庫，決定是否額外生成資料庫關聯表 (ER Diagram)。
4. **validate_diagram_node**（LLM 生成）：檢驗生成的 Mermaid 語法，確保沒有不合法字元。
"""

from __future__ import annotations

import logging
from typing import Optional
from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from app.application.graphs.diagram_nodes.detect_db_node import detect_db_node
from app.application.graphs.diagram_nodes.generate_architecture_node import generate_architecture_node
from app.application.graphs.diagram_nodes.generate_er_node import generate_er_node
from app.application.graphs.diagram_nodes.validate_diagram_node import validate_diagram_node
from app.application.graphs.diagram_state import DiagramGraphState

logger = logging.getLogger(__name__)


def _route_after_architecture(state: DiagramGraphState) -> str:
    """決定 generate_architecture 之後的走向。"""
    if state.get("has_database", False):
        return "generate_er_node"
    return "validate_diagram_node"


def build_diagram_graph() -> StateGraph:
    """建構並回傳編譯後的 Diagram LangGraph 實例。"""
    builder = StateGraph(DiagramGraphState)

    # 1. 註冊節點
    builder.add_node("detect_db_node", detect_db_node)
    builder.add_node("generate_architecture_node", generate_architecture_node)
    builder.add_node("generate_er_node", generate_er_node)
    builder.add_node("validate_diagram_node", validate_diagram_node)

    # 2. 定義邊界 (Edges)
    builder.set_entry_point("detect_db_node")
    builder.add_edge("detect_db_node", "generate_architecture_node")
    
    # 條件跳轉
    builder.add_conditional_edges(
        "generate_architecture_node",
        _route_after_architecture,
        {
            "generate_er_node": "generate_er_node",
            "validate_diagram_node": "validate_diagram_node"
        }
    )

    # ER 圖產生後也進入驗證節點
    builder.add_edge("generate_er_node", "validate_diagram_node")
    builder.add_edge("validate_diagram_node", END)

    return builder.compile()
