"""Live LLM client package.

NOT ENABLED ON THE SOLVE PATH. The engineering solve path compiles typed
actions; it does not call this client to authorize a report or select a solver.
Keep the client importable for its own tests. Do not describe a successful
import as evidence that a live model participated in a solve.
"""

from .client import LiveLLMClient, LiveLLMResponse

__all__ = ["LiveLLMClient", "LiveLLMResponse"]
