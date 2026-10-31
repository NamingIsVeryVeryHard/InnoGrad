import { bundleSchema } from '../../skills/graduate-portrait/scripts/schema.mjs';
import { portraitSchema } from '../../skills/graduate-portrait/scripts/portrait-schema.mjs';
import { validateShape, validateBundle } from '../../skills/graduate-portrait/scripts/validation.mjs';

export { loadProjectEnv } from '../../skills/graduate-portrait/scripts/env.mjs';

export { bundleSchema, portraitSchema, validateBundle };
export { aResultSchema, validateAResult, materialFingerprints, buildAResult } from '../../skills/graduate-portrait/scripts/handoff.mjs';
export const validatePortrait = value => validateShape(portraitSchema, value, 'portrait');

export async function loadConfiguration() {
  const workflow = await import('../../skills/graduate-portrait/scripts/workflow.mjs');
  return workflow.loadConfiguration();
}

export async function runWorkflow(input) {
  const { runPortraitWorkflow } = await import('../../skills/graduate-portrait/scripts/workflow.mjs');
  return runPortraitWorkflow(input);
}

export async function syntheticFixture() {
  const { fixture } = await import('../../skills/graduate-portrait/scripts/synthetic.mjs');
  return fixture();
}

export async function syntheticPortrait(input) {
  const { buildPortrait } = await import('../../skills/graduate-portrait/scripts/engine.mjs');
  return buildPortrait({ ...input, provenance: { mode: 'synthetic' } });
}
