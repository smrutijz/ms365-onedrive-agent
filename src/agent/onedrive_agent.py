from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from typing import List, Optional, Literal
from langchain_openai import ChatOpenAI
from trustcall import create_extractor
from src.clients.oneDriveHelper import GraphClient


import os
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Please set OPENAI_API_KEY in .env or env")

OPENAI_MODEL = os.getenv("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise RuntimeError("Please set OPENAI_MODEL in .env or env")


# -----------------------
# Models
# -----------------------

class Candidate(BaseModel):
    id: str
    name: str
    type: Literal["folder", "file"]
    mime_type: Optional[str]
    parent_reference_path: Optional[str]
    raw: dict

class Decision(BaseModel):
    action: Literal["enter_folder", "select_file", "stop"]
    id: str
    name: str
    reason: str

class DecisionStep(BaseModel):
    attempt: int
    depth: int
    chosen_id: str
    chosen_name: str
    chosen_type: str
    reason: str
    alternatives: List[str]

class FileRelevance(BaseModel):
    score: float
    reason: str
    is_match: bool

class FoundFile(BaseModel):
    id: str
    name: str
    path: str
    relevance: Optional[FileRelevance] = None

class RejectedPath(BaseModel):
    path: str
    file_name: str
    rejection_reason: str

class AgentState(BaseModel):
    user_query: str
    drive_description: Optional[str] = None
    max_attempts: int = 3
    start_item_id: Optional[str] = None
    current_item_id: Optional[str] = None
    current_path: str = ""
    depth: int = 0
    attempt: int = 1
    done: bool = False
    verified: bool = False
    visited_items: List[str] = []
    rejected_paths: List[RejectedPath] = []
    candidates: List[Candidate] = []
    decision_trace: List[DecisionStep] = []
    current_file: Optional[FoundFile] = None

# -----------------------
# Node implementations
# -----------------------
def resolve_start(state: AgentState, config):
    graph_client: GraphClient = config["configurable"]["graph_client"]
    if state.start_item_id:
        return {"current_item_id": state.start_item_id}
    if state.current_path:
        return {"current_item_id": graph_client.get_folder_id_by_path(state.current_path)}
    return {"current_item_id": "root"}


def list_children(state: AgentState, config):
    graph_client: GraphClient = config["configurable"]["graph_client"]

    items = (
        graph_client.list_root()
        if state.current_item_id == "root"
        else graph_client.list_folder(state.current_item_id)
    )

    candidates = []
    for i in items:
        candidates.append(
            Candidate(
                id=i["id"],
                name=i["name"],
                type="folder" if i.get("folder") else "file",
                mime_type=i.get("file", {}).get("mimeType"),
                parent_reference_path=i.get("parentReference", {})
                    .get("path", "")
                    .replace("/drive/root:", ""),
                raw=i
            )
        )

    return {"candidates": candidates}


def build_decision_prompt(state: AgentState) -> str:
    return f"""
You are a file navigation agent exploring a OneDrive folder tree to find the file that best matches the user's search query. Use the folder’s listing and metadata to choose the next action.

### CONTEXT
User search query:
\"{state.user_query}\"

Drive description:
\"{state.drive_description}\"

Current folder path:
\"{state.current_path or '/'}\"

Contents of this folder:
Each item includes both simplified fields and full OneDrive metadata:

{[
    {
        "id": c.id,
        "name": c.name,
        "type": c.type,
        "mime_type": c.mime_type,
        "parent_path": c.parent_reference_path,
        "complete_metadata": c.raw
    }
    for c in state.candidates
]}

### YOUR GOAL
Choose the **single best next action** that will help you find the most relevant file for the user’s query.

### ACTION SETTINGS
You may return one of these actions only:
- **enter_folder**: Dive into a subfolder to continue searching
- **select_file**: Choose a file as the best match
- **stop**: Stop searching because no further action is needed

### OUTPUT FORMAT
Return **STRICT JSON ONLY** with the following keys (no extra text outside the JSON object):

{
  "action": "<enter_folder | select_file | stop>",
  "id": "<ID of the chosen item>",
  "name": "<Name of the chosen item>",
  "reason": "<Justification for your choice>"
}

### GUIDANCE
- If the query matches a file's name, path, or content strongly, use **select_file**.
- If there are subfolders that likely contain better matches, use **enter_folder**.
- If no item seems useful and search should end, use **stop**.
- Provide a concise reason describing why you chose that action in terms of relevance to the query.

Examples of metadata you can consider include:
- Name and file type (e.g., `.pdf`, `.docx`)
- Path segments related to the query
- Content hints in metadata fields (e.g., keywords in file name)

Respond with JSON only.

"""


def decide_next(state: AgentState):
    if not state.candidates:
        return {"done": True}

    llm = ChatOpenAI(model=OPENAI_MODEL, openai_api_key=OPENAI_API_KEY, temperature=0)

    extractor = create_extractor(
        llm,
        tools=[Decision],
        tool_choice="Decision"
    )

    decision: Decision = extractor.invoke(
        input=build_decision_prompt(state)
    ).get("responses", [None])[0]

    if decision is None:
        return {"done": True}

    # Log the decision
    trace = DecisionStep(
        attempt=state.attempt,
        depth=state.depth,
        chosen_id=decision.id,
        chosen_name=decision.name,
        chosen_type="file" if decision.action == "select_file" else "folder",
        reason=decision.reason,
        alternatives=[c.name for c in state.candidates if c.id != decision.id],
    )

    updates = {"decision_trace": state.decision_trace + [trace]}

    # Handle actions
    if decision.action == "select_file":
        updates["current_file"] = FoundFile(
            id=decision.id,
            name=decision.name,
            path=f"{state.current_path}/{decision.name}"
        )
        updates["done"] = True

    elif decision.action == "enter_folder":
        updates.update({
            "current_item_id": decision.id,
            "current_path": f"{state.current_path}/{decision.name}",
            "depth": state.depth + 1
        })

    else:  # stop
        updates["done"] = True

    return updates


def build_relevance_prompt(state: AgentState, content: str) -> str:
    return f"""
You are evaluating whether a file matches the user's search intent. Based on the user's query, file name, path, and content, you will assign a **relevance score**.

User query:
\"{state.user_query}\"

File name:
\"{state.current_file.name}\"

File path:
\"{state.current_file.path}\"

File content (first 2000 characters):
{content[:2000]}

You must return **STRICT JSON ONLY** in this exact format:

{{
  "score": <0.0, 0.5, or 1.0>,
  "reason": "<explanation of your score>",
  "is_match": <true or false>
}}

### SCORING GUIDELINES (interpret these carefully):
Assign one of these three scores based on how well the file matches the query:

1. **1.0 — Highly Relevant**
   • The file clearly contains strong evidence that it fulfills the user's search intent, such as:
     - The query terms appear in the **file name** or **file path**  
       AND the **content** meaningfully discusses or answers the query.  
   • Typical indicators include direct textual matches to key query phrases or highly relevant context.

2. **0.5 — Moderately Relevant**
   • Some signals of relevance exist but are incomplete or only moderately aligned, such as:
     - Query terms appear only in the content (not name/path),  
     - The context relates to the topic but not strongly or fully.

3. **0.0 — Not Relevant**
   • No meaningful evidence of relevance in the file name, path, or content.
   • The content does not answer, mention, or meaningfully relate to the query.

### OUTPUT RULES:
• **score** must be exactly 0.0, 0.5, or 1.0.  
• **is_match** should be `true` if score is **1.0 or 0.5** (moderate or high relevance), otherwise `false`.  
• **reason** should briefly explain which signals you used to determine the score.

Return JSON only — no extra text outside the JSON object.
"""



def download_and_verify(state: AgentState, config):
    graph_client: GraphClient = config["configurable"]["graph_client"]

    if not state.current_file:
        return {}

    # Download file
    file_bytes = graph_client.download_file(state.current_file.id)
    md_text = file_bytes.decode("utf-8", errors="ignore")

    # LLM relevance scoring
    llm = ChatOpenAI(model=OPENAI_MODEL, openai_api_key=OPENAI_API_KEY, temperature=0)

    extractor = create_extractor(
        llm,
        tools=[FileRelevance],
        tool_choice="FileRelevance"
    )

    relevance: FileRelevance = extractor.invoke(
        input=build_relevance_prompt(state, md_text)
    ).get("responses", [None])[0]

    # Fail-safe: if LLM returns nothing
    if relevance is None:
        relevance = FileRelevance(
            score=0.0,
            reason="LLM returned no structured output",
            is_match=False
        )

    # ✅ If file is relevant
    if relevance.is_match:
        return {
            "verified": True,
            "done": True,
            "current_file": state.current_file.model_copy(
                update={"relevance": relevance}
            ),
        }

    # ❌ If file is NOT relevant
    return {
        "verified": False,
        "attempt": state.attempt + 1,
        "current_file": None,
        "rejected_paths": state.rejected_paths + [
            RejectedPath(
                path=state.current_path,
                file_name=state.current_file.name,
                rejection_reason=f"Content mismatch: {relevance.reason}",
            )
        ],
    }


# -----------------------
# Build StateGraph
# -----------------------

def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("resolve_start", resolve_start)
    graph.add_node("list_children", list_children)
    graph.add_node("decide_next", decide_next)
    graph.add_node("download_and_verify", download_and_verify)

    graph.add_edge(START, "resolve_start")
    graph.add_edge("resolve_start", "list_children")
    graph.add_edge("list_children", "decide_next")

    graph.add_conditional_edges(
        "decide_next",
        lambda s: "download_and_verify" if s.done else "list_children",
    )

    graph.add_edge("download_and_verify", END)

    return graph.compile()


# -----------------------
# Run Example
# -----------------------

from src.utils.token_manager import TokenManager
access_token = TokenManager().refresh_access_token()
# access_token = TokenManager().get_access_token()
client = GraphClient(access_token)

initial_state = AgentState(
    user_query="find my test.txt which is within the test folder not in root",
    drive_description="Files organized by Work, Personal, Education"
)

agent_graph = build_agent_graph()
final = agent_graph.invoke(
    initial_state,
    config={
        "configurable": {
            "graph_client": client
        }
    }
)
