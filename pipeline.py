"""Agents + one async runner. Env: OPENAI_API_KEY, DEEPSEEK_API_KEY, SENDGRID_*."""

from __future__ import annotations

import os
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

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


class DraftReview(BaseModel):
    accept: bool = Field(description="True if the draft is ready to send; False otherwise.")
    feedback: str = Field(description="Rationale and concrete suggestions.")


class NameCheckOutput(BaseModel):
    is_name_in_message: bool
    name: str


INSTRUCTIONS1 = """You are a sales agent working for ComplAI, \
a company that provides a SaaS tool for ensuring SOC2 compliance and preparing for audits, powered by AI. \
You write professional, serious cold emails without subject lines only the email body."""

INSTRUCTIONS2 = """You are a humorous, engaging sales agent working for ComplAI, \
a company that provides a SaaS tool for ensuring SOC2 compliance and preparing for audits, powered by AI. \
You write witty, engaging cold emails without subject lines only the email body that are likely to get a response."""

INSTRUCTIONS3 = """You are a busy sales agent working for ComplAI, \
a company that provides a SaaS tool for ensuring SOC2 compliance and preparing for audits, powered by AI. \
You write concise, to the point cold emails without subject lines only the email body."""

ANALYSER_INSTRUCTIONS = """You are a quality reviewer for outbound cold emails at ComplAI (SOC2 / audit-compliance SaaS).

You receive the user's request, the three draft bodies, which draft was chosen, and optional rationale.
Decide if the chosen draft is clear, professional, and on-brief. Output only structured accept + feedback."""

SALES_MANAGER_INSTRUCTIONS = """
You are a Sales Manager at ComplAI. Use sales_agent1, sales_agent2, sales_agent3 to get three drafts (body only, no subject).
Pick the best, call review_draft_email with the user's request, all three drafts, chosen number (1–3), winning body, and rationale.
If accept is true, hand off the winning body to Email Manager via transfer_to_email_manager. If accept is false, revise and review again (at most two rounds), then hand off if needed per your judgment.
"""


def _review_tool_output(output: RunResult) -> Any:
    fo = output.final_output
    if fo is not None and hasattr(fo, "model_dump_json"):
        return fo.model_dump_json()
    text = ItemHelpers.text_message_outputs(output.new_items)
    return text if text else str(fo)


async def _review_tool_output_async(output: RunResult) -> str:
    return str(_review_tool_output(output))


def build_agents() -> tuple[Agent, Agent]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is required")

    deepseek_client = AsyncOpenAI(
        base_url=DEEPSEEK_BASE_URL,
        api_key=os.environ["DEEPSEEK_API_KEY"],
    )
    deepseek_model = OpenAIChatCompletionsModel(model="deepseek-chat", openai_client=deepseek_client)

    sales_agent1 = Agent(name="DeepSeek Sales Agent", instructions=INSTRUCTIONS1, model=deepseek_model)
    sales_agent2 = Agent(name="Gemini Sales Agent", instructions=INSTRUCTIONS2, model=deepseek_model)
    sales_agent3 = Agent(name="Llama3.3 Sales Agent", instructions=INSTRUCTIONS3, model=deepseek_model)

    td = "Write a cold sales email"
    tool1 = sales_agent1.as_tool(tool_name="sales_agent1", tool_description=td)
    tool2 = sales_agent2.as_tool(tool_name="sales_agent2", tool_description=td)
    tool3 = sales_agent3.as_tool(tool_name="sales_agent3", tool_description=td)

    analyser = Agent(
        name="Email draft analyser",
        instructions=ANALYSER_INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=DraftReview,
    )
    review_tool = analyser.as_tool(
        tool_name="review_draft_email",
        tool_description="Review draft choice; returns JSON with accept and feedback.",
        custom_output_extractor=_review_tool_output_async,
    )

    @function_tool
    def send_html_email(subject: str, html_body: str) -> dict[str, str]:
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        key = os.environ.get("SENDGRID_API_KEY")
        from_addr = os.environ.get("SENDGRID_FROM_EMAIL", "geekyoswald@gmail.com")
        to_addr = os.environ.get("SENDGRID_TO_EMAIL", "geekyoswald@gmail.com")
        if not key:
            raise RuntimeError("SENDGRID_API_KEY is not set")
        if not from_addr or not to_addr:
            raise RuntimeError("SENDGRID_FROM_EMAIL and SENDGRID_TO_EMAIL must be set")

        sg = sendgrid.SendGridAPIClient(api_key=key)
        mail = Mail(Email(from_addr), To(to_addr), subject, Content("text/html", html_body)).get()
        sg.client.mail.send.post(request_body=mail)
        return {"status": "success"}

    subj = Agent(
        name="Email subject writer",
        instructions="Write a compelling subject line for the given cold email body.",
        model="gpt-4o-mini",
    )
    html = Agent(
        name="HTML email body converter",
        instructions="Convert the email body to simple, clear HTML.",
        model="gpt-4o-mini",
    )
    subject_tool = subj.as_tool(tool_name="subject_writer", tool_description="Write email subject")
    html_tool = html.as_tool(tool_name="html_converter", tool_description="Convert body to HTML")

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
        name="Name check",
        instructions="Check if the user message includes a person's name as the sender identity.",
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
        name="Sales Manager",
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
    sm, careful = build_agents()
    agent = careful if use_name_guardrail else sm
    name = os.environ.get("WORKFLOW_TRACE_NAME", "Automated SDR")
    with trace(name):
        result = await Runner.run(agent, message)
    return {
        "final_output": _out(result.final_output),
        "last_agent": result.last_agent.name,
    }

