import type { ParsedMaterialBundle, Portrait, Workflow, AResult, AOutputMetadata, Extraction, Assessment, MaterialFingerprint } from './src/contracts.js';

export function loadProjectEnv(input?: { env?: Record<string, string | undefined>; path?: string }): Promise<Record<string, string | undefined>>;
export const bundleSchema: Record<string, unknown>;
export const portraitSchema: Record<string, unknown>;
export function aResultSchema(rules: Record<string, unknown>): Record<string, unknown>;
export function validateAResult(bundle: ParsedMaterialBundle, aResult: AResult, rules: Record<string, unknown>): AResult;
export function materialFingerprints(bundle: ParsedMaterialBundle): MaterialFingerprint[];
export function buildAResult(input: { bundle: ParsedMaterialBundle; extraction: Extraction; rules: Record<string, unknown>; metadata: AOutputMetadata }): AResult;
export function validatePortrait(value: unknown): void;
export function validateBundle(value: unknown): ParsedMaterialBundle;
export function loadConfiguration(): Promise<{ rules: Record<string, unknown>; rubric: Record<string, unknown> }>;
export const runWorkflow: Workflow;
export function syntheticFixture(): Promise<{ bundle: ParsedMaterialBundle; extraction: Extraction; assessment: Assessment; rules: Record<string, unknown>; rubric: Record<string, unknown> }>;
export function syntheticPortrait(input: unknown): Promise<Portrait>;
