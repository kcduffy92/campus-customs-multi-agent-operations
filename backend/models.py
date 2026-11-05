"""Data types shared by the agent team, the audit trail and (later) the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "awaiting_approval", "resolved"]


class Fact(BaseModel):
    """One fact an agent relies on, tied to the MCP tool that returned it."""

    source_tool: str = Field(description="MCP tool (or colleague) the fact came from, e.g. check_rent_due")
    detail: str = Field(description="The fact, with the exact values the tool returned")


class AgentReport(BaseModel):
    """Structured output every agent returns, to the Boss or to the colleague who asked."""

    agent: AgentName
    summary: str = Field(description="What this agent found and did, in a few sentences")
    facts: list[Fact] = Field(default_factory=list, description="Only facts returned by tools in this run")
    approval_request_ids: list[int] = Field(
        default_factory=list, description="IDs of approval requests filed or found for this ticket"
    )
    customer_reply: str | None = Field(
        default=None, description="Draft reply to the requester (Customer Service or Boss only). Never sent."
    )
    recommended_ticket_status: TicketStatus | None = None
    open_issues: list[str] = Field(default_factory=list, description="Anything unresolved or needing a human")


class DelegationResult(BaseModel):
    """What the delegate tool hands back to the calling agent."""

    accepted: bool
    to_agent: str
    cached: bool = False
    refusal: str | None = None
    report: AgentReport | None = None


class DelegationRecord(BaseModel):
    from_agent: str
    to_agent: str
    depth: int
    task: str
    outcome: Literal["completed", "cached", "refused", "failed"]
    note: str | None = None


class UsageSummary(BaseModel):
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TeamRunResult(BaseModel):
    """The outcome of running the whole team on one ticket."""

    run_id: str
    ticket_id: int
    model: str
    status: Literal["completed", "stopped_usage_limit", "error", "refused"]
    final_report: AgentReport | None = None
    delegations: list[DelegationRecord] = Field(default_factory=list)
    usage: UsageSummary = Field(default_factory=UsageSummary)
    error: str | None = None
