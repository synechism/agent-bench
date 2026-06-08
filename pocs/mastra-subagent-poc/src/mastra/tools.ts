import { createTool } from "@mastra/core/tools";
import { z } from "zod";

export const inspectRepoTool = createTool({
  id: "inspect-repo",
  description: "Return a compact repository inventory for a target area.",
  inputSchema: z.object({
    area: z.string().describe("Repository area to inspect"),
  }),
  outputSchema: z.object({
    files: z.array(z.string()),
    note: z.string(),
  }),
  execute: async ({ area }) => ({
    files:
      area === "subagents"
        ? [
            "src/tools/AgentTool/AgentTool.tsx",
            "src/tools/AgentTool/runAgent.ts",
            "src/tools/AgentTool/forkSubagent.ts",
          ]
        : ["README.md", "src/index.ts"],
    note: `Inventory generated for ${area}.`,
  }),
});

export const summarizeContextTool = createTool({
  id: "summarize-context",
  description: "Summarize what context layers are visible to the current agent.",
  inputSchema: z.object({
    layerNames: z.array(z.string()),
  }),
  outputSchema: z.object({
    summary: z.string(),
  }),
  execute: async ({ layerNames }) => ({
    summary: `Visible layers: ${layerNames.join(", ")}`,
  }),
});

