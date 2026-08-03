"""HTTP transport for the chatbot.

Routes, session identity, serialization. That is the whole job. There is no
business logic here, no arithmetic, and no prompt text — every reply below is
produced by ``chat.Session`` and passed through untouched, and every number in
one came from ``calculators/``.

Run it:

    uvicorn app:app --reload     # or: python app.py
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chat import Session
from chat.llm import get_llm_or_unconfigured

UI_DIRECTORY = Path(__file__).parent / "ui"

app = FastAPI(title="Finance chatbot", version="1.0")

# In process memory, by design. The spec excludes persistence and accounts, so
# a conversation lives as long as the server does and no longer.
_SESSIONS: dict[str, Session] = {}

# One provider, built once. A missing key yields a placeholder that explains
# itself on first use rather than stopping the server from starting.
_LLM = get_llm_or_unconfigured()


class NewSessionReply(BaseModel):
    session_id: str
    reply: str


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str


class ChatReply(BaseModel):
    session_id: str
    reply: str


@app.post("/session", response_model=NewSessionReply)
def open_session() -> NewSessionReply:
    """Start a conversation and return its opening message."""
    session_id = uuid4().hex
    session = Session(llm=_LLM)
    _SESSIONS[session_id] = session
    return NewSessionReply(session_id=session_id, reply=session.greeting())


@app.post("/chat", response_model=ChatReply)
def chat(request: ChatRequest) -> ChatReply:
    """Hand one message to its session and return the reply verbatim."""
    session = _SESSIONS.get(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")

    return ChatReply(session_id=request.session_id, reply=session.handle(request.message))


# Mounted last so it cannot shadow the two routes above. ``html=True`` serves
# ui/index.html at "/".
app.mount("/", StaticFiles(directory=UI_DIRECTORY, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
