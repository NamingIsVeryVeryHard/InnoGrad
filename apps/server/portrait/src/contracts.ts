export interface ParsedMaterialBundle {
  schema_version: '1.0';
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
  task_context?: TaskContext;
  documents: {
    document_id: string;
    source_name: string;
    sha256: string;
    kind: 'annual' | 'proposal' | 'assessment' | 'supporting';
    student_id: string;
    period: string | null;
    parse_status: 'complete' | 'partial' | 'failed';
    segments: { segment_id: string; page: number | null; text: string }[];
  }[];
}

export interface TaskContext {
  task_id: string | null;
  observation_period: string | null;
  training_category: string | null;
  training_year: number | null;
  support_conditions: string | null;
}

export interface EvidenceRef {
  document_id: string;
  segment_id: string;
  quote: string;
}

export interface LocatedEvidence extends EvidenceRef {
  source_name: string;
  sha256: string;
  page: number | null;
}

export type EvidenceState = 'evaluable' | 'insufficient' | 'conflicting' | 'not_applicable';
export type PerformanceGrade = 'needs_improvement' | 'meets_requirements' | 'well_demonstrated';
export type WorkStatus = 'planned' | 'in_progress' | 'completed' | 'unknown';

export interface CriterionAssessment {
  criterion_id: string;
  evidence_state: EvidenceState;
  performance_grade: PerformanceGrade | null;
  standard_status: 'applicable' | 'pending_confirmation' | 'not_applicable';
  work_status: WorkStatus;
  observed: string;
  rationale: string;
  evidence: (EvidenceRef & { supports: string })[];
  evidence_nature: 'observed' | 'self_report' | 'mixed' | 'unknown';
  contribution: { individual: string | null; guidance: string | null; tools: string | null };
  limitations: string[];
  missing_evidence: string[];
  suggestions: string[];
}

export interface Assessment {
  schema_version: '2.0';
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
  rubric_version: string;
  dimensions: { dimension_id: string; criteria: CriterionAssessment[] }[];
}

export interface PortraitCriterion extends Omit<CriterionAssessment, 'evidence'> {
  criterion_label: string;
  evidence: (LocatedEvidence & { supports: string })[];
  review: {
    status: 'pending';
    reviewer: null;
    reviewed_at: null;
    modification_reason: null;
    independent_corroboration: 'unverified';
  };
}

export interface Portrait {
  schema_version: '2.0';
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
  run_id: string;
  review_status: 'draft';
  warnings: string[];
  task_context: TaskContext | null;
  explicit_status: 'pending' | 'local_pipeline' | 'merged';
  a_handoff: AHandoffMetadata | null;
  provenance: {
    producer: { mode: ProducerMode; model: string | null; description: string | null };
    hashes: {
      input: string; extraction: string | null; assessment: string; rules: string; rubric: string; skill: string; a_result: string | null;
    };
    versions: { schema: string; rules: string; rubric: string; skill: string };
  };
  sources: {
    document_id: string; source_name: string; sha256: string;
    parse_status: 'complete' | 'partial' | 'failed';
    pages: { segment_id: string; page: number | null }[];
  }[];
  explicit: ExplicitResult | null;
  implicit: {
    rubric_version: string; status: string; interpretation: string;
    dimensions: {
      id: string; label: string; criteria: PortraitCriterion[];
      summary: { criterion_ids: string[]; text: string }[];
      review_required: true;
    }[];
  };
}

export type ProducerMode = 'offline_replay' | 'synthetic' | 'assistant_curated' | 'skill_execution' | 'remote_model';
export type NumericQualifier = 'exact' | 'lower_bound' | 'approximate';
export type ItemStatus = 'planned' | 'in_progress' | 'under_review' | 'accepted' | 'published' | 'completed' | 'unknown';
export type PeriodStatus = 'in_scope' | 'out_of_scope' | 'uncertain';
export type ListingCoverage = 'complete' | 'partial' | 'not_reported';

export interface Fact {
  field: string;
  value: string | number;
  qualifier: NumericQualifier;
  numeric_token: string | null;
  evidence: EvidenceRef[];
}
export interface ExtractedItem {
  item_id: string; kind: string; title: string; status: ItemStatus;
  role: string | null; identifier: string | null; occurred_on: string | null;
  period_status: PeriodStatus; evidence: EvidenceRef[];
}
export interface Extraction {
  schema_version: '1.0'; student_id: string; period: string | null; stage: 'annual' | 'proposal';
  facts: Fact[]; items: ExtractedItem[];
  coverage: { kind: string; status: ListingCoverage; evidence: EvidenceRef[] }[];
}
export interface RuleCheck {
  rule_version: string;
  applicable_scope: { student_id: string; period: string | null; stage: 'annual' | 'proposal' };
  input_evidence: EvidenceRef[];
  id: string; label: string; kind: 'minimum' | 'consistency' | 'material_comparison';
  source: string | null; metric: string;
  status: 'not_applicable' | 'period_unconfirmed' | 'pending_rule' | 'needs_review' | 'insufficient_evidence' | 'met' | 'not_met' | 'consistent';
  threshold?: number | null; observed?: number | null; qualifier?: NumericQualifier;
  reference?: number | null; interpretation?: string; self_report?: number; listed?: number;
  listing_coverage?: ListingCoverage;
}
export interface ExplicitResult {
  overall_score: null;
  metrics: Record<string, {
    label: string; unit: string | null; value: string | number | null;
    qualifier: NumericQualifier | null; status: 'conflict' | 'observed' | 'not_observed';
    verification: 'material_report'; observations: Fact[];
  }>;
  ledger: Record<string, Record<string, number | null>>;
  ledger_details: Record<string, {
    coverage: ListingCoverage; declared_coverage: ListingCoverage; partial_source: boolean;
    counts: Record<string, {
      listed: number; value: number | null; qualifier: 'exact' | 'lower_bound';
      status: 'conflict' | 'complete_listing' | 'partial_listing' | 'not_observed';
    }>;
    excluded_item_ids: string[];
  }>;
  item_conflicts: { kind: string; item_ids: string[]; statuses: ItemStatus[]; period_statuses: PeriodStatus[] }[];
  potential_duplicates: { kind: string; item_ids: string[]; status: 'needs_review'; reason: string }[];
  items: { kind: string; item_ids: string[]; records: ExtractedItem[] }[];
  checks: RuleCheck[];
  groups: { id: string; label: string; fields: string[]; item_kinds: string[] }[];
}

export interface MaterialFingerprint {
  document_id: string;
  sha256: string;
  content_sha256: string;
}
export interface AProducer {
  mode: ProducerMode;
  name: string | null;
  model: string | null;
}
export interface AOutputMetadata {
  output_version: string;
  generated_at: string;
  producer: AProducer;
}
export interface AHandoffMetadata extends AOutputMetadata {
  schema_version: 'a-handoff-1.0';
  material_fingerprints: MaterialFingerprint[];
  rules_version: string;
}
export interface AResult extends AHandoffMetadata {
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
  task_id: string | null;
  task_context_sha256: string;
  extraction: Extraction;
  explicit: ExplicitResult;
}

export type WorkflowMode = 'implicit_only' | 'bundle_pipeline';

export interface PortraitRequest {
  bundle: ParsedMaterialBundle;
  mode?: WorkflowMode;
  aResult?: AResult;
}

export type Workflow = (input: PortraitRequest & { signal: AbortSignal }) => Promise<Portrait>;

export interface PublicError {
  code: string;
  message: string;
}

export interface PortraitJob {
  id: string;
  status: 'running' | 'completed' | 'failed';
  createdAt: string;
  expiresAt: string;
  completedAt?: string;
  portrait?: Portrait;
  error?: PublicError;
}
