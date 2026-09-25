"""Knowledge-graph extraction: one Claude structured-output call per paper."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, Field

from paper_rag.ingest.pdf import PdfDocument

log = logging.getLogger(__name__)

EntityType = Literal["Method", "Model", "Dataset", "Task", "Metric", "Concept", "Field"]
RelationType = Literal[
    "PROPOSES", "USES", "EXTENDS", "EVALUATES_ON", "OUTPERFORMS", "ADDRESSES", "IS_A", "PART_OF", "RELATED_TO"
]
ENTITY_TYPES: tuple[str, ...] = EntityType.__args__  # type: ignore[attr-defined]
RELATION_TYPES: tuple[str, ...] = RelationType.__args__  # type: ignore[attr-defined]
THIS_PAPER = "THIS_PAPER"


class PaperMeta(BaseModel):
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    abstract: str
    summary: str = Field(description="2-3 plain sentences: the problem, the approach, the main finding.")


class Entity(BaseModel):
    name: str = Field(description="Canonical name. Reuse an existing corpus name verbatim when it is the same thing.")
    type: EntityType
    description: str = Field(description="One sentence, general (not paper-specific) definition.")
    aliases: list[str] = Field(description="Abbreviations or alternative spellings used in the paper.")


class Relation(BaseModel):
    source: str = Field(description=f"An entity name from `entities`, or {THIS_PAPER}.")
    target: str = Field(description=f"An entity name from `entities`, or {THIS_PAPER}.")
    type: RelationType
    evidence: str = Field(description="Short verbatim quote (under 30 words) supporting the relation.")
    page: int | None


class Extraction(BaseModel):
    paper: PaperMeta
    entities: list[Entity]
    relations: list[Relation]
    references: list[str] = Field(description="Titles of cited works, as written in the reference list.")


class Extractor(Protocol):
    def extract(self, doc: PdfDocument, known_entities: dict[str, list[str]]) -> Extraction: ...


class ExtractionError(RuntimeError):
    pass


SYSTEM_PROMPT = f"""You build a knowledge graph over a corpus of scientific papers. Given one paper's full text \
(with [page N] markers), extract:

- paper: bibliographic metadata and a short summary.
- entities: the 10-40 most important research entities: methods, models/architectures, datasets, tasks, \
metrics, key concepts and research fields. Prefer entities that other papers could plausibly share; skip \
paper-specific trivia (hyperparameters, figure names).
- relations: typed, directed relations between entities, or between {THIS_PAPER} and entities. Use \
{THIS_PAPER} as the source for what this paper PROPOSES, USES, EVALUATES_ON, ADDRESSES. Use OUTPERFORMS \
only for claims backed by reported results. Every relation needs a short verbatim evidence quote and its page.
- references: the titles of cited works from the reference list (titles only, no authors or venues).

Entity naming matters because graphs from many papers are merged by name. When an entity matches one \
already in the corpus (listed by the user), reuse that exact name. Otherwise use the most standard full name \
and put abbreviations in aliases (e.g. name "Retrieval-Augmented Generation", aliases ["RAG"])."""


def _known_entities_block(known: dict[str, list[str]], per_type: int = 150) -> str:
    if not any(known.values()):
        return "The corpus has no entities yet."
    lines = ["Entities already in the corpus (reuse these names when they match):"]
    for etype, names in known.items():
        if names:
            lines.append(f"- {etype}: " + "; ".join(names[:per_type]))
    return "\n".join(lines)


class ClaudeExtractor:
    def __init__(self, model: str, client: anthropic.Anthropic | None = None, max_tokens: int = 32000):
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.max_tokens = max_tokens

    def extract(self, doc: PdfDocument, known_entities: dict[str, list[str]]) -> Extraction:
        user = (
            f"{_known_entities_block(known_entities)}\n\n"
            f"<paper file=\"{doc.path.name}\" pdf_title=\"{doc.title_hint}\">\n{doc.text_with_page_markers()}\n</paper>"
        )
        # Streamed: long papers plus a large structured output can exceed non-streaming timeouts.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_format=Extraction,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise ExtractionError(f"Claude declined to extract {doc.path.name}")
        if response.stop_reason == "max_tokens":
            raise ExtractionError(f"Extraction for {doc.path.name} hit max_tokens")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            text = next((b.text for b in response.content if b.type == "text"), "")
            parsed = Extraction.model_validate_json(text)
        log.info(
            "Extracted %s: %d entities, %d relations, %d references (in=%d out=%d tokens)",
            doc.paper_id, len(parsed.entities), len(parsed.relations), len(parsed.references),
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return parsed
