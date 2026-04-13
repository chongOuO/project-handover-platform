"""語法驗證與修正節點 (Validate Diagram Node)。

使用嚴格規則 + Chain-of-Thought 兩段式提示，強制 LLM 在修正前條列錯誤，
有效修正 Mermaid graph TD 與 erDiagram 常見的語法錯誤。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.graphs.diagram_state import DiagramGraphState
from app.infrastructure.adapters.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Mermaid 合法型別白名單（erDiagram 只接受這些型別）
# ─────────────────────────────────────────────────────────────────────────────
_ER_VALID_TYPES = {
    "string", "int", "integer", "float", "double", "boolean", "bool",
    "date", "datetime", "timestamp", "time", "bigint", "smallint",
    "decimal", "number", "text", "varchar", "char", "uuid", "json",
    "blob", "bytes", "enum",
}

_ARCHITECTURE_VALIDATE_PROMPT = """\
你是一位 Mermaid.js 語法驗證專家，現在需要嚴格檢查並修正以下 `graph TD` 或 `graph LR` 架構圖的語法。

【修正步驟 - 必須按此順序執行】

**步驟一：先條列所有發現的問題**（用 ISSUE: 開頭列出，若無問題則寫 ISSUE: None）

**步驟二：輸出修正後的純 Mermaid 語法**（用 FIXED: 開頭，後接整段正確語法）

【架構圖語法規則 - 逐條強制檢查】

1. **節點命名**：節點 ID 只能使用英文字母、數字、底線。特殊字元或含空格的名稱必須用方括號 `[" "]` 包裝標籤文字，不可在 ID 本身使用特殊字元。
   - 錯誤：`Frontend(React App<v18>)`
   - 正確：`Frontend["React App (v18)"]`

2. **嚴格禁止以下非法語法（屬於其他圖表類型，graph 完全不支援）**：
   - `note right of ...` / `note left of ...` / `note over ...`（屬於 sequenceDiagram）
   - `participant ...`（屬於 sequenceDiagram）
   - 若發現這些語法，必須將整個 note 區塊（含對應的 `end`）完全刪除。

3. **subgraph/end 配對**：每個 `subgraph` 必須有且只有一個對應的 `end`。note 區塊被刪除後，其原本的 `end` 也要一併刪除，確保 `end` 數量與 `subgraph` 數量完全對應。

4. **連線標籤**：`-- "標籤" -->` 中的標籤若含有任何特殊字元（括號 `()`、斜線 `/`、角括號 `<` `>`），**必須用雙引號包裹整個標籤**。
   - 錯誤：`A -- (Optional) --> B`
   - 正確：`A -- "Optional" --> B`

5. **節點標籤字串引號包裝**：當節點的標籤文字包含空格、括號 `()`、斜線 `/` 等任何特殊字元時，**必須用雙引號將整個標籤內容包裹起來**，以避免與圖表形狀語法衝突。
   - 錯誤：`LG[LoadGenerator (Python/Locust)]`、`SAS[ShoppingAssistant (Optional)]`
   - 正確：`LG["LoadGenerator (Python/Locust)"]`、`SAS["ShoppingAssistant (Optional)"]`

6. **Cylinder（資料庫筒形）節點**：表示資料庫實體時，唯一合法語法是 `id[("label")]`。
   - 錯誤：`DB_Node((["My Database"]))` 或 `DB_Node(("My Database"))`
   - 正確：`DB_Node[("My Database")]`
   - 若發現 `(([...]))` 或 `(("..."))` 形式，統一修正為 `[("...")]`。

7. **`direction` 語法**：`direction` 關鍵字（如 `direction LR`、`direction TD`）只在 `flowchart` 類型合法，**`graph TD` / `graph LR` 的 subgraph 內嚴格禁止**。若發現，必須整行刪除。

8. **subgraph 名稱不可作為節點 ID**：邊線連接（`-->` 或 `---`）的兩端只能是已定義的節點 ID，不可使用帶引號的 subgraph 名稱字串。
   - 錯誤：`"3. Core Microservices" --> OTC`
   - 正確：將相關節點逐一列出或引入代表性節點 ID。

9. **註解格式**：`graph` 圖表中，唯一合法的單行註解是 `%%`，不可使用單個 `%`。
   - 錯誤：`% User Flow`
   - 正確：`%% User Flow`

10. **style 與 classDef**：引用的節點 ID 必須已在圖中定義過。

【待驗證架構圖】

{diagram}

【請嚴格依照「步驟一：ISSUE:...」→「步驟二：FIXED:...」的格式輸出】
"""

_ER_VALIDATE_PROMPT = """\
你是一位 Mermaid.js erDiagram 語法驗證專家，需要嚴格修正以下 ER 圖的語法。

【修正步驟 - 必須按此順序執行】

**步驟一：先條列所有發現的問題**（用 ISSUE: 開頭列出，若無問題則寫 ISSUE: None）

**步驟二：輸出修正後的純 Mermaid 語法**（用 FIXED: 開頭，後接整段正確語法）

【erDiagram 強制規則】

1. **合法欄位型別**：只能使用以下型別（不分大小寫）：
   `string`, `int`, `integer`, `float`, `double`, `boolean`, `bool`, `date`, `datetime`,
   `timestamp`, `time`, `bigint`, `smallint`, `decimal`, `number`, `text`, `varchar`,
   `char`, `uuid`, `json`, `blob`, `bytes`, `enum`
   - ✗ 錯誤：`UUID id PK`、`DateTime created_at`、`Text html`
   - ✓ 正確：`string id PK`、`datetime created_at`、`string html`

2. **欄位屬性**：只能使用 `PK`、`FK`、`UK`（不可組合如 `PK,FK`）。若一欄同時為 PK 與 FK，只保留 `PK`。
   - ✗ 錯誤：`string id PK,FK`
   - ✓ 正確：`string id PK`

3. **關聯語法**：只能使用以下關係符號：
   `||--||`（一對一）、`||--o{`（一對多）、`}o--o{`（多對多）、`||--|{`（一對多必填）
   - 錯誤：`User ||-->  Role`
   - 正確：`User ||--o{ User_Role : "has"`

4. **關聯標籤**：所有關聯必須有標籤，格式：`EntityA 關係符號 EntityB : "標籤"`

5. **避免重複宣告**：中間表（如 `User_Role`）已定義為實體後，不需要再從父表分別連接到子表（避免重複定義多對多）。只需用中間表連接即可。

6. **實體名稱**：不能含有空格或特殊字元，使用 PascalCase。

7. **欄位描述字串**：欄位後的字串（如 FK 描述）格式為 `type name FK "description"`，引號必須配對。

【待驗證 ER 圖】

{diagram}

【請嚴格依照「步驟一：ISSUE:...」→「步驟二：FIXED:...」的格式輸出】
"""


def _extract_fixed_block(llm_output: str, diagram_type: str) -> str:
    """從 LLM Chain-of-Thought 輸出中提取 FIXED: 後的 Mermaid 語法。

    Args:
        llm_output: LLM 回傳的完整文字。
        diagram_type: 'graph' 或 'er'，用於 fallback 判斷。

    Returns:
        提取出的純 Mermaid 語法字串。
    """
    # 嘗試找到 "FIXED:" 標記
    fixed_match = re.search(r"FIXED:\s*\n?(.*)", llm_output, re.DOTALL | re.IGNORECASE)
    if fixed_match:
        result = fixed_match.group(1).strip()
        return _clean_code_fence(result)

    # Fallback：直接找 mermaid 語法開頭
    if diagram_type == "graph":
        graph_match = re.search(r"(graph\s+(?:TD|LR|BT|RL)\s*\n.*)", llm_output, re.DOTALL | re.IGNORECASE)
        if graph_match:
            return _clean_code_fence(graph_match.group(1).strip())
    elif diagram_type == "er":
        er_match = re.search(r"(erDiagram\s*\n.*)", llm_output, re.DOTALL | re.IGNORECASE)
        if er_match:
            return _clean_code_fence(er_match.group(1).strip())

    # 最終 fallback：清理整個輸出
    return _clean_code_fence(llm_output)


def _clean_code_fence(text: str) -> str:
    """清理由 LLM 不小心包裝的 markdown fence，並處理多餘換行。"""
    text = text.strip()
    # 移除開頭的 ```mermaid 或 ```
    if text.startswith("```mermaid"):
        text = text[10:]
    elif text.startswith("```"):
        text = text[3:]
    # 移除結尾的 ```
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _preprocess_er_types(diagram: str) -> str:
    """對 erDiagram 的型別進行快速字串替換修正（在送 LLM 前做一次）。

    Args:
        diagram: 原始 erDiagram 語法。

    Returns:
        初步修正後的語法，型別已標準化。
    """
    # 高頻常見問題：非法型別替換
    type_replacements = {
        r"\bUUID\b": "string",
        r"\bDateTime\b": "datetime",
        r"\bText\b": "string",
        r"\bBoolean\b": "boolean",
        r"\bInteger\b": "int",
        r"\bString\b": "string",
        r"\bFloat\b": "float",
        r"\bDouble\b": "float",
    }
    for pattern, replacement in type_replacements.items():
        diagram = re.sub(pattern, replacement, diagram)

    # 高頻常見問題：PK,FK 改為 PK（只保留第一個）
    diagram = re.sub(r"\b(PK),\s*FK\b", "PK", diagram)
    diagram = re.sub(r"\bFK,\s*(PK)\b", "PK", diagram)

    return diagram


def _preprocess_arch(diagram: str) -> str:
    """對架構圖進行快速規則型前處理，清除 sequenceDiagram 非法語法。

    graph TD/LR 中不允許 `note right of` / `note left of` / `note over` 等語法，
    這些語法屬於 sequenceDiagram。若存在，會造成 `end` 與 `subgraph` 數量不匹配。

    Args:
        diagram: 原始架構圖語法。

    Returns:
        清理後的架構圖語法。
    """
    # 移除 note ... end 區塊（含跨行）
    # 匹配：note right of / note left of / note over，到最近的獨立 `end` 行
    diagram = re.sub(
        r"^[ \t]*note\s+(?:right|left)\s+of\s+\S+.*?^[ \t]*end\b[^\S\r\n]*$",
        "",
        diagram,
        flags=re.MULTILINE | re.DOTALL,
    )
    diagram = re.sub(
        r"^[ \t]*note\s+over\s+.*?^[ \t]*end\b[^\S\r\n]*$",
        "",
        diagram,
        flags=re.MULTILINE | re.DOTALL,
    )
    # 移除單行 note（無 end 配對，某些版本）
    diagram = re.sub(
        r"^[ \t]*note\s+(?:right|left)\s+of\s+.*$",
        "",
        diagram,
        flags=re.MULTILINE,
    )
    # 移除 participant 語法（sequenceDiagram 專用）
    diagram = re.sub(r"^[ \t]*participant\s+.*$", "", diagram, flags=re.MULTILINE)

    # 修正未引號包裹且含括號的邊線標籤：-- (label) --> 或 -- (label) --- 等
    # 錯誤：A -- (Optional) --> B
    # 正確：A -- "Optional" --> B
    diagram = re.sub(
        r'--\s+\(([^)]+)\)\s+(-->|--->|--)',
        r'-- "\1" \2',
        diagram,
    )

    # 修正非法的 cylinder 節點語法
    # 模式一：((["label"])) 雙引號包裹 → [("label")]
    diagram = re.sub(
        r'\(\(\["([^"]+)"\]\)\)',
        r'[("\1")]',
        diagram,
    )
    # 模式二：(("label")) 雙括號雙引號 → [("label")]
    diagram = re.sub(
        r'\(\("([^"]+)"\)\)',
        r'[("\1")]',
        diagram,
    )
    # 模式三：((label)) 無引號雙層括號 → [("label")]
    diagram = re.sub(
        r'\(\(([A-Za-z0-9 _\-\.]+)\)\)',
        r'[("\1")]',
        diagram,
    )

    # 移除 graph subgraph 內非法的 direction 宣告
    # direction 只在 flowchart 類型合法，graph TD/LR 不支援
    diagram = re.sub(
        r"^[ \t]*direction\s+(?:LR|RL|TD|BT)\s*$",
        "",
        diagram,
        flags=re.MULTILINE,
    )

    # 修正單個 % 的非法註解為合法的 %%
    # 錯誤：% User Flow
    # 正確：%% User Flow
    diagram = re.sub(
        r"^[ \t]*(?<!%)%(?!%)(.*)$",
        r"%% \1",
        diagram,
        flags=re.MULTILINE,
    )

    # 移除以帶引號 subgraph 名稱字串作為邊線端點的非法連線
    # 錯誤："3. Core Microservices" --> OTC
    # 這類連線無法安全自動修正，直接刪除整行，讓 LLM 在第二層重新生成
    diagram = re.sub(
        r'^[ \t]*"[^"]+"\s*(?:--|-->|---)[^\n]*$',
        "",
        diagram,
        flags=re.MULTILINE,
    )
    diagram = re.sub(
        r'^[ \t]*\S+\s*(?:--|-->)\s*"[^"]+"\s*$',
        "",
        diagram,
        flags=re.MULTILINE,
    )

    # 修正未引號包裹的節點標籤包含括號問題
    # 若節點採用 ID[...] 的語法，且內部標籤有 (...) 但沒有被雙引號包裝，會導致 Mermaid 解析錯誤
    # 錯誤：LG[LoadGenerator (Python/Locust)] -> 正確：LG["LoadGenerator (Python/Locust)"]
    # [^"\]]* 可以確保裡面沒有引號（若已有引號則不匹配），且在 ] 之前完成匹配
    diagram = re.sub(
        r'([A-Za-z0-9_-]+)\[([^"\]]*\([^"\]]*\)[^"\]]*)\]',
        r'\1["\2"]',
        diagram,
    )

    # 清理連續空行
    diagram = re.sub(r"\n{3,}", "\n\n", diagram)
    return diagram.strip()

async def validate_diagram_node(state: DiagramGraphState, config: Any) -> dict[str, Any]:
    """執行 Mermaid 語法修復與驗證的 LangGraph 節點。

    使用兩段式 Chain-of-Thought 策略讓 LLM 先條列錯誤、再輸出修正結果。
    對 erDiagram 同時執行快速規則型預處理（regex 替換），減少 LLM 的負擔。

    Args:
        state: Diagram Graph 的當前狀態。
        config: LangGraph 環境設定。

    Returns:
        包含修正後圖表語法的更新字典。
    """
    logger.info("[validate_diagram_node] 開始 Mermaid 語法驗證修正...")
    llm = LLMClient()
    updates = {}

    # ── 架構圖驗證 ─────────────────────────────────────────────────────────
    arch_diagram = state.get("architecture_diagram", "")
    if arch_diagram and not arch_diagram.startswith("graph TD\n  Empty[No"):
        # Step 1: 快速 regex 預處理（清除 note 等非法語法）
        arch_preprocessed = _preprocess_arch(arch_diagram)
        if arch_preprocessed != arch_diagram:
            logger.info("[validate_diagram_node] 架構圖已完成快速非法語法清除。")

        # Step 2: 送 LLM 做完整語法驗證
        prompt = _ARCHITECTURE_VALIDATE_PROMPT.replace("{diagram}", arch_preprocessed)
        try:
            raw = await llm.complete(prompt)
            logger.info("[validate_diagram_node] 架構圖 LLM 回傳長度: %d", len(raw))
            fixed = _extract_fixed_block(raw, "graph")
            if fixed:
                updates["architecture_diagram"] = fixed
                logger.info("[validate_diagram_node] 架構圖修正完畢（%d 字元）。", len(fixed))
            else:
                # fallback：至少保留預處理結果
                updates["architecture_diagram"] = arch_preprocessed
                logger.warning("[validate_diagram_node] 架構圖未能提取 FIXED 區塊，使用預處理結果。")
        except Exception as e:
            updates["architecture_diagram"] = arch_preprocessed
            logger.warning("[validate_diagram_node] 架構圖 LLM 修正失敗，使用預處理結果: %s", e)

    # ── ER 圖驗證 ───────────────────────────────────────────────────────────
    er_diagram = state.get("er_diagram", "")
    if er_diagram and not er_diagram.startswith("erDiagram\n  Error {"):
        # Step 1: 先做快速正規表達式修正
        er_preprocessed = _preprocess_er_types(er_diagram)
        if er_preprocessed != er_diagram:
            logger.info("[validate_diagram_node] ER 圖已完成快速型別標準化。")

        # Step 2: 再交給 LLM 做語意與關聯驗證
        prompt = _ER_VALIDATE_PROMPT.replace("{diagram}", er_preprocessed)
        try:
            raw = await llm.complete(prompt)
            logger.info("[validate_diagram_node] ER 圖 LLM 回傳長度: %d", len(raw))
            fixed = _extract_fixed_block(raw, "er")
            if fixed:
                updates["er_diagram"] = fixed
                logger.info("[validate_diagram_node] ER 圖修正完畢（%d 字元）。", len(fixed))
            else:
                # 即使 LLM 提取失敗，至少保存 regex 預處理結果
                updates["er_diagram"] = er_preprocessed
                logger.warning("[validate_diagram_node] ER 圖未能提取 FIXED 區塊，使用預處理結果。")
        except Exception as e:
            # 即使 LLM 失敗，至少保存 regex 預處理結果
            updates["er_diagram"] = er_preprocessed
            logger.warning("[validate_diagram_node] ER 圖 LLM 修正失敗，使用預處理結果: %s", e)

    return updates
