from typing import Callable, Dict
from src.config import settings
from src.security.audit import audit

class Tool:
    def __init__(self, name: str, tier: int, handler: Callable):
        self.name = name
        self.tier = tier
        self.handler = handler

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str):
        return self._tools.get(name)

class PermissionGate:
    @staticmethod
    def can_use(tool: Tool) -> bool:
        """Policy check with no side effects, for introspection and prompts."""
        return tool.tier in settings.ALLOWED_TIERS

    @classmethod
    def check(cls, tool: Tool) -> bool:
        """Policy check for an actual invocation. Audited."""
        if not cls.can_use(tool):
            audit.log_event("tool.denied", {"tool": tool.name, "tier": tool.tier, "reason": "tier_not_allowed"})
            return False

        audit.log_event("tool.allowed", {"tool": tool.name, "tier": tool.tier})
        return True

# Singleton instances
registry = ToolRegistry()
gate = PermissionGate()