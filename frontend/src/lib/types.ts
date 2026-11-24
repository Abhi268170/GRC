export type PlatformRole = "super_admin" | "tenant_admin" | "tenant_user";

export interface User {
  id: string;
  email: string;
  full_name: string;
  platform_role: PlatformRole;
  organisational_role_id: string | null;
  must_change_password: boolean;
  is_active: boolean;
  last_login_at: string | null;
}

export interface Tenant {
  id: string;
  name: string;
  industry: string | null;
  employee_count: string | null;
  /** The company details the user saved and the industry code (noga_*). */
  profile?: Record<string, unknown>;
}

export interface Me {
  user: User;
  tenant: Tenant | null;
}

export interface MasterDataCategory {
  key: string;
  label: string;
  group: string;
  description: string;
  /** How a control uses it: "one", "one_optional", "several", or "" when not on controls. */
  selection: "one" | "one_optional" | "several" | "";
  locked: boolean;
}

export type OrgRoleType = "executive" | "operational";

export interface OrganisationalRole {
  id: string;
  code: string;
  name: string;
  abbreviation: string;
  type: OrgRoleType;
  reports_to: string | null;
  description: string | null;
  purpose: string | null;
  accountabilities: string | null;
  responsibilities: string | null;
  decision_making_powers: string | null;
  interfaces: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface MasterDataItem {
  id: string;
  category: string;
  code: string;
  label: string;
  description: string | null;
  numeric_value: number | null;
  sort_order: number;
  is_active: boolean;
}

export interface DomainVersion {
  id: string;
  version: number;
  status: VersionStatus;
  name: string;
  description: string | null;
  published_at: string | null;
}

export type VersionStatus = "draft" | "published" | "deprecated";

export interface Domain {
  id: string;
  abbreviation: string;
  published: DomainVersion | null;
  draft: DomainVersion | null;
  control_count: number;
}

export interface ClauseRef {
  id: string;
  framework_code: string;
  ref: string;
  title: string;
}

/** Action item or risk template: title and description are both required. */
export interface Template {
  title: string;
  description: string;
}

export interface Requirement {
  requirement_id: string;
  code: string;
  statement: string;
  /** How to meet the requirement (evidence is what proves it). */
  guidance: string;
  mandatory: boolean | null;
  evidence: string[];
  action_templates: Template[];
  risk_templates: Template[];
  sort_order: number;
  clauses: ClauseRef[];
}

export interface Option {
  id: string;
  code: string;
  label: string;
  is_active: boolean;
}

/** Control text fields, in display order. */
export const CONTROL_TEXT_FIELDS = [
  ["short_description", "Short description", "Why the control is important."],
  ["key_requirement", "Key requirement", "One sentence on what the company must have in place."],
  ["risk_exposure", "Risk exposure", "The impact if the control isn't implemented."],
  ["involved_parties", "Involved parties", "Who takes part, e.g. top management, security team, legal."],
  ["triggers", "Triggers", "Events that call for the control, e.g. new business activities, mergers, new locations."],
  ["supporting_documents", "Supporting documents", "Documents that support the control, e.g. context analysis, scope statement."],
  ["special_considerations", "Special considerations", "Cases needing extra care, e.g. critical systems, external users, legal or contract requirements."],
  ["subject_specific_support", "Subject-specific support", "When specialist help is needed."],
] as const;
export type ControlTextField = (typeof CONTROL_TEXT_FIELDS)[number][0];

/** Several-per-control lists: API field -> master data category. */
export const CONTROL_MULTI_FIELDS = [
  ["control_types", "control_type", "Control type"],
  ["protection_domains", "protection_domain", "Protection domain"],
  ["security_capabilities", "security_capability", "Security capability"],
  ["protection_objectives", "protection_objective", "Protection objective"],
  ["use_cases", "use_case", "Use case"],
] as const;
export type ControlMultiField = (typeof CONTROL_MULTI_FIELDS)[number][0];

export type ControlVersion = {
  id: string;
  version: number;
  version_code: string;
  status: VersionStatus;
  domain_id: string;
  title: string;
  area: Option | null;
  company_risk_exposure: Option | null;
  responsible_role: { id: string; name: string; abbreviation: string } | null;
  published_at: string | null;
  missing_for_publish: string[];
  requirements: Requirement[];
} & Record<ControlMultiField, Option[]> & Record<ControlTextField, string | null>;

export interface ControlSummary {
  id: string;
  code: string;
  version_code: string;
  area: string | null;
  domain_id: string;
  title: string;
  version: number;
  status: VersionStatus;
  has_draft: boolean;
  imported: boolean;
  requirement_count: number;
  frameworks: string[];
}

export interface ControlDetail {
  id: string;
  code: string;
  domain_locked: boolean;
  versions: { id: string; version: number; version_code: string; status: VersionStatus; published_at: string | null }[];
  published: ControlVersion | null;
  draft: ControlVersion | null;
}

export type JobState = "none" | "pending" | "processing" | "done" | "failed";

export interface FrameworkVersion {
  id: string;
  version: number;
  version_label: string;
  status: VersionStatus;
  parse_status: JobState;
  parse_error: string | null;
  clause_count: number;
  published_at: string | null;
  has_source: boolean;
  /** Requirements (in any control version) mapped to this version's clauses. Mapped versions can't be deleted. */
  mapped_requirements: number;
}

export interface Framework {
  id: string;
  code: string;
  name: string;
  publisher: string | null;
  versions: FrameworkVersion[];
  mapped_requirements: number;
}

export interface Clause {
  id: string;
  parent_id: string | null;
  ref: string;
  title: string;
  description: string | null;
  level: number;
  sort_order: number;
  is_assessable: boolean;
  mapped_requirements: number;
}

export interface FrameworkVersionDetail {
  framework: Framework;
  version: FrameworkVersion;
  clauses: Clause[];
}

export interface ClauseSearchResult {
  id: string;
  framework_code: string;
  framework_name: string;
  ref: string;
  title: string;
}

export interface AssessmentVersionSummary {
  id: string;
  version: number;
  status: VersionStatus;
  title: string;
  description: string | null;
  generation_status: JobState;
  published_at: string | null;
  domain_count: number;
  control_count: number;
  question_count: number;
}

export interface AssessmentListItem {
  id: string;
  code: string;
  published: AssessmentVersionSummary | null;
  draft: AssessmentVersionSummary | null;
  run_count: number;
}

export interface BuilderQuestion {
  id: string;
  text: string;
  help_text: string | null;
  sort_order: number;
  origin: "ai_generated" | "ai_generated_edited" | "manual";
  requirement_ids: string[];
}

export interface BuilderDomain {
  id: string;
  domain_id: string;
  name: string;
  sort_order: number;
  controls: {
    control_id: string;
    control_version_id: string;
    code: string;
    title: string;
    version: number;
    requirements: { id: string; code: string; statement: string; mandatory: boolean | null }[];
  }[];
  questions: BuilderQuestion[];
}

export interface AssessmentVersionDetail {
  id: string;
  assessment_id: string;
  code: string;
  version: number;
  status: VersionStatus;
  title: string;
  description: string | null;
  generation_status: JobState;
  published_at: string | null;
  domains: BuilderDomain[];
  coverage: { total: number; covered: number; uncovered: string[] };
  latest_job: { id: string; type: string; status: string; error: string | null } | null;
  other_versions: AssessmentVersionSummary[];
  control_updates: { control_id: string; code: string; title: string; current: string; latest: string }[];
}

export interface CatalogItem {
  assessment_id: string;
  version_id: string;
  version: number;
  title: string;
  description: string | null;
  published_at: string | null;
  domains: string[];
  control_count: number;
  question_count: number;
  frameworks: string[];
}

export interface Notification {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

// ---------- runs ----------

export type RunStatus = "intake" | "in_progress" | "generating_outputs" | "in_review" | "changes_requested" | "approved";
export type DomainStatus = "not_started" | "in_progress" | "completed" | "changes_requested";
export interface Person { id: string; full_name: string }

export interface RunSummary {
  id: string;
  title: string;
  status: RunStatus;
  version: number;
  version_deprecated: boolean;
  started_by: Person;
  started_at: string | null;
  approved_at: string | null;
  progress: number;
  domains_total: number;
  domains_completed: number;
  score: number | null;
}

export interface RunDomainSummary {
  id: string;
  name: string;
  status: DomainStatus;
  assignee: Person | null;
  questions_total: number;
  questions_done: number;
  requirements_total: number;
  requirements_rated: number;
  requirements_verified: number;
  can_work: boolean;
  score: number | null;
  open_comments: number;
}

export interface IntakeQuestion { id: string; text: string; hint: string | null; options: string[] }

export interface RunDetail extends RunSummary {
  assessment_description: string | null;
  intake: { status: string; questions?: IntakeQuestion[]; answers?: Record<string, string>; context_summary?: string } | null;
  intake_job: string | null;
  outputs_job_status: string | null;
  outputs_job_error: string | null;
  domains: RunDomainSummary[];
  can_review: boolean;
  is_admin: boolean;
  ai_paused: boolean;
}

export interface Evaluation {
  id: string;
  rating: number | null;
  is_na: boolean;
  na_reason: string | null;
  rationale: string;
  ai_rating: number | null;
  ai_is_na: boolean | null;
  status: "awaiting_ai" | "ai_suggested" | "verified" | "overridden";
  verified_by: Person | null;
  answer: string | null;
  citations: { evidence_id: string | null; evidence_filename: string | null; response_id: string | null; excerpt: string | null }[];
}

export interface RequirementState {
  id: string;
  key: string;
  control: string;
  statement: string;
  guidance: string;
  evidence: string[];
  mandatory: boolean | null;
  clauses: { framework_code: string; ref: string; title: string }[];
  evaluation: Evaluation | null;
}

export interface QuestionState {
  id: string;
  kind: "base" | "follow_up";
  parent_id: string | null;
  text: string;
  help_text: string | null;
  status: "pending" | "answered" | "skipped_na";
  proposed_na: boolean;
  proposed_na_reason: string | null;
  requirement_keys: string[];
  answer: string | null;
}

export interface EvidenceFile {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  processing_status: "pending" | "processing" | "ready" | "failed";
  summary: string | null;
  uploaded_by: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system_event";
  content: string;
  data: Record<string, unknown> | null;
  author: Person | null;
  created_at: string;
}

export interface Workspace {
  run_id: string;
  run_status: RunStatus;
  domain: RunDomainSummary;
  current_question_id: string | null;
  questions: QuestionState[];
  requirements: RequirementState[];
  messages: ChatMessage[];
  evidence: EvidenceFile[];
  comments: { id: string; comment: string; created_at: string; resolved: boolean; author: string }[];
  editable: boolean;
  ai_paused: boolean;
  analysis_pending: boolean;
}

export interface ActionItem {
  id: string;
  title: string;
  description: string | null;
  status: "suggested" | "open" | "in_progress" | "done" | "dismissed";
  priority: "low" | "medium" | "high" | "critical" | null;
  owner: Person | null;
  due_date: string | null;
  requirement_keys: string[];
  run_id?: string | null;
  run_title?: string | null;
}

export interface RiskItem {
  id: string;
  title: string;
  description: string | null;
  status: "suggested" | "open" | "mitigating" | "accepted" | "closed" | "dismissed";
  category: string | null;
  likelihood: number;
  impact: number;
  score: number;
  treatment: "mitigate" | "accept" | "transfer" | "avoid" | null;
  owner: Person | null;
  requirement_keys: string[];
  run_id?: string | null;
  run_title?: string | null;
}

export interface ReportDomain {
  name: string;
  score: number | null;
  weakest_link: boolean;
  summary?: string;
  strengths?: string[];
  gaps?: string[];
  score_explanation?: string;
  requirements: { key: string; control: string; statement: string; rating: number | null; na: boolean; rationale: string | null }[];
}

export interface Report {
  title: string;
  version: number;
  company: { name: string; industry: string | null; employees: string | null };
  generated_at: string;
  overall: { score: number | null; explanation: string };
  executive_summary: string;
  frameworks: { name: string; pct: number | null; covered: number; considered: number }[];
  domains: ReportDomain[];
}

export interface Results {
  report: Report | null;
  report_status: "draft" | "final" | null;
  actions: ActionItem[];
  risks: RiskItem[];
}

// ---------- control import ----------

export interface ImportIssue {
  level: "error" | "warning";
  sheet: string | null;
  row: number | null;
  column: string | null;
  value: string | null;
  message: string;
  suggestion: string | null;
  control: string | null;
}

export interface ImportFieldChange { field: string; before: string; after: string }

export interface ImportRequirementChange {
  code: string | null;
  position: number;
  status: "added" | "changed" | "moved" | "unchanged";
  statement: string;
  changes: ImportFieldChange[];
  moved_from?: number | null;
}

export type ImportControlStatus = "new" | "changed" | "unchanged" | "conflict" | "invalid";

export interface ImportControl {
  ref: string;
  row: number;
  code: string | null;
  expected_code: string | null;
  title: string;
  domain: string;
  status: ImportControlStatus;
  has_draft: boolean;
  base: string | null;
  fields: ImportFieldChange[];
  requirements: ImportRequirementChange[];
  removals: { code: string; statement: string }[];
  publish_missing: string[];
}

export interface ImportSummary {
  new: number; changed: number; unchanged: number; conflicts: number; invalid: number;
  errors: number; warnings: number; removals: number; created?: number; updated?: number;
}

export interface ImportChoices { conflicts: Record<string, "overwrite" | "skip">; removals: string[] }

export interface ControlImport {
  id: string;
  filename: string;
  status: "preview" | "applied" | "expired";
  created_at: string;
  created_by: string;
  applied_at: string | null;
  summary: ImportSummary;
  report: { issues: ImportIssue[]; controls: ImportControl[] };
  choices: Partial<ImportChoices>;
  blockers: string[];
  drafts: { control_id: string; code: string; version_code: string; title: string; status: VersionStatus }[];
}

export type ControlImportListItem = Pick<ControlImport, "id" | "filename" | "status" | "created_at" | "created_by" | "applied_at" | "summary">;

/** One NOGA 2025 industry code (six digits) with the section and division it belongs to. */
export interface NogaCandidate {
  code: string;
  label_en: string;
  label_de: string;
  section: string;
  section_label_en: string;
  division: string;
  division_label_en: string;
  confidence: "high" | "medium" | "low" | null;
}

/** A company found in the commercial register. */
export interface CompanyHit {
  uid: string;
  name: string;
  legal_seat: string | null;
  legal_form: string | null;
}

export interface CompanySearch {
  results: CompanyHit[];
  too_many: boolean;
}

/** One company from the register with what public sources added. */
export interface CompanyProfile {
  uid: string;
  name: string;
  legal_form: string | null;
  legal_seat: string | null;
  canton: string | null;
  purpose: string | null;
  address: { street: string | null; house_number: string | null; zip: string | null; city: string | null };
  address_line: string;
  website: string | null;
  employees: number | null;
  employees_year: number | null;
  employee_range: string | null;
  industries: NogaCandidate[];
  sources: string[];
}

/** What a company says about itself. Every field is optional and the user can change it. */
export interface CompanyDetails {
  registration_number: string | null;
  legal_form: string | null;
  street: string | null;
  house_number: string | null;
  zip: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  website: string | null;
  description: string | null;
}

/** The company profile page: GET and PUT /company/profile. */
export interface CompanyProfileData {
  name: string;
  industry: string | null;
  noga: NogaCandidate | null;
  employee_count: string | null;
  details: CompanyDetails;
  /** When a workspace admin confirmed the details (needed once, before the first assessment). */
  verified_at: string | null;
  verified_by: string | null;
  /** Labels of what still has to be filled in before the details can be confirmed. */
  missing: string[];
}
