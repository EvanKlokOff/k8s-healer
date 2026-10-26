from healer.core.config import settings
from healer.core.guardrails.base import Guardrail
from healer.core.schemas import Decision, GuardrailResult


class BlastRadiusGuardrail(Guardrail):
    """Не трогаем control-plane ноды и не более X% нод одновременно."""

    name = "blast_radius"

    def __init__(self, control_plane_roles: tuple[str, ...] = ("control-plane", "master")):
        self.control_plane_roles = control_plane_roles

    def check(self, decision: Decision) -> GuardrailResult:
        node = decision.action_params.get("node")
        if not node:
            return GuardrailResult(name=self.name, allowed=True)

        # control-plane защита
        node_roles = decision.action_params.get("node_roles", [])
        if any(r in self.control_plane_roles for r in node_roles):
            return GuardrailResult(
                name=self.name,
                allowed=False,
                reason=f"node {node} is control-plane, refusing action",
            )
        return GuardrailResult(name=self.name, allowed=True)