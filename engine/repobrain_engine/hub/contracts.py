"""Structured contracts for Knowledge Hub refresh and ask flows.

This module centralizes the machine-readable artifacts written during
``rb refresh`` and consumed during ``rb ask``. The contracts intentionally
separate:

- refresh-time module facts and health state
- ask-time claim selection and verification results

These models are the source of truth for the upgraded evidence-driven
pipeline. Human-readable Markdown views are rendered from these models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ClaimImportance = Literal["high", "medium", "low"]
RefreshState = Literal["success", "partial", "failed", "skipped", "unresolved"]
VerificationState = Literal["verified", "partially_verified", "unverified"]
ImpactDecisionState = Literal["affected", "unaffected", "unresolved"]


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format.

    Returns:
        ISO-8601 timestamp string with timezone information.
    """
    return datetime.now(timezone.utc).isoformat()


class EvidenceSpan(BaseModel):
    """A source-backed evidence snippet for a claim.

    Args:
        file: Workspace-relative source file path.
        start_line: Inclusive 1-based start line.
        end_line: Inclusive 1-based end line.
        excerpt: Text snippet copied from the source range.
    """

    file: str = Field(description="Workspace-relative source file path.")
    start_line: int = Field(ge=1, description="Inclusive 1-based start line.")
    end_line: int = Field(ge=1, description="Inclusive 1-based end line.")
    excerpt: str = Field(default="", description="Source excerpt for the evidence span.")

    @field_validator("end_line")
    @classmethod
    def validate_line_order(cls, value: int, info) -> int:
        """Ensure evidence spans use non-decreasing line ranges.

        Args:
            value: Proposed end line value.
            info: Pydantic validation metadata.

        Returns:
            The validated end line.

        Raises:
            ValueError: If ``end_line`` is smaller than ``start_line``.
        """
        start_line = info.data.get("start_line", 1)
        if value < start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return value


class ModuleClaim(BaseModel):
    """A structured claim about a module, backed by source evidence.

    Args:
        claim_id: Stable machine-readable identifier for the claim.
        claim_type: Category such as ``responsibility`` or ``public_api``.
        statement: Human-readable claim statement.
        importance: Verification priority for this claim.
        source_files: Files relevant to the claim.
        evidence: One or more evidence spans supporting the claim.
    """

    claim_id: str = Field(description="Stable identifier for the claim.")
    claim_type: str = Field(description="Claim category.")
    statement: str = Field(description="Human-readable claim statement.")
    importance: ClaimImportance = Field(
        default="medium",
        description="Verification priority for the claim.",
    )
    source_files: list[str] = Field(
        default_factory=list,
        description="Workspace-relative files related to the claim.",
    )
    evidence: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Evidence spans supporting the claim.",
    )

    @field_validator("source_files", mode="before")
    @classmethod
    def normalize_source_files(cls, value: object) -> list[str]:
        """Normalize the source file list while preserving order.

        Args:
            value: Raw source file value.

        Returns:
            Deduplicated list of non-empty source file paths.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            return []

        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized


class GroupFactsDocument(BaseModel):
    """Facts extracted for one refresh analysis group.

    Args:
        module: Module identifier that owns the group.
        group_name: Name of the group within the module.
        source_files: Group files that were analyzed.
        claims: Structured claims extracted from those files.
    """

    module: str = Field(description="Module identifier.")
    group_name: str = Field(description="Group name within the module.")
    source_files: list[str] = Field(
        default_factory=list,
        description="Workspace-relative source files in the group.",
    )
    claims: list[ModuleClaim] = Field(
        default_factory=list,
        description="Claims extracted from the group.",
    )


class ModuleFactsDocument(BaseModel):
    """Merged facts for an entire module.

    Args:
        module: Module identifier.
        groups: Group names merged into this document.
        source_files: All source files represented in the facts.
        claims: Structured module claims.
        generated_at: UTC timestamp for artifact creation.
    """

    module: str = Field(description="Module identifier.")
    groups: list[str] = Field(default_factory=list, description="Merged group names.")
    source_files: list[str] = Field(
        default_factory=list,
        description="All workspace-relative source files in the module facts.",
    )
    claims: list[ModuleClaim] = Field(
        default_factory=list,
        description="Merged module claims.",
    )
    generated_at: str = Field(
        default_factory=utc_now_iso,
        description="UTC timestamp for the generated artifact.",
    )


class ModuleRegistryEntry(BaseModel):
    """Lightweight routing entry for a module.

    Args:
        module: Module identifier.
        keywords: Routing keywords derived from structured facts.
        top_paths: Representative source paths for the module.
        status: Health state of the module knowledge.
        summary: Short description for humans and fallback routing.
    """

    module: str = Field(description="Module identifier.")
    keywords: list[str] = Field(default_factory=list, description="Routing keywords.")
    top_paths: list[str] = Field(
        default_factory=list,
        description="Representative workspace-relative source paths.",
    )
    status: RefreshState = Field(description="Health state for the module knowledge.")
    summary: str = Field(default="", description="Short human-readable module summary.")


class FailureRecord(BaseModel):
    """Machine-readable record for a refresh failure.

    Args:
        stage: Refresh stage name.
        module: Optional module identifier related to the failure.
        group: Optional group name related to the failure.
        reason: Short failure reason.
    """

    stage: str = Field(description="Refresh stage name.")
    module: str | None = Field(default=None, description="Related module identifier.")
    group: str | None = Field(default=None, description="Related group name.")
    reason: str = Field(description="Human-readable failure reason.")


class ChangeRecord(BaseModel):
    """One committed-tree change considered by incremental refresh."""

    path: str = Field(description="Target workspace-relative path.")
    old_path: str | None = Field(default=None, description="Source path for a rename.")
    change_type: Literal["added", "modified", "deleted", "renamed"]
    patch: str = Field(default="", description="Bounded unified diff for this change.")
    old_symbols: list[str] = Field(default_factory=list)
    new_symbols: list[str] = Field(default_factory=list)
    signature_changed: bool = False
    imports_added: list[str] = Field(default_factory=list)
    imports_removed: list[str] = Field(default_factory=list)
    semantic_noop_hint: bool = False


class ImpactCandidate(BaseModel):
    """A stable Agent group offered to the impact planner."""

    group_id: str
    module: str
    group_name: str
    files: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    distance: int = Field(default=0, ge=0)


class ImpactDecision(BaseModel):
    """Planner or verifier decision for one Agent group."""

    group_id: str
    decision: ImpactDecisionState
    reason: str
    evidence: list[str] = Field(default_factory=list)
    impact_path: list[str] = Field(default_factory=list)
    propagate: bool = False
    artifacts: list[str] = Field(default_factory=list)


class ImpactVerification(BaseModel):
    """Independent verification of a proposed impact set."""

    decisions: list[ImpactDecision] = Field(default_factory=list)
    missing_group_ids: list[str] = Field(default_factory=list)
    extraneous_group_ids: list[str] = Field(default_factory=list)
    approved: bool = False
    reason: str = ""


class ImpactPlan(BaseModel):
    """Auditable output of the bounded Planner/Verifier loop."""

    run_id: str
    baseline_generation: str
    baseline_head: str
    target_head: str
    round: int = Field(default=0, ge=0)
    changes: list[ChangeRecord] = Field(default_factory=list)
    candidates: list[ImpactCandidate] = Field(default_factory=list)
    decisions: list[ImpactDecision] = Field(default_factory=list)
    verifier: ImpactVerification | None = None
    affected_group_ids: list[str] = Field(default_factory=list)
    unaffected_group_ids: list[str] = Field(default_factory=list)
    unresolved_group_ids: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class RefreshStatus(BaseModel):
    """Top-level status artifact for a refresh run.

    Args:
        refresh_run_id: Stable identifier for the refresh run.
        generated_at: UTC timestamp for status generation.
        overall_status: Aggregate refresh result.
        stages: Stage-level statuses.
        modules: Module-level statuses keyed by module id.
        failures: Collected partial and hard failures.
    """

    refresh_run_id: str = Field(description="Stable identifier for the refresh run.")
    generated_at: str = Field(
        default_factory=utc_now_iso,
        description="UTC timestamp for the status artifact.",
    )
    overall_status: RefreshState = Field(description="Aggregate refresh result.")
    stages: dict[str, RefreshState] = Field(
        default_factory=dict,
        description="Stage-level statuses.",
    )
    modules: dict[str, RefreshState] = Field(
        default_factory=dict,
        description="Module-level statuses keyed by module id.",
    )
    failures: list[FailureRecord] = Field(
        default_factory=list,
        description="Collected failures for the refresh run.",
    )
    head_sha: str | None = Field(
        default=None,
        description="Git HEAD SHA observed while writing this status.",
    )
    module_head_shas: dict[str, str] = Field(
        default_factory=dict,
        description="HEAD SHA where each module status was last updated.",
    )
    groups: dict[str, RefreshState] = Field(
        default_factory=dict,
        description="Group-level statuses keyed by '<module>/<group>'.",
    )
    group_head_shas: dict[str, str] = Field(
        default_factory=dict,
        description="HEAD SHA where each group status was last updated.",
    )
    baseline_generation: str | None = None
    target_head: str | None = None
    impact_round: int = 0
    affected_groups: list[str] = Field(default_factory=list)
    unaffected_groups: list[str] = Field(default_factory=list)
    unresolved_groups: list[str] = Field(default_factory=list)
    impact_plan_path: str | None = None

    @property
    def exit_code(self) -> int:
        """Return the CLI exit code implied by this status.

        Returns:
            ``0`` for success, ``2`` for partial refresh, and ``1`` for hard
            failure.
        """
        if self.overall_status == "success":
            return 0
        if self.overall_status in {"partial", "unresolved"}:
            return 2
        return 1


class WorkerEvidence(BaseModel):
    """Selected claim set used to answer a question.

    Args:
        module: Module identifier selected by the pre-router.
        draft_answer: Worker-level answer draft for the module.
        claims_used: Claim identifiers used by the worker.
        verification_required: Whether verifier must inspect the claims.
    """

    module: str = Field(description="Selected module identifier.")
    draft_answer: str = Field(default="", description="Worker-level answer draft.")
    claims_used: list[str] = Field(
        default_factory=list,
        description="Claim identifiers used to draft the answer.",
    )
    verification_required: bool = Field(
        default=False,
        description="Whether verification is mandatory for this worker output.",
    )


class ClaimVerification(BaseModel):
    """Verification result for a single claim.

    Args:
        claim_id: Verified claim identifier.
        state: Verification outcome.
        notes: Short explanation for the outcome.
        evidence: Evidence spans inspected during verification.
    """

    claim_id: str = Field(description="Verified claim identifier.")
    state: VerificationState = Field(description="Verification outcome.")
    notes: str = Field(default="", description="Short explanation for the outcome.")
    evidence: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Evidence spans inspected during verification.",
    )


class VerificationResult(BaseModel):
    """Aggregated verification report for an answer.

    Args:
        question: Original user question.
        module: Module identifier that was verified.
        claims: Per-claim verification results.
        verification_required: Whether verification was mandatory.
    """

    question: str = Field(description="Original user question.")
    module: str = Field(description="Module identifier that was verified.")
    claims: list[ClaimVerification] = Field(
        default_factory=list,
        description="Per-claim verification results.",
    )
    verification_required: bool = Field(
        default=False,
        description="Whether verification was mandatory for the module.",
    )
