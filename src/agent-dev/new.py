import pprint
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from langchain_openai import ChatOpenAI
from trustcall import create_extractor
from src.clients.oneDriveHelper import GraphClient

import os
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

# -----------------------
# MODELS
# -----------------------

class Candidate(BaseModel):
    id: str
    name: str
    type: Literal["folder", "file"]
    mime_type: Optional[str]
    parent_reference_path: Optional[str]
    raw: dict

class Decision(BaseModel):
    action: Literal["enter_folder", "select_file"]
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


# ----------------------------------------------------
# UNION STATE: REDUCERS DEFINE APPEND (UNION) FIELDS
# ----------------------------------------------------
def append_list(old, new):
    return (old or []) + (new or [])

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

    visited_items: List[str] = Field(default_factory=list)
    decision_trace: List[DecisionStep] = Field(default_factory=list)
    rejected_paths: List[RejectedPath] = Field(default_factory=list)

    # REPLACED each step (not union)
    candidates: List[Candidate] = Field(default_factory=list)
    current_file: Optional[FoundFile] = None

    class Config:
        arbitrary_types_allowed = True
        # 👇 union-based reducers
        reducers = {
            "visited_items": append_list,
            "decision_trace": append_list,
            "rejected_paths": append_list,
        }


# -----------------------
# NODE IMPLEMENTATIONS
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

    candidates = [
        Candidate(
            id=i["id"],
            name=i["name"],
            type="folder" if i.get("folder") else "file",
            mime_type=i.get("file", {}).get("mimeType"),
            parent_reference_path=i.get("parentReference", {}).get("path", "").replace("/drive/root:", ""),
            raw=i
        )
        for i in items
    ]

    return {
        "candidates": candidates,
        "visited_items": [state.current_item_id]
    }


def build_decision_prompt(state: AgentState) -> str:
    return f"""
You are a file navigation agent exploring a OneDrive folder tree.

User query:
\"{state.user_query}\"

Current path:
\"{state.current_path or '/'}\"

Items in this folder:
{[
    {
        "id": c.id,
        "name": c.name,
        "type": c.type,
        "mime_type": c.mime_type,
        "parent_path": c.parent_reference_path,
    }
    for c in state.candidates
]}

Return STRICT JSON:
{{
  "action": "<enter_folder|select_file>",
  "id": "<item id>",
  "name": "<item name>",
  "reason": "<why>"
}}
"""


def decide_next(state: AgentState):
    if not state.candidates:
        return {"done": True}

    llm = ChatOpenAI(model=OPENAI_MODEL, openai_api_key=OPENAI_API_KEY, temperature=0)

    extractor = create_extractor(llm, tools=[Decision], tool_choice="Decision")

    decision: Decision = extractor.invoke(
        input=build_decision_prompt(state)
    ).get("responses", [None])[0]

    if decision is None:
        return {"done": True}

    trace = DecisionStep(
        attempt=state.attempt,
        depth=state.depth,
        chosen_id=decision.id,
        chosen_name=decision.name,
        chosen_type="file" if decision.action == "select_file" else "folder",
        reason=decision.reason,
        alternatives=[c.name for c in state.candidates if c.id != decision.id],
    )

    updates = {"decision_trace": [trace]}

    if decision.action == "select_file":
        updates.update({
            "current_file": FoundFile(
                id=decision.id,
                name=decision.name,
                path=f"{state.current_path}/{decision.name}"
            ),
            "done": True,
        })
    else:
        updates.update({
            "current_item_id": decision.id,
            "current_path": f"{state.current_path}/{decision.name}",
            "depth": state.depth + 1,
            "attempt": state.attempt + 1,
            "current_file": None,
            "done": False
        })

    return updates


def build_relevance_prompt(state: AgentState, content: str) -> str:
    return f"""
You are evaluating relevance.

User query: "{state.user_query}"
File name: "{state.current_file.name}"

Content:
{content[:2000]}

Return STRICT JSON:
{{
  "score": 0.0 | 0.5 | 1.0,
  "reason": "...",
  "is_match": true/false
}}
"""


def download_and_verify(state: AgentState, config):
    graph_client: GraphClient = config["configurable"]["graph_client"]

    if not state.current_file:
        return {}

    file_bytes = graph_client.download_file(state.current_file.id)
    md_text = file_bytes.decode("utf-8", errors="ignore")

    llm = ChatOpenAI(model=OPENAI_MODEL, openai_api_key=OPENAI_API_KEY, temperature=0)

    extractor = create_extractor(llm, tools=[FileRelevance], tool_choice="FileRelevance")

    relevance: FileRelevance = extractor.invoke(
        input=build_relevance_prompt(state, md_text)
    ).get("responses", [None])[0]

    if relevance is None:
        relevance = FileRelevance(score=0.0, reason="LLM returned nothing", is_match=False)

    if relevance.is_match:
        return {
            "verified": True,
            "done": True,
            "current_file": state.current_file.model_copy(update={"relevance": relevance})
        }

    return {
        "done": False,
        "verified": False,
        "attempt": state.attempt + 1,
        "current_file": None,
        "rejected_paths": [
            RejectedPath(
                path=state.current_path,
                file_name=state.current_file.name,
                rejection_reason=relevance.reason,
            )
        ],
    }


# -----------------------
# BUILD GRAPH
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
        lambda s: END if s.attempt == s.max_attempts+2 else "download_and_verify" if s.done else "list_children",
    )

    graph.add_edge("download_and_verify", END)

    return graph.compile()


# -----------------------
# RUN EXAMPLE
# -----------------------
from src.utils.token_manager import TokenManager
access_token = TokenManager().get_access_token()
client = GraphClient(access_token)

state = AgentState(
    user_query="find my test.txt, which is within the test folder not in root",
    drive_description="Files organized by Work, Personal, Education"
)

agent_graph = build_agent_graph()
final = agent_graph.invoke(state, config={"configurable": {"graph_client": client}})
# pprint.pprint(final)
import json
def pydantic_encoder(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "dict"):
        return obj.dict()
    else:
        return str(obj)

with open("src/agent/final_state.json", "w") as f:
    json.dump(final, f, indent=4, default=pydantic_encoder)