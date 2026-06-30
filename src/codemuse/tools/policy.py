"""根据工具权限域和副作用声明计算工具执行安全策略。"""
from __future__ import annotations

from dataclasses import dataclass, field

from codemuse.domain.tools import ToolSpec

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


@dataclass
class ToolPolicyDecision:
    """记录工具安全策略的动作、原因和附加详情。"""
    action: str
    reason: str = ""
    details: dict[str, object] = field(default_factory=dict)


class ToolPolicyEvaluator:
    """最小工具安全策略：先把会改变工作区/外部世界的工具挡在审批门前。"""

    risky_permission_domains = {"write", "shell", "network", "external"}

    def evaluate(self, spec: ToolSpec) -> ToolPolicyDecision:
        """根据工具规格判断本次调用的安全策略。"""
        if not spec.model_callable:
            return ToolPolicyDecision(
                action=DENY,
                reason=f"Tool is not model-callable: {spec.name}",
                details={"tool_name": spec.name},
            )
        if spec.requires_confirmation:
            return ToolPolicyDecision(
                action=ASK,
                reason=f"Tool requires explicit confirmation: {spec.name}",
                details={"tool_name": spec.name, "requires_confirmation": True},
            )
        if spec.side_effect:
            return ToolPolicyDecision(
                action=ASK,
                reason=f"Tool may change local state: {spec.name}",
                details={"tool_name": spec.name, "side_effect": True},
            )
        if spec.permission_domain in self.risky_permission_domains:
            return ToolPolicyDecision(
                action=ASK,
                reason=f"Tool uses risky permission domain '{spec.permission_domain}': {spec.name}",
                details={"tool_name": spec.name, "permission_domain": spec.permission_domain},
            )
        return ToolPolicyDecision(action=ALLOW, details={"tool_name": spec.name})
