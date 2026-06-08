import { Mastra } from "@mastra/core";
import { researchAgent, supervisorAgent, verifierAgent } from "./agents";

export const mastra = new Mastra({
  agents: { supervisorAgent, researchAgent, verifierAgent },
});

