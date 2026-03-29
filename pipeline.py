"""Agents + one async runner. Env: OPENAI_API_KEY, DEEPSEEK_API_KEY, SENDGRID_*."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agents import (
    Agent,
    GuardrailFunctionOutput,
    ItemHelpers,
    OpenAIChatCompletionsModel,
    RunResult,
    Runner,
    function_tool,
    input_guardrail,
    trace,
)
from agents.exceptions import MaxTurnsExceeded
from agents.lifecycle import RunHooks
from agents.run_context import RunContextWrapper
from agents.tool import Tool

from telegram_util import bind_steps_list, log_step, steps_reset

log = logging.getLogger("complai_sdr.pipeline")

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _is_valid_email(addr: str) -> bool:
    s = (addr or "").strip()
    return bool(s and EMAIL_PATTERN.fullmatch(s))


class ParsedInput(BaseModel):
    recipient_email: str = Field(
        description="Recipient email (plain user@domain) or empty if missing.",
    )
    brief: str = Field(description="Campaign instructions for the SDR, excluding the recipient address.")


class DraftReview(BaseModel):
    accept: bool = Field(description="True if the draft is ready to send; False otherwise.")
    feedback: str = Field(description="Rationale and concrete suggestions.")


class NameCheckOutput(BaseModel):
    is_name_in_message: bool
    name: str


# Shared by all drafters: reduces default "Silicon Valley outbound" bias and stereotypical hooks.
DRAFTER_SHARED = """

Ground rules (all drafts):
- Follow the user's brief for audience, persona, region, industry, and formality. Do not override it with your own assumptions.
- Do not guess the recipient's gender, background, or personal traits; use neutral salutations ("Hello," "Hi there," or role/title from the brief) unless the brief names the person.
- Avoid stereotypes, caricatures, or humor at the expense of any group. Wit should be good-natured and restrained—never snark about roles, companies, or regions.
- Do not invent metrics, logos, customers, audits, or certifications. Stay within plausible claims for ComplAI as SOC2 / audit-readiness assistance software.
- Keep tone inclusive and respectful; avoid idioms that rely on narrow cultural context unless the brief targets that locale.
"""

INSTRUCTIONS1 = (
    """You represent ComplAI: a SaaS product that helps teams work toward SOC2 and audit readiness, with AI-assisted workflows. \
You write the email body only (no subject line), in a calm, direct, businesslike voice—clear and serious without being cold."""
    + DRAFTER_SHARED
)

INSTRUCTIONS2 = (
    """You represent ComplAI: a SaaS product that helps teams work toward SOC2 and audit readiness, with AI-assisted workflows. \
You write the email body only (no subject line), in a warm, lightly personable voice. You may use gentle humor or a clever line \
if it fits the brief, but never at the recipient's expense and never relying on stereotypes."""
    + DRAFTER_SHARED
)

INSTRUCTIONS3 = (
    """You represent ComplAI: a SaaS product that helps teams work toward SOC2 and audit readiness, with AI-assisted workflows. \
You write the email body only (no subject line), as short as possible while respectful and complete—no filler, no clichéd urgency."""
    + DRAFTER_SHARED
)

REVIEWER_INSTRUCTIONS = """You are a quality reviewer for outbound cold emails at ComplAI (SOC2 / audit-readiness SaaS).

You receive the user's request, the three draft bodies, which draft was chosen, and optional rationale.

Judge the chosen draft on:
- Fit to the user's brief (audience, goal, tone, facts).
- Clarity and honesty (no fabricated proof points or stats).
- Respect and inclusion: no demeaning, exoticizing, or stereotypical language; no assumptions about the recipient beyond the brief.
- Tone appropriate to the brief—not "professional" only in the narrow sense of formal US enterprise mail; match what the brief asked for.

Reject (accept: false) if the draft is off-brief, misleading, or unfair to the reader. Output only structured accept + feedback."""

SALES_MANAGER_INSTRUCTIONS = """
You are a Sales Manager at ComplAI. Use sales_agent1, sales_agent2, sales_agent3 to get three drafts (body only, no subject).
Pick the best option for the user's stated goal and audience—not a default preference for one tone. Call review_draft_email with the user's request, all three drafts, chosen number (1–3), winning body, and rationale.
If accept is true, hand off the winning body to Email Manager via transfer_to_email_manager.
If accept is false, revise once (regenerate drafts as needed), call review_draft_email exactly one more time, then hand off to Email Manager—never a third review round.
"""

INPUT_PARSER_INSTRUCTIONS = """You parse the user's message into two fields only (structured output, no extra text).

recipient_email: One valid outbound address (local-part@domain). Strip mailto:, URLs, and brackets. If no plausible email exists, use an empty string. Never invent an address.

brief: Everything else—the campaign instructions (product, audience, tone, persona)—without repeating only the email line."""

_TOOL_DRAFT_LABELS = {"sales_agent1": "1", "sales_agent2": "2", "sales_agent3": "3"}


async def _delay_if_configured() -> None:
    sec = float(os.environ.get("TELEGRAM_STEP_DELAY_SEC", "0") or "0")
    if sec > 0:
        await asyncio.sleep(sec)


async def _log(step: str) -> None:
    log_step(step)
    await _delay_if_configured()


def _sales_manager_max_turns() -> int:
    """Default agent run is 10; draft + at most one review loop + Email Manager need headroom."""
    raw = os.environ.get("SDR_MAX_TURNS", "28")
    try:
        n = int(raw)
    except ValueError:
        n = 28
    return max(15, min(n, 80))


class DemoRunHooks(RunHooks):
    """Live step lines for Telegram/console via ``log_step`` (tool start/end)."""

    def __init__(self) -> None:
        self._pending_revise = False

    async def on_tool_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        tool: Tool,
    ) -> None:
        name = tool.name
        if name in _TOOL_DRAFT_LABELS:
            if self._pending_revise:
                await _log("🔁 Revising draft...")
                self._pending_revise = False
            n = _TOOL_DRAFT_LABELS[name]
            await _log(f"✍️ Sales Agent {n} generating draft...")
            return
        if name == "review_draft_email":
            await _log("🧪 Reviewer evaluating draft...")
            return
        if name == "send_html_email":
            await _log("📤 Sending email...")

    async def on_tool_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent[Any],
        tool: Tool,
        result: str,
    ) -> None:
        name = tool.name
        if name == "review_draft_email":
            try:
                data = json.loads(result)
                if data.get("accept") is True:
                    await _log("✅ Reviewer accepted draft")
                elif data.get("accept") is False:
                    await _log("❌ Reviewer rejected draft")
                    self._pending_revise = True
                else:
                    await _log("🧪 Reviewer evaluated draft (no clear accept/reject)")
            except (json.JSONDecodeError, TypeError):
                await _log("🧪 Reviewer evaluated draft (parse error)")
            return
        if name == "send_html_email":
            await _log("✅ Email sent successfully")


def _input_parser_agent() -> Agent[Any]:
    return Agent(
        name="Input parser",
        instructions=INPUT_PARSER_INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=ParsedInput,
    )


def _review_tool_output(output: RunResult) -> Any:
    fo = output.final_output
    if fo is not None and hasattr(fo, "model_dump_json"):
        return fo.model_dump_json()
    text = ItemHelpers.text_message_outputs(output.new_items)
    return text if text else str(fo)


async def _review_tool_output_async(output: RunResult) -> str:
    return str(_review_tool_output(output))


def build_agents(recipient_email: str | None = None) -> tuple[Agent, Agent]:
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        log.error("build_agents aborted: OPENAI_API_KEY is missing or blank")
        raise RuntimeError("OPENAI_API_KEY is required")
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        log.error("build_agents aborted: DEEPSEEK_API_KEY is missing or blank")
        raise RuntimeError("DEEPSEEK_API_KEY is required")

    deepseek_client = AsyncOpenAI(
        base_url=DEEPSEEK_BASE_URL,
        api_key=os.environ["DEEPSEEK_API_KEY"],
    )
    deepseek_model = OpenAIChatCompletionsModel(model="deepseek-chat", openai_client=deepseek_client)

    sales_agent1 = Agent(
        name="ComplAI drafter — professional tone",
        instructions=INSTRUCTIONS1,
        model=deepseek_model,
    )
    sales_agent2 = Agent(
        name="ComplAI drafter — engaging tone",
        instructions=INSTRUCTIONS2,
        model=deepseek_model,
    )
    sales_agent3 = Agent(
        name="ComplAI drafter — concise tone",
        instructions=INSTRUCTIONS3,
        model=deepseek_model,
    )

    tool1 = sales_agent1.as_tool(
        tool_name="sales_agent1",
        tool_description="Draft cold email body (no subject), professional and serious tone.",
    )
    tool2 = sales_agent2.as_tool(
        tool_name="sales_agent2",
        tool_description="Draft cold email body (no subject), witty and engaging tone.",
    )
    tool3 = sales_agent3.as_tool(
        tool_name="sales_agent3",
        tool_description="Draft cold email body (no subject), concise and direct tone.",
    )

    draft_reviewer = Agent(
        name="Email draft reviewer",
        instructions=REVIEWER_INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=DraftReview,
    )
    # Enforce at most one rejection per run; second reject is coerced to accept in the wrapper.
    _review_once_state: dict[str, bool] = {"saw_reject": False}

    @function_tool(
        name_override="review_draft_email",
        description_override=(
            "Review draft choice; returns JSON with accept and feedback. "
            "Only one rejection per email run is allowed; after one revision the next result accepts."
        ),
    )
    async def review_draft_email(ctx: RunContextWrapper[Any], input: str) -> str:
        output = await Runner.run(
            draft_reviewer,
            input,
            context=ctx.context,
            max_turns=10,
        )
        raw = await _review_tool_output_async(output)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if data.get("accept") is False:
            if _review_once_state["saw_reject"]:
                fb = (data.get("feedback") or "").strip()
                data["accept"] = True
                data["feedback"] = (
                    "Accepted after one revision (max one rejection per run). Notes: "
                    + (fb or "(none)")
                )
            else:
                _review_once_state["saw_reject"] = True
        return json.dumps(data)

    review_tool = review_draft_email

    to_override = (recipient_email or "").strip()

    @function_tool
    def send_html_email(subject: str, html_body: str) -> dict[str, str]:
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        key = os.environ.get("SENDGRID_API_KEY")
        from_addr = os.environ.get("SENDGRID_FROM_EMAIL")
        to_addr = to_override or os.environ.get("SENDGRID_TO_EMAIL")
        if not key:
            raise RuntimeError("SENDGRID_API_KEY is not set")
        if not from_addr or not to_addr:
            raise RuntimeError("SENDGRID_FROM_EMAIL and a recipient (parsed email or SENDGRID_TO_EMAIL) must be set")

        sg = sendgrid.SendGridAPIClient(api_key=key)
        mail = Mail(Email(from_addr), To(to_addr), subject, Content("text/html", html_body)).get()
        sg.client.mail.send.post(request_body=mail)
        return {"status": "success"}

    subj = Agent(
        name="Subject line writer",
        instructions=(
            "Write one short subject line that accurately reflects the email body. "
            "No clickbait, false urgency, or bait-and-switch. "
            "Use neutral, inclusive wording; avoid gendered or stereotypical hooks."
        ),
        model="gpt-4o-mini",
    )
    html = Agent(
        name="HTML body formatter",
        instructions=(
            "Convert the email body to simple, readable HTML (paragraphs, minimal styling). "
            "Preserve meaning and inclusive wording; do not add claims or flair not in the source text."
        ),
        model="gpt-4o-mini",
    )
    subject_tool = subj.as_tool(
        tool_name="subject_writer",
        tool_description="Write a short, compelling subject line for the email body.",
    )
    html_tool = html.as_tool(
        tool_name="html_converter",
        tool_description="Convert plain email body to simple, readable HTML.",
    )

    emailer = Agent(
        name="Email Manager",
        instructions=(
            "Use subject_writer, then html_converter, then send_html_email with subject and HTML."
        ),
        tools=[subject_tool, html_tool, send_html_email],
        model="gpt-4o-mini",
        handoff_description="Format and send email",
    )

    sm_tools = [tool1, tool2, tool3, review_tool]
    sales_manager = Agent(
        name="Sales Manager",
        instructions=SALES_MANAGER_INSTRUCTIONS,
        tools=sm_tools,
        handoffs=[emailer],
        model="gpt-4o-mini",
    )

    guard = Agent(
        name="Sender identity check",
        instructions=(
            "Read the user message. Set is_name_in_message to true only if it specifies a particular person's name "
            "as the sender (e.g. sign-off, 'from FirstName LastName', or similar). "
            "Do not treat product names, company names, or role-only labels (e.g. 'Head of Sales') as a person's name. "
            "If true, set name to that person's name or empty string if unclear. Be consistent for names from any cultural background."
        ),
        output_type=NameCheckOutput,
        model="gpt-4o-mini",
    )

    @input_guardrail
    async def guardrail_against_name(ctx, agent, message):
        r = await Runner.run(guard, message, context=ctx.context)
        return GuardrailFunctionOutput(
            output_info={"found_name": r.final_output},
            tripwire_triggered=r.final_output.is_name_in_message,
        )

    careful = Agent(
        name="Sales Manager (input screened)",
        instructions=SALES_MANAGER_INSTRUCTIONS,
        tools=sm_tools,
        handoffs=[emailer],
        model="gpt-4o-mini",
        input_guardrails=[guardrail_against_name],
    )

    return sales_manager, careful


def _out(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


async def run_sdr_pipeline(message: str, *, use_name_guardrail: bool = False) -> dict[str, Any]:
    steps: list[str] = []
    ctx_tok = bind_steps_list(steps)
    trace_name = os.environ.get("WORKFLOW_TRACE_NAME", "Automated SDR")
    try:
        with trace(trace_name):
            await _log("🧠 Parsing input...")

            parser = _input_parser_agent()
            parse_result = await Runner.run(parser, message)
            raw_parsed = parse_result.final_output

            if raw_parsed is None:
                log.warning("parse failed: Input parser returned no structured output")
                await _log("❌ Could not find a valid email in your message")
                return {
                    "recipient_email": "",
                    "steps": steps,
                    "final_output": None,
                    "last_agent": getattr(parse_result.last_agent, "name", "Input parser"),
                }

            p = raw_parsed if isinstance(raw_parsed, ParsedInput) else ParsedInput.model_validate(raw_parsed)

            if not _is_valid_email(p.recipient_email):
                bad = (p.recipient_email or "").strip()
                log.warning(
                    "parse rejected recipient: not a valid email (got %r)",
                    bad[:120] if bad else "(empty)",
                )
                await _log("❌ Could not find a valid email in your message")
                return {
                    "recipient_email": (p.recipient_email or "").strip(),
                    "steps": steps,
                    "final_output": None,
                    "last_agent": parse_result.last_agent.name,
                }

            recipient = p.recipient_email.strip()
            await _log(f"✅ Extracted recipient: {recipient}")

            brief = (p.brief or "").strip() or "Send a professional ComplAI cold email per the user request."

            sm, careful = build_agents(recipient_email=recipient)
            agent = careful if use_name_guardrail else sm
            hooks = DemoRunHooks()
            max_turns = _sales_manager_max_turns()
            try:
                result = await Runner.run(agent, brief, hooks=hooks, max_turns=max_turns)
            except MaxTurnsExceeded:
                log.error(
                    "Sales Manager hit MaxTurnsExceeded (max_turns=%s env SDR_MAX_TURNS=%r)",
                    max_turns,
                    os.environ.get("SDR_MAX_TURNS"),
                )
                await _log(
                    "⚠️ Step limit reached (review loops + send used all allowed turns). "
                    "Raising SDR_MAX_TURNS or trying a shorter brief may help."
                )
                return {
                    "recipient_email": recipient,
                    "steps": steps,
                    "final_output": None,
                    "last_agent": getattr(agent, "name", "Sales Manager"),
                    "error": "max_turns_exceeded",
                }

        await _log("🎉 Workflow completed successfully!")

        return {
            "recipient_email": recipient,
            "steps": steps,
            "final_output": _out(result.final_output),
            "last_agent": result.last_agent.name,
        }
    finally:
        steps_reset(ctx_tok)

