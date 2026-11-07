from typing import Any

from pydantic import BaseModel


class Phase(BaseModel):
    name: str
    objective: str
    activities: list[str]
    deliverables: list[str]
    duration_weeks: float | None = None
    dependencies: list[str] = []


class SolutionDesign(BaseModel):
    approach_summary: str
    architecture_description: str
    architecture_components: list[dict[str, Any]]  # {name, purpose, technology, maps_to_req_codes}
    requirement_traceability: dict[str, str]  # req_code -> how addressed
    phases: list[Phase]
    testing_strategy: str
    deployment_strategy: str
    support_model: str
    assumptions: list[str]
    risks: list[dict[str, Any]]  # {risk, impact, mitigation}
    capability_gaps: list[str]
