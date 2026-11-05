"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

Each agent is a PydanticAI agent on gpt-6-luna (through Portkey) with:
- its own prompt from backend/prompts/<name>.md,
- its own filtered view of the campus-customs MCP server (HTTP). Shop facts come
  only from these MCP tools; this module never opens the database,
- one `delegate` tool that can reach any other agent (full connectivity), guarded
  by depth, per-ticket, duplicate and circular-delegation limits,
- a structured AgentReport output.

All agents in one ticket run share one RunUsage and one UsageLimits budget, and
every agent-loop step is appended to output/audit_trail.json.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimits

import config
from audit import append_event, preview
from models import (
    AGENT_NAMES,
    AgentName,
    AgentReport,
    DelegationRecord,
    DelegationResult,
    TeamRunResult,
    UsageSummary,
)

# Which campus-customs MCP tools each agent may see. Money requests have one owner
# (Accounting) so the same payment is never requested by two agents.
AGENT_TOOLS: dict[str, frozenset[str]] = {
    "boss": frozenset({"list_tickets", "get_ticket", "list_approval_requests", "update_ticket"}),
    "inventory": frozenset({"check_stock_and_pricing", "list_vendors", "get_vendor_invoice_status"}),
    "accounting": frozenset({
        "get_vendor_invoice_status", "check_rent_due", "check_stock_and_pricing", "get_cash_balance",
        "list_approval_requests", "request_invoice_payment", "request_rent_payment", "request_purchase",
        "request_discount",
    }),
    "facilities": frozenset({"get_ticket", "check_rent_due"}),
    "customer_service": frozenset({"get_ticket", "check_stock_and_pricing", "list_approval_requests"}),
}

# Human-decision tools on the MCP server. No agent toolset may ever include them.
BACKEND_ONLY_TOOLS = frozenset({"execute_approved_request", "reject_request"})
assert not any(tools & BACKEND_ONLY_TOOLS for tools in AGENT_TOOLS.values()), "agent can reach a backend-only tool"
assert set(AGENT_TOOLS) == set(AGENT_NAMES)

# Tools where the caller's identity and ticket are filled in by this code, not the model.
_REQUESTER_TOOLS = {"request_invoice_payment", "request_rent_payment", "request_purchase", "request_discount"}


# ---------------------------------------------------------------------------
# Run state and delegation guards
# ---------------------------------------------------------------------------


@dataclass
class TicketRun:
    """State shared by every agent working one ticket."""

    run_id: str
    ticket_id: int
    delegations: int = 0
    seen_tasks: dict[tuple[str, str], AgentReport] = field(default_factory=dict)
    records: list[DelegationRecord] = field(default_factory=list)


@dataclass
class TeamDeps:
    """Per-agent dependencies: who is running, and the chain of agents that led here."""

    run: TicketRun
    agent: AgentName
    chain: tuple[str, ...]

    @property
    def depth(self) -> int:
        return len(self.chain) - 1


def normalize_task(task: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", task.lower()).split())


def check_delegation(deps: TeamDeps, to_agent: str, task: str) -> str | None:
    """Return a refusal reason, or None if the delegation may go ahead."""
    if to_agent not in AGENT_NAMES:
        return f"Unknown agent {to_agent!r}. Choose one of {list(AGENT_NAMES)}."
    if to_agent == deps.agent:
        return "An agent cannot delegate to itself; do the work with your own tools."
    if to_agent in deps.chain:
        return f"Circular delegation refused: {to_agent} is already in the chain {' -> '.join(deps.chain)}."
    if deps.depth + 1 > config.MAX_DELEGATION_DEPTH:
        return f"Delegation depth limit ({config.MAX_DELEGATION_DEPTH}) reached; finish with what you have."
    if deps.run.delegations >= config.MAX_DELEGATIONS_PER_TICKET:
        return f"Per-ticket delegation limit ({config.MAX_DELEGATIONS_PER_TICKET}) reached; finish with what you have."
    if not normalize_task(task):
        return "The task is empty; say exactly what you need."
    return None


def usage_summary(usage: RunUsage) -> UsageSummary:
    return UsageSummary(
        requests=usage.requests,
        tool_calls=usage.tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _audit(deps: TeamDeps, action: str, **fields: Any) -> None:
    append_event({
        "run_id": deps.run.run_id,
        "ticket_id": deps.run.ticket_id,
        "agent": deps.agent,
        "parent_agent": deps.chain[-2] if len(deps.chain) > 1 else None,
        "depth": deps.depth,
        "chain": list(deps.chain),
        "action": action,
        **fields,
    })


# ---------------------------------------------------------------------------
# MCP toolsets (one filtered view per agent)
# ---------------------------------------------------------------------------


async def _process_tool_call(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict[str, Any]):
    """Enforce the allowlist, stamp identity, call the MCP tool, and audit the call."""
    deps = ctx.deps
    if name not in AGENT_TOOLS[deps.agent] or name in BACKEND_ONLY_TOOLS:
        _audit(deps, "mcp_tool_refused", tool=name, args=args)
        return {"error": f"{deps.agent} is not allowed to call {name}."}
    args = dict(args)
    if name in _REQUESTER_TOOLS:
        args["requested_by"] = deps.agent
        args["ticket_id"] = deps.run.ticket_id
    if name == "update_ticket":
        args["updated_by"] = deps.agent
        args["ticket_id"] = deps.run.ticket_id
        # A finished run is not a fulfilled ticket. Only a person (dashboard resolve route) or the
        # backend's recorded-rent rule may set "resolved"; agents recommend it in their report instead.
        if str(args.get("status", "")).strip().lower() == "resolved":
            message = ("Agents cannot mark a ticket resolved. Set awaiting_approval or in_progress, and put your "
                       "recommendation in recommended_ticket_status and open_issues. A person confirms "
                       "resolution in the dashboard.")
            _audit(deps, "mcp_tool_refused", tool=name, args=args, result=message)
            return {"updated": False, "error": message}
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        _audit(deps, "mcp_tool_error", tool=name, args=args, result=preview(f"{type(exc).__name__}: {exc}"))
        raise
    _audit(deps, "mcp_tool_call", tool=name, args=args, result=preview(result))
    return result


def _toolset(name: str):
    allowed = AGENT_TOOLS[name]
    base = MCPToolset(config.MCP_SERVER_URL, id=f"campus-customs-{name}", process_tool_call=_process_tool_call)
    return base.filtered(lambda ctx, tool_def: tool_def.name in allowed)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

_agents: dict[str, Agent[TeamDeps, AgentReport]] = {}


def _model() -> OpenAIResponsesModel:
    key = config.portkey_api_key()
    headers = {"x-portkey-api-key": key}
    if config.PORTKEY_PROVIDER:
        headers["x-portkey-provider"] = config.PORTKEY_PROVIDER
    client = AsyncOpenAI(api_key=key, base_url=config.PORTKEY_BASE_URL, default_headers=headers)
    return OpenAIResponsesModel(config.MODEL_NAME, provider=OpenAIProvider(openai_client=client))


async def delegate(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> DelegationResult:
    """Ask one colleague to do a specific piece of work on this ticket and return their report.

    Only delegate when the colleague owns the information or action you need. Give a precise
    task (what to check or prepare, with any IDs). Refused if it would loop, repeat, or exceed
    the depth or per-ticket limits.
    """
    deps = ctx.deps
    run = deps.run
    refusal = check_delegation(deps, to_agent, task)
    if refusal:
        run.records.append(DelegationRecord(from_agent=deps.agent, to_agent=to_agent, depth=deps.depth + 1,
                                            task=task, outcome="refused", note=refusal))
        _audit(deps, "delegation_refused", delegation={"to_agent": to_agent, "task": task}, result=refusal)
        return DelegationResult(accepted=False, to_agent=to_agent, refusal=refusal)

    key = (to_agent, normalize_task(task))
    if key in run.seen_tasks:
        run.records.append(DelegationRecord(from_agent=deps.agent, to_agent=to_agent, depth=deps.depth + 1,
                                            task=task, outcome="cached", note="identical task already answered"))
        _audit(deps, "delegation_cached", delegation={"to_agent": to_agent, "task": task})
        return DelegationResult(accepted=True, to_agent=to_agent, cached=True, report=run.seen_tasks[key])

    run.delegations += 1
    child = TeamDeps(run=run, agent=to_agent, chain=(*deps.chain, to_agent))
    _audit(deps, "delegation_started", delegation={"to_agent": to_agent, "task": task, "number": run.delegations})
    prompt = (
        f"Ticket {run.ticket_id}. {deps.agent} asks you (delegation chain: {' -> '.join(child.chain)}):\n{task}"
    )
    try:
        report = await run_agent(to_agent, prompt, child, ctx.usage)
    except UsageLimitExceeded:
        raise  # the shared budget is gone: stop the whole ticket run
    except Exception as exc:
        note = f"{type(exc).__name__}: {exc}"[:300]
        run.records.append(DelegationRecord(from_agent=deps.agent, to_agent=to_agent, depth=child.depth,
                                            task=task, outcome="failed", note=note))
        _audit(deps, "delegation_failed", delegation={"to_agent": to_agent, "task": task}, result=note)
        return DelegationResult(accepted=False, to_agent=to_agent, refusal=f"{to_agent} failed: {note}")
    run.seen_tasks[key] = report
    run.records.append(DelegationRecord(from_agent=deps.agent, to_agent=to_agent, depth=child.depth,
                                        task=task, outcome="completed"))
    _audit(deps, "delegation_finished", delegation={"to_agent": to_agent, "task": task},
           result=preview(report.model_dump()))
    return DelegationResult(accepted=True, to_agent=to_agent, report=report)


def get_agent(name: str) -> Agent[TeamDeps, AgentReport]:
    if name not in _agents:
        prompt = (config.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        agent: Agent[TeamDeps, AgentReport] = Agent(
            _model(),
            name=name,
            deps_type=TeamDeps,
            output_type=AgentReport,
            instructions=prompt,
            toolsets=[_toolset(name)],
            retries=2,
        )
        agent.tool(delegate)
        _agents[name] = agent
    return _agents[name]


def usage_limits() -> UsageLimits:
    return UsageLimits(
        request_limit=config.REQUEST_LIMIT,
        tool_calls_limit=config.TOOL_CALLS_LIMIT,
        total_tokens_limit=config.TOTAL_TOKENS_LIMIT,
    )


def _log_node(deps: TeamDeps, step: int, node: Any, usage: RunUsage) -> None:
    """Write one audit entry for one agent-loop step."""
    if Agent.is_model_request_node(node):
        returns, prompt = [], None
        for part in node.request.parts:
            if isinstance(part, ToolReturnPart):
                returns.append({"tool": part.tool_name, "result": preview(part.content)})
            elif isinstance(part, RetryPromptPart):
                returns.append({"tool": part.tool_name, "retry": preview(part.content)})
            elif isinstance(part, UserPromptPart):
                prompt = preview(part.content)
        _audit(deps, "model_request", step=step, prompt=prompt, tool_results=returns,
               usage=usage_summary(usage).model_dump())
    elif Agent.is_call_tools_node(node):
        resp = node.model_response
        calls, text, thinking = [], [], []
        for part in resp.parts:
            if isinstance(part, ToolCallPart):
                kind = ("delegation" if part.tool_name == "delegate"
                        else "mcp" if part.tool_name in AGENT_TOOLS[deps.agent] else "output")
                calls.append({"tool": part.tool_name, "kind": kind, "args": part.args_as_dict()})
            elif isinstance(part, TextPart) and part.content:
                text.append(preview(part.content))
            elif isinstance(part, ThinkingPart) and part.content:
                thinking.append(preview(part.content))
        _audit(deps, "model_response", step=step, model=resp.model_name, tool_calls=calls, text=text,
               thinking=thinking, finish_reason=resp.finish_reason,
               response_tokens={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
               usage=usage_summary(usage).model_dump())


async def run_agent(name: str, prompt: str, deps: TeamDeps, usage: RunUsage) -> AgentReport:
    """Run one agent's loop to its structured output, auditing every step."""
    agent = get_agent(name)
    _audit(deps, "agent_started", prompt=preview(prompt))
    step = 0
    async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=usage_limits()) as run:
        async for node in run:
            step += 1
            _log_node(deps, step, node, usage)
    report = run.result.output
    # Readable conclusion fields for the dashboard, next to the (truncated) full report.
    _audit(deps, "agent_finished", step=step, result=preview(report.model_dump()),
           summary=report.summary[:1000], customer_reply=(report.customer_reply or "")[:1000] or None,
           approval_request_ids=list(report.approval_request_ids),
           recommended_ticket_status=report.recommended_ticket_status,
           open_issues=[issue[:300] for issue in report.open_issues],
           usage=usage_summary(usage).model_dump())
    return report


_active_tickets: set[int] = set()


async def run_team(ticket_id: int, run_id: str | None = None) -> TeamRunResult:
    """Run the team on one ticket, starting with the Boss. One run per ticket at a time.

    run_id lets the API hand the id to the dashboard before the run starts.
    """
    run = TicketRun(run_id=run_id or str(uuid.uuid4()), ticket_id=ticket_id)
    deps = TeamDeps(run=run, agent="boss", chain=("boss",))
    base = {"run_id": run.run_id, "ticket_id": ticket_id, "model": config.MODEL_NAME}
    if ticket_id in _active_tickets:
        return TeamRunResult(**base, status="refused", error="This ticket is already being worked.")
    _active_tickets.add(ticket_id)
    usage = RunUsage()
    _audit(deps, "run_started", model=config.MODEL_NAME, mcp_server=config.MCP_SERVER_URL,
           run_label=config.RUN_LABEL, limits={
        "max_delegation_depth": config.MAX_DELEGATION_DEPTH,
        "max_delegations_per_ticket": config.MAX_DELEGATIONS_PER_TICKET,
        "request_limit": config.REQUEST_LIMIT,
        "tool_calls_limit": config.TOOL_CALLS_LIMIT,
        "total_tokens_limit": config.TOTAL_TOKENS_LIMIT,
    })
    report, status, error = None, "completed", None
    try:
        report = await run_agent(
            "boss",
            f"Work desk ticket {ticket_id}. Read it with get_ticket first, then follow your instructions.",
            deps,
            usage,
        )
    except UsageLimitExceeded as exc:
        status, error = "stopped_usage_limit", str(exc)
    except Exception as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"[:500]
    finally:
        _active_tickets.discard(ticket_id)
    result = TeamRunResult(**base, status=status, final_report=report, delegations=run.records,
                           usage=usage_summary(usage), error=error)
    _audit(deps, "run_finished", status=status, error=error, usage=result.usage.model_dump(),
           delegations=[r.model_dump() for r in run.records])
    return result
