"""Tools package for dynamic capability-based routing and tool registry.

NOT ENABLED. This package is an LLM tool-calling interface. It is not consumed
by the Agent main loop, which builds and executes Abaqus Action scripts. A tool
registered here is not evidence that the product can call it. Do not describe
this registry as part of the running solve path, and do not delete it merely
because that path has no import.
"""

from .registry import (
    RiskLevel,
    ToolMetadata,
    ToolRegistry,
    build_default_cae_tool_registry,
)
from .router import (
    DynamicRouteResult,
    DynamicToolRouter,
)

__all__ = [
    "RiskLevel",
    "ToolMetadata",
    "ToolRegistry",
    "build_default_cae_tool_registry",
    "DynamicRouteResult",
    "DynamicToolRouter",
]
