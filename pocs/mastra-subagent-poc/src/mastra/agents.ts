import { Agent } from "@mastra/core/agent";
import { inspectRepoTool, summarizeContextTool } from "./tools";

export const researcherInstructions = `You are a fresh research subagent.
You receive only the prompt supplied by the parent plus your own instructions.
Do not assume you have seen the parent conversation. Report concise findings.`;

export const verifierInstructions = `You are a verification subagent.
Check whether a claim is supported by the context you were given. Be terse and concrete.`;

export const supervisorInstructions = `You are the parent coordinator.
You can delegate work to specialist subagents. For fresh subagents, write a self-contained prompt.
For forked workers, provide a directive because they inherit the parent context.`;

const model = process.env.MASTRA_MODEL ?? "openai/gpt-5-nano";

export const researchAgent = new Agent({
  id: "research-agent",
  name: "Research Agent",
  description: "Searches and summarizes relevant files from a self-contained brief.",
  instructions: researcherInstructions,
  model,
  tools: { inspectRepoTool, summarizeContextTool },
});

export const verifierAgent = new Agent({
  id: "verifier-agent",
  name: "Verifier Agent",
  description: "Checks a claim against supplied context and reports supported/unsupported.",
  instructions: verifierInstructions,
  model,
  tools: { summarizeContextTool },
});

export const supervisorAgent = new Agent({
  id: "supervisor-agent",
  name: "Supervisor Agent",
  description: "Parent coordinator with access to research and verification subagents.",
  instructions: supervisorInstructions,
  model,
  agents: { researchAgent, verifierAgent },
  tools: { summarizeContextTool },
});

