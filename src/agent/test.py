from langchain_openai import ChatOpenAI
from trustcall import create_extractor
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Please set OPENAI_API_KEY in .env or env")

OPENAI_MODEL = os.getenv("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise RuntimeError("Please set OPENAI_MODEL in .env or env")

class Candidate(BaseModel):
     id: str
     name: str
     mime_type: str

llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
ex = create_extractor(
     llm,
     tools=[Candidate],
     tool_choice="Candidate"
 )
print("Extractor:", ex)
print("Has invoke?", hasattr(ex, "invoke"))
x=ex.invoke(
     input="Choose the file named report.pdf with id 12345 and mime type application/pdf")
x.get("responses", [])
