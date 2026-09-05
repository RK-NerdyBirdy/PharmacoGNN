from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.explain import InteractionExplanation

logger = logging.getLogger(__name__)

# Graph-grounded RAG note: this prompt is deliberately defensive about the GNN
# score being a statistical signal (not ground truth) and about NOT inventing
# specific protein/gene identifiers or a fabricated xai_pathway. As of Phase 3,
# backend/weights has no drug-protein/protein-protein edge data (the same gap
# flagged in gnn_engine.py for Z_DRUG_CACHE), so `pathway` in the prompt context
# is always empty -- the model is instructed to reflect that honestly rather
# than filling in a plausible-looking graph.
_SYSTEM_PROMPT = """You are a clinical pharmacology explanation engine embedded in a \
polypharmacy risk-stratification clinical decision support system. You are given a \
machine-learning model's prediction for a drug-drug interaction -- a statistical signal \
from a graph neural network, not a confirmed clinical fact -- and must produce a \
structured explanation for clinicians and patients.

Rules:
- Only state pharmacological mechanisms that are well-established in clinical literature \
(e.g. CYP450 enzyme inhibition/induction, additive QT prolongation, receptor competition, \
pharmacokinetic or pharmacodynamic interaction classes). If you are not confident of the \
exact molecular mechanism for this specific pair, describe the most clinically recognized \
mechanism class for interactions producing this adverse effect in general terms, rather \
than inventing specific enzyme, gene, or protein identifiers you are not confident about.
- Do not fabricate specific protein/gene identifiers, study citations, or statistics beyond \
what you were given in the prompt.
- patient_summary must be written at approximately a 6th-grade reading level, in plain \
English, and must state the concern and what it means practically without causing undue \
alarm.
- actionable_guidance must be concrete and clinical (e.g. specific monitoring parameters, \
dose titration guidance, timing separation, labs to check), not generic phrases like \
"consult your doctor".
- severity_classification must be exactly one of: Contraindicated, Major, Moderate, Minor.
- You will be given a "pathway" object describing any known intermediate biological nodes. \
If it has no nodes, you MUST set xai_pathway.data_available to false and leave \
xai_pathway.nodes and xai_pathway.edges as empty lists -- never invent nodes or edges to \
fill in a graph that was not provided.
- Respond with ONLY a single JSON object matching the schema described in the user message. \
No prose outside the JSON, no markdown code fences.
"""

_USER_PROMPT_TEMPLATE = """Drug A: {drug_a_name} (CID {drug_a_cid})
Drug B: {drug_b_name} (CID {drug_b_cid})
GNN-predicted adverse effect: {adverse_effect}
GNN risk score (0-100): {risk_score:.1f}
Female-biased-ADR adjustment applied: {female_adjustment_applied}
Known intermediate biological pathway (if empty, do not invent one): {pathway_json}

Return a JSON object with exactly these keys:
- clinical_mechanism (string)
- severity_classification (one of "Contraindicated", "Major", "Moderate", "Minor")
- patient_summary (string)
- actionable_guidance (string)
- xai_pathway (object with "nodes" (list of {{"id", "label", "type"}}), "edges" (list of \
{{"source", "target", "label"}}), and "data_available" (bool))
"""


def _build_user_prompt(context: dict[str, Any]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        drug_a_name=context["drug_a_name"],
        drug_a_cid=context["drug_a_cid"],
        drug_b_name=context["drug_b_name"],
        drug_b_cid=context["drug_b_cid"],
        adverse_effect=context["adverse_effect"],
        risk_score=context["risk_score"],
        female_adjustment_applied=context["female_adjustment_applied"],
        pathway_json=json.dumps(context["pathway"]),
    )


async def explain_interaction(context: dict[str, Any]) -> InteractionExplanation:
    """Calls OpenRouter for a structured, graph-grounded interaction explanation.

    Raises RuntimeError if OPENROUTER_API_KEY is unset, the HTTP call fails, or the
    model's response doesn't parse into the required schema (retried once with a
    stricter follow-up before giving up).
    """
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(context)},
    ]

    async with httpx.AsyncClient(timeout=settings.OPENROUTER_TIMEOUT_SECONDS) as client:
        for attempt in range(2):
            content = await _call_openrouter(client, messages)
            try:
                return InteractionExplanation.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as exc:
                logger.warning(
                    "LLM explanation failed schema validation (attempt %d): %s\nraw content: %s",
                    attempt + 1,
                    exc,
                    content,
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That response did not match the required JSON schema "
                            f"({exc}). Return ONLY a corrected JSON object with exactly "
                            "the keys clinical_mechanism, severity_classification, "
                            "patient_summary, actionable_guidance, xai_pathway."
                        ),
                    }
                )

    raise RuntimeError("LLM returned a response that did not match the required schema after retrying")


async def _call_openrouter(client: httpx.AsyncClient, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": settings.OPENROUTER_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    try:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json=payload,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from exc
