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
    def check(tool: Tool) -> bool:
        # P1 Policy: Only allow tools in the ALLOWED_TIERS list (Tier 0)
        if tool.tier not in settings.ALLOWED_TIERS:
            audit.log_event("tool.denied", {"tool": tool.name, "tier": tool.tier, "reason": "tier_not_allowed"})
            return False
        
        audit.log_event("tool.allowed", {"tool": tool.name, "tier": tool.tier})
        return True

# Singleton instances
registry = ToolRegistry()
gate = PermissionGate()