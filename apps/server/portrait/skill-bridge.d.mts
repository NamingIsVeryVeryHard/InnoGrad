import type { ParsedMaterialBundle, Portrait, Workflow } from './src/contracts.js';

export const bundleSchema: Record<string, unknown>;
export const portraitSchema: Record<string, unknown>;
export function validatePortrait(value: unknown): void;
export function validateBundle(value: unknown): ParsedMaterialBundle;
export function loadConfiguration(): Promise<{ rules: Record<string, unknown>; rubric: Record<string, unknown> }>;
export const runWorkflow: Workflow;
export function syntheticFixture(): Promise<{ bundle: ParsedMaterialBundle; [key: string]: unknown }>;
export function syntheticPortrait(input: unknown): Promise<Portrait>;
