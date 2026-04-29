/**
 * Mastra registry — central place to wire agents, tools, workflows.
 * The orchestrator agent is exported here for use by the API layer.
 */
import { Mastra } from '@mastra/core';
import { plannerAgent } from './agents/planner.js';

export const mastra = new Mastra({
  agents: { plannerAgent },
});

export { plannerAgent };
