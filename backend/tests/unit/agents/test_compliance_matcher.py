from app.agents import compliance_matcher as cm
from app.llm.fake import FakeLLMClient
from app.schemas.compliance import ComplianceStatus, LLMMatchBatch
from app.schemas.evidence import EvidenceCategory as EC
from app.schemas.tender import ReqCategory as RC
from tests.unit.agents.builders import ev, req


class KeywordEmbedLLM(FakeLLMClient):
    """Embeddings on a few keyword axes, so similarity is predictable."""

    AXES = ("iso", "project", "turnover", "java", "staff")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if axis in low else 0.0 for axis in self.AXES] + [0.01] * 1531
            out.append(vec)
        return out


async def test_select_candidates_category_first_then_similarity_and_k() -> None:
    reqs = [req("CER-001", "Valid ISO 9001 certificate", RC.CERTIFICATION)]
    evidence = [
        ev("EV-PRJ-001", EC.PROJECT, "Project with ISO audit"),
        ev("EV-CER-001", EC.CERTIFICATION, "ISO 9001 certificate"),
        ev("EV-CER-002", EC.CERTIFICATION, "PEC licence"),
        ev("EV-FIN-001", EC.FINANCIAL, "Turnover 2023"),
    ]
    out = await cm.select_candidates(KeywordEmbedLLM(), reqs, evidence, k=3)
    assert [e.evidence_code for e in out["CER-001"]] == ["EV-CER-001", "EV-CER-002", "EV-PRJ-001"]


async def test_select_candidates_without_evidence_makes_no_embed_call() -> None:
    class NoEmbed(FakeLLMClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("should not embed")

    out = await cm.select_candidates(NoEmbed(), [req("TEC-001", "x")], [], k=8)
    assert out == {"TEC-001": []}


async def test_batches_of_ten_and_skipped_requirements_filled_unverified() -> None:
    reqs = [req(f"TEC-{i:03d}", f"Requirement {i}") for i in range(1, 24)]
    reqs.append(req("TEC-099", "No evidence for this one"))
    item = ev("EV-CAP-001", EC.CAPABILITY, "Java development")
    candidates = {r.req_code: [item] for r in reqs[:23]}
    candidates["TEC-099"] = []
    batch_sizes: list[int] = []

    def respond(system: str, user: str, schema: type) -> dict:
        assert schema is LLMMatchBatch
        codes = [c for c in (f"TEC-{i:03d}" for i in range(1, 100)) if f'"{c}"' in user]
        batch_sizes.append(len(codes))
        matches = [
            {
                "req_code": c,
                "proposed_status": "PARTIAL",
                "confidence": "MEDIUM",
                "evidence_codes": ["EV-CAP-001"],
                "rationale": "ok",
            }
            for c in codes
            if c != "TEC-005"  # the model skips one
        ]
        matches.append(  # and invents one outside the batch -> ignored
            {
                "req_code": "ELG-777",
                "proposed_status": "COMPLIANT",
                "confidence": "HIGH",
                "evidence_codes": [],
                "rationale": "x",
            }
        )
        return {"matches": matches}

    llm = FakeLLMClient().on("compliance", respond)
    out = await cm.match_requirements(llm, candidates, reqs, run_id="r1")
    assert sorted(batch_sizes) == [3, 10, 10]  # TEC-099 never sent
    assert [m.req_code for m in out] == [r.req_code for r in reqs]  # one per requirement
    by_code = {m.req_code: m for m in out}
    assert by_code["TEC-005"].proposed_status == ComplianceStatus.UNVERIFIED
    assert by_code["TEC-005"].evidence_codes == []
    assert by_code["TEC-099"].proposed_status == ComplianceStatus.UNVERIFIED
    assert by_code["TEC-001"].proposed_status == ComplianceStatus.PARTIAL
    assert "ELG-777" not in by_code
    assert all(c.model_tier == "fast" for c in llm.calls)


async def test_no_candidates_anywhere_means_no_llm_call() -> None:
    llm = FakeLLMClient()
    out = await cm.match_requirements(llm, {}, [req("TEC-001", "x")], run_id="r1")
    assert llm.calls == [] and out[0].proposed_status == ComplianceStatus.UNVERIFIED
