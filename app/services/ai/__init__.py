"""Manager AI Assistant (Phase 6): an LLM-powered analyst restricted to a fixed set of
read-only tools (`tools.py`) that all delegate to the deterministic analytics engine built in
Phase 4/5. See `assistant.py` for the orchestration loop and the guarantees it enforces.
"""

from app.services.ai.assistant import AssistantAnswer, AssistantError, ask_assistant
from app.services.ai.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS

__all__ = ["ask_assistant", "AssistantAnswer", "AssistantError", "TOOL_DEFINITIONS", "TOOL_FUNCTIONS"]
