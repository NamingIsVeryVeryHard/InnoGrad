import { bundleSchema } from '../../../.agents/skills/graduate-portrait/scripts/schema.mjs';
import { portraitSchema } from '../../../.agents/skills/graduate-portrait/scripts/portrait-schema.mjs';
import { validateShape, validateBundle } from '../../../.agents/skills/graduate-portrait/scripts/validation.mjs';

export { bundleSchema, portraitSchema, validateBundle };
export { aResultSchema, validateAResult, materialFingerprints, buildAResult } from '../../../.agents/skills/graduate-portrait/scripts/handoff.mjs';
export const validatePortrait = value => validateShape(portraitSchema, value, 'portrait');

export async function loadConfiguration() {
  const workflow = await import('../../../.agents/skills/graduate-portrait/scripts/workflow.mjs');
  return workflow.loadConfiguration();
}

export async function runWorkflow(input) {
  const { runPortraitWorkflow } = await import('../../../.agents/skills/graduate-portrait/scripts/workflow.mjs');
  return runPortraitWorkflow(input);
}

export async function syntheticFixture() {
  const { fixture } = await import('../../../.agents/skills/graduate-portrait/scripts/synthetic.mjs');
  return fixture();
}

export async function syntheticPortrait(input) {
  const { buildPortrait } = await import('../../../.agents/skills/graduate-portrait/scripts/engine.mjs');
  return buildPortrait({ ...input, provenance: { mode: 'synthetic' } });
}
