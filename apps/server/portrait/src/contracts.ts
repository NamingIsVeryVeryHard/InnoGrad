export interface ParsedMaterialBundle {
  schema_version: '1.0';
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
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

// Nested result fields are governed by the Skill's shared JSON schema.
export interface Portrait extends Record<string, unknown> {
  schema_version: '1.0';
  student_id: string;
  period: string | null;
  stage: 'annual' | 'proposal';
  run_id: string;
  review_status: 'draft';
}

export type Workflow = (input: { bundle: ParsedMaterialBundle; signal: AbortSignal }) => Promise<Portrait>;

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
