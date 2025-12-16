from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from typing import List, Optional, Literal
from langchain_openai import ChatOpenAI
from trustcall import create_extractor
from src.clients.graph_api import GraphClient


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

class DecisionStep(BaseModel):
    attempt: int
    depth: int
    chosen_id: str
    chosen_name: str
    chosen_type: str
    reason: str
    alternatives: List[str]

class FoundFile(BaseModel):
    id: str
    name: str
    path: str
    content_md: Optional[str]

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
# resolve_start(state, config)
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

    return {
        "candidates": [
            Candidate(
                id=i["id"],
                name=i["name"],
                type="folder" if i.get("folder") else "file",
                mime_type=i.get("file", {}).get("mimeType"),
                parent_reference_path=i.get("parentReference", {}).get("path").replace("/drive/root:", "") if i.get("parentReference") else None,
            )
            for i in items
        ]
    }


def build_decision_prompt(state: AgentState) -> str:
    return f"""
You are navigating a OneDrive folder tree.

User query: "{state.user_query}"
Drive desc: "{state.drive_description}"

Path: {state.current_path or "/"}
Items: {[c.model_dump() for c in state.candidates]}

Return strict JSON:
{{
  "action": "enter_folder | select_file | stop",
  "id": "...",
  "name": "...",
  "reason": "..."
}}
"""

def decide_next(state: AgentState):
    if not state.candidates:
        return {"done": True}

    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)

    extractor = create_extractor(
        llm,
        tools=[Candidate],
        tool_choice="Candidate"
    )

    if extractor is None or not hasattr(extractor, "invoke"):
        raise RuntimeError("Extractor creation failed")

    result = extractor.invoke(input=build_decision_prompt(state))
    responses = result.get("responses", [])

    if not responses:
        return {"done": True}

    decision = responses[0]
    chosen_id = decision.id
    chosen_name = decision.name
    chosen_type = decision.type

    # Workaround until you add a full Decision schema
    reason = ""
    action = "select_file" if chosen_type == "file" else "enter_folder"

    trace = DecisionStep(
        attempt=state.attempt,
        depth=state.depth,
        chosen_id=chosen_id,
        chosen_name=chosen_name,
        chosen_type=chosen_type,
        reason=reason,
        alternatives=[c.name for c in state.candidates if c.id != chosen_id],
    )

    updates = {"decision_trace": state.decision_trace + [trace]}

    if action == "select_file":
        updates.update({
            "current_file": FoundFile(
                id=chosen_id,
                name=chosen_name,
                path=state.current_path + "/" + chosen_name
            ),
            "done": True
        })
    else:
        updates.update({
            "current_item_id": chosen_id,
            "current_path": state.current_path + "/" + chosen_name,
            "depth": state.depth + 1
        })

    return updates



def download_and_verify(state: AgentState, config):
    graph_client: GraphClient = config["configurable"]["graph_client"]

    if not state.current_file:
        return {}

    file_bytes = graph_client.download_file(state.current_file.id)
    md_text = file_bytes.decode("utf-8", errors="ignore")

    verified = "resume" in md_text.lower()

    if verified:
        return {
            "verified": True,
            "done": True,
            "current_file": state.current_file.copy(
                update={"content_md": md_text}
            ),
        }

    return {
        "verified": False,
        "attempt": state.attempt + 1,
        "current_file": None,
        "rejected_paths": state.rejected_paths
        + [
            RejectedPath(
                path=state.current_path,
                file_name=state.current_file.name,
                rejection_reason="Content mismatch",
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
# access_token = TokenManager().refresh_access_token()
access_token = TokenManager().get_access_token()
client = GraphClient(access_token)

initial_state = AgentState(
    user_query="find my test, which I believe is in txt format",
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
print(final)

# print(final.current_file)
# print([d.dict() for d in final.decision_trace])
