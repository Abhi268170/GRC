"""Single-call tasks: one input model and one output model each.

The field descriptions on output models are part of the prompt: the model sees them."""

from typing import Literal

from pydantic import BaseModel, Field

from ai_contracts.common import Company, ControlContext, DomainScope, EvidenceFile, FileInput

# ---------- framework parsing: POST /v1/framework/parse ----------


class ParseFrameworkIn(BaseModel):
    framework_name: str
    version_label: str
    file: FileInput


class ParsedClause(BaseModel):
    ref: str = Field(description="The identifier exactly as written in the document, e.g. 'PR.AA-01' or 'A.5.15'.")
    title: str = Field(description="Clause title or, for clauses without a title, the full statement.")
    description: str | None = Field(description="Supporting text for the clause, if any. Null if none.")
    parent_ref: str | None = Field(description="ref of the parent clause; null for top-level items.")
    is_assessable: bool = Field(description="True for clauses an organisation can be assessed against; false for pure grouping headings (chapters, functions, categories).")


class ParsedFramework(BaseModel):
    clauses: list[ParsedClause]


# ---------- assessment questions: POST /v1/questions/generate, /v1/questions/tag ----------


class GenerateQuestionIn(BaseModel):
    domain: DomainScope


class DomainQuestion(BaseModel):
    text: str = Field(description="The domain's single opening question, in plain conversational English.")
    help_text: str = Field(description="A one-line intro, then exactly one '- ' bullet per control, then one short line on useful evidence.")


class TagQuestionIn(BaseModel):
    domain: DomainScope
    question_text: str
    help_text: str | None = None


class Tags(BaseModel):
    requirement_keys: list[str]


# ---------- pre-assessment intake: POST /v1/intake/questions, /v1/intake/tailor ----------


class IntakeIn(BaseModel):
    company: Company
    domains: list[DomainScope]


class IntakeQuestion(BaseModel):
    id: str = Field(description="Short id like i1, i2.")
    text: str = Field(description="A short, plain-English question.")
    hint: str | None = Field(description="Optional example answer or clarification.")
    options: list[str] = Field(description="Suggested quick answers (2-5) when the answer is usually one of a few options; empty for free text.")


class IntakeQuestions(BaseModel):
    questions: list[IntakeQuestion]


class IntakeAnswer(BaseModel):
    question: str
    answer: str | None = None


class KeyedQuestion(BaseModel):
    key: str  # Q1, Q2, ...
    text: str


class TailorDomainIn(BaseModel):
    name: str
    questions: list[KeyedQuestion]


class TailorIn(BaseModel):
    company: Company
    intake: list[IntakeAnswer]
    domains: list[TailorDomainIn]


class TailoredQuestion(BaseModel):
    key: str = Field(description="The question key you were given, e.g. Q3.")
    text: str = Field(description="The question reworded for this company. Keep its meaning and everything it asks about.")
    propose_na: bool = Field(description="True only if the intake answers make it very likely the whole question doesn't apply.")
    na_reason: str | None = Field(description="Why it likely doesn't apply, in one sentence. Null if propose_na is false.")


class TailoredDomain(BaseModel):
    domain: str = Field(description="The domain name exactly as given.")
    question_keys_in_order: list[str] = Field(description="Every question key of this domain, in the order to ask them.")


class Tailoring(BaseModel):
    context_summary: str = Field(description="Three to five sentences summarising the company's context relevant to this assessment.")
    questions: list[TailoredQuestion]
    domains: list[TailoredDomain]


# ---------- evidence: POST /v1/evidence/digest ----------


class EvidenceDigestIn(BaseModel):
    file: FileInput


class EvidenceDigest(BaseModel):
    summary: str = Field(description="Two to four sentences: what this document or image is and what it shows about the company's security practices (dates, owners, scope, approvals).")
    extracted_text: str | None = Field(description="For images or scanned documents only: a faithful transcription of the visible text and settings. Null when the text was already provided.")


# ---------- cross-analysis: POST /v1/cross-analysis ----------


class ExistingSuggestion(BaseModel):
    rating: int | None = None
    is_na: bool = False
    rationale: str = ""


class OpenRequirement(BaseModel):
    key: str
    statement: str
    guidance: str = ""
    evidence: list[str] = Field(default_factory=list)
    target: bool = False  # the requirement the answer was given for: it must always be rated
    existing: ExistingSuggestion | None = None  # an AI suggestion that is already there


class OpenControl(BaseModel):
    context: ControlContext
    requirements: list[OpenRequirement]


class OpenDomain(BaseModel):
    name: str
    controls: list[OpenControl]


class CrossAnalysisIn(BaseModel):
    company: Company
    domains: list[OpenDomain]  # only requirements that are still open
    source: Literal["chat", "requirement"]
    text: str | None = None
    evidence: list[EvidenceFile] = Field(default_factory=list)


class CrossRating(BaseModel):
    requirement: str = Field(description="Requirement key, e.g. R12.")
    rating: int | None = Field(description="0-4, or null when not applicable.")
    not_applicable: bool
    na_reason: str | None
    rationale: str = Field(description="One to three sentences citing what the answer or evidence shows, and what would raise the rating.")
    evidence_ids: list[str] = Field(description="Ids of the evidence files the rating relies on.")
    quote: str | None = Field(description="A short quote from the answer or evidence that the rating relies on.")


class CrossResult(BaseModel):
    ratings: list[CrossRating]


# ---------- results: POST /v1/results/narrative ----------


class RatedRequirement(BaseModel):
    key: str
    statement: str
    guidance: str = ""
    mandatory: bool | None = None
    rated: bool = True          # false: nobody rated it
    is_na: bool = False
    rating: int | None = None
    rationale: str = ""


class ResultControl(BaseModel):
    context: ControlContext
    requirements: list[RatedRequirement]


class ResultDomain(BaseModel):
    name: str
    score: float | None = None
    has_zero_rating: bool = False
    controls: list[ResultControl]


class FrameworkCoverage(BaseModel):
    name: str
    pct: float
    covered: int
    considered: int


class TemplateSlot(BaseModel):
    """An action or risk template from the control library, for a requirement rated below target."""

    id: str               # A1, A2, ... for actions; K1, K2, ... for risks
    requirement_key: str
    rating: int
    title: str
    description: str


class ResultsIn(BaseModel):
    company: Company
    assessment_title: str
    overall_score: float | None = None
    domains: list[ResultDomain]
    frameworks: list[FrameworkCoverage] = Field(default_factory=list)
    action_templates: list[TemplateSlot] = Field(default_factory=list)
    risk_templates: list[TemplateSlot] = Field(default_factory=list)
    gaps_without_action_template: list[str] = Field(default_factory=list)  # requirement keys
    gaps_without_risk_template: list[str] = Field(default_factory=list)


class DomainNarrative(BaseModel):
    domain: str
    summary: str = Field(description="Two to three sentences on this domain's state.")
    strengths: list[str]
    gaps: list[str]
    score_explanation: str = Field(description="One or two sentences explaining the calculated score (which requirements pulled it up or down).")


class SuggestedAction(BaseModel):
    title: str = Field(description="Imperative, specific, e.g. 'Enforce MFA for all admin accounts'.")
    description: str = Field(description="What to do and what 'done' looks like.")
    priority: str = Field(description="One of: low, medium, high, critical.")
    requirement_keys: list[str]


class SuggestedRisk(BaseModel):
    title: str
    description: str = Field(description="The risk scenario: what could happen, why, and the impact.")
    category: str = Field(description="One of: security, compliance, operational, third_party, data_privacy.")
    likelihood: int = Field(description="1 (rare) to 5 (almost certain).")
    impact: int = Field(description="1 (negligible) to 5 (severe).")
    requirement_keys: list[str]


class AdaptedAction(BaseModel):
    template_id: str = Field(description="The action template id, e.g. A3.")
    title: str = Field(description="The template's title adapted to the company: imperative and specific.")
    description: str = Field(description="The template's description adapted to the company: what to do and what 'done' looks like.")
    priority: str = Field(description="One of: low, medium, high, critical.")


class AdaptedRisk(BaseModel):
    template_id: str = Field(description="The risk template id, e.g. K2.")
    title: str
    description: str = Field(description="The template's risk adapted to the company: what could happen, why, and the impact.")
    category: str = Field(description="One of: security, compliance, operational, third_party, data_privacy.")
    likelihood: int = Field(description="1 (rare) to 5 (almost certain).")
    impact: int = Field(description="1 (negligible) to 5 (severe).")


class Narrative(BaseModel):
    executive_summary: str = Field(description="One short paragraph for leadership: overall posture, the most important gaps, and what to do first.")
    overall_explanation: str = Field(description="One or two sentences explaining the overall calculated score.")
    domains: list[DomainNarrative]
    adapted_actions: list[AdaptedAction] = Field(description="Exactly one per action template listed.")
    adapted_risks: list[AdaptedRisk] = Field(description="Exactly one per risk template listed.")
    action_items: list[SuggestedAction] = Field(description="New action items, only for gaps listed as having no action template.")
    risks: list[SuggestedRisk] = Field(description="New risks, only for gaps listed as having no risk template.")


# ---------- industry classification: POST /v1/noga/classify ----------


class NogaClassifyIn(BaseModel):
    """What a company does, in any language: usually the purpose clause from the commercial register."""

    text: str = Field(min_length=3, max_length=20_000)
    company_name: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class NogaCandidate(BaseModel):
    """One NOGA 2025 code (six digits) with the section and division it belongs to."""

    code: str
    label_en: str
    label_de: str
    section: str            # "C"
    section_label_en: str
    section_label_de: str
    division: str           # "25"
    division_label_en: str
    division_label_de: str
    confidence: Literal["high", "medium", "low"] | None = None  # only on codes the model chose


class NogaRanking(BaseModel):
    candidates: list[NogaCandidate]  # best first; empty when the text doesn't say what the company does


__all__ = [
    "AdaptedAction", "AdaptedRisk", "CrossAnalysisIn", "CrossRating", "CrossResult", "DomainNarrative", "DomainQuestion",
    "EvidenceDigest", "EvidenceDigestIn", "ExistingSuggestion", "FrameworkCoverage", "GenerateQuestionIn", "IntakeAnswer",
    "IntakeIn", "IntakeQuestion", "IntakeQuestions", "KeyedQuestion", "Narrative", "NogaCandidate", "NogaClassifyIn",
    "NogaRanking", "OpenControl", "OpenDomain",
    "OpenRequirement", "ParseFrameworkIn", "ParsedClause", "ParsedFramework", "RatedRequirement", "ResultControl",
    "ResultDomain", "ResultsIn", "SuggestedAction", "SuggestedRisk", "TagQuestionIn", "Tags", "TailorDomainIn", "TailorIn",
    "TailoredDomain", "TailoredQuestion", "Tailoring", "TemplateSlot",
]
