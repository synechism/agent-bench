import { inspectRepoTool, summarizeContextTool } from "./mastra/tools";
import {
  researcherInstructions,
  verifierInstructions,
} from "./mastra/agents";
import {
  loadRuntimeRegistry,
  renderSkillListing,
  runDeclarativeHooks,
} from "./registry";
import type {
  AgentDefinition,
  Message,
  ParentContext,
  SkillDefinition,
  SubagentTranscript,
  ToolSpec,
} from "./types";

type ChildContext = {
  agentId: string;
  agentType: string;
  mode: "fresh" | "fork";
  systemPrompt: string;
  messages: Message[];
  tools: Record<string, ToolSpec>;
  skills: SkillDefinition[];
  developerContext: string;
  hookContext: string;
  hookIds: string[];
  state: {
    readFileState: Map<string, string>;
    discoveredSkillNames: Set<string>;
    parentContextVisible: boolean;
  };
};

const inspectRepo: ToolSpec = {
  id: "inspect-repo",
  description: inspectRepoTool.description,
  execute: async input => {
    const area =
      typeof input === "object" && input !== null && "area" in input
        ? String(input.area)
        : "unknown";

    return {
      files:
        area === "subagents"
          ? [
              "src/tools/AgentTool/AgentTool.tsx",
              "src/tools/AgentTool/runAgent.ts",
              "src/tools/AgentTool/forkSubagent.ts",
            ]
          : ["README.md", "src/index.ts"],
      note: `Inventory generated for ${area}.`,
    };
  },
};

const summarizeContext: ToolSpec = {
  id: "summarize-context",
  description: summarizeContextTool.description,
  execute: async input => {
    const layerNames =
      typeof input === "object" && input !== null && "layerNames" in input
        ? input.layerNames
        : [];
    const names = Array.isArray(layerNames) ? layerNames.map(String) : [];

    return { summary: `Visible layers: ${names.join(", ")}` };
  },
};

const toolsById: Record<string, ToolSpec> = {
  "inspect-repo": inspectRepo,
  "summarize-context": summarizeContext,
};

export const agentRegistry: Record<string, AgentDefinition> = {
  "research-agent": {
    id: "research-agent",
    description: "Searches and summarizes relevant files from a self-contained brief.",
    instructions: researcherInstructions,
    tools: { "inspect-repo": inspectRepo, "summarize-context": summarizeContext },
    maxTurns: 4,
  },
  "verifier-agent": {
    id: "verifier-agent",
    description: "Checks a claim against supplied context.",
    instructions: verifierInstructions,
    tools: { "summarize-context": summarizeContext },
    maxTurns: 3,
  },
};

let nextAgentNumber = 1;

function createAgentId(agentType: string): string {
  return `${agentType}-${String(nextAgentNumber++).padStart(3, "0")}`;
}

function cloneMessages(messages: Message[]): Message[] {
  return messages.map(message => ({ ...message }));
}

function filterIncompleteToolCalls(messages: Message[]): Message[] {
  return messages.filter(message => {
    if (message.role !== "assistant") return true;
    return !message.content.includes("<incomplete_tool_call>");
  });
}

function buildForkDirectiveMessage(directive: string): Message {
  return {
    role: "user",
    name: "fork-directive",
    content: `<fork_boilerplate>
STOP. READ THIS FIRST.

You are a forked worker process. You are NOT the main agent.
Use the inherited context above, execute the directive directly, and return only scoped facts.
</fork_boilerplate>

<fork_directive>${directive}</fork_directive>`,
  };
}

function createSubagentContext(args: {
  agentId: string;
  agentType: string;
  mode: "fresh" | "fork";
  systemPrompt: string;
  messages: Message[];
  tools: Record<string, ToolSpec>;
  skills: SkillDefinition[];
  developerContext: string;
  hookContext: string;
  hookIds: string[];
  parentReadFileState: Map<string, string>;
  parentContextVisible: boolean;
}): ChildContext {
  return {
    agentId: args.agentId,
    agentType: args.agentType,
    mode: args.mode,
    systemPrompt: args.systemPrompt,
    messages: cloneMessages(args.messages),
    tools: { ...args.tools },
    skills: [...args.skills],
    developerContext: args.developerContext,
    hookContext: args.hookContext,
    hookIds: [...args.hookIds],
    state: {
      readFileState: new Map(args.parentReadFileState),
      discoveredSkillNames: new Set(),
      parentContextVisible: args.parentContextVisible,
    },
  };
}

async function runDeterministicChild(context: ChildContext): Promise<string> {
  const layerNames = [
    "systemPrompt",
    "messages",
    "tools",
    "skillRegistry",
    "readFileState",
    context.hookContext ? "hookContext" : "",
    context.state.parentContextVisible ? "parentConversation" : "parentBriefOnly",
  ].filter(Boolean);
  const contextSummary = await context.tools["summarize-context"]?.execute({
    layerNames,
  });

  const inventory = await context.tools["inspect-repo"]?.execute({
    area: "subagents",
  });

  return [
    `agentId=${context.agentId}`,
    `mode=${context.mode}`,
    `agentType=${context.agentType}`,
    `messageCount=${context.messages.length}`,
    `toolNames=${Object.keys(context.tools).join(",")}`,
    `skillNames=${context.skills.map(skill => skill.id).join(",")}`,
    `hookIds=${context.hookIds.join(",")}`,
    `developerContextChars=${context.developerContext.length}`,
    `hookContextChars=${context.hookContext.length}`,
    `parentContextVisible=${context.state.parentContextVisible}`,
    `contextSummary=${JSON.stringify(contextSummary)}`,
    `inventory=${JSON.stringify(inventory ?? "not available")}`,
  ].join("\n");
}

export async function spawnFreshSubagent(args: {
  parent: ParentContext;
  agentType: string;
  prompt: string;
}): Promise<SubagentTranscript> {
  const runtime = await loadRuntimeRegistry({
    toolsById,
    fallbackAgents: agentRegistry,
  });
  const definition = runtime.agents[args.agentType];
  if (!definition) {
    throw new Error(`Unknown agent type: ${String(args.agentType)}`);
  }

  const agentId = createAgentId(definition.id);
  const messages: Message[] = [{ role: "user", content: args.prompt }];
  const developerContext = renderSkillListing(runtime.skills);
  const subagentHooks = runDeclarativeHooks({
    hooks: runtime.hooks,
    event: "SubagentStart",
    scope: "subagent",
  });
  const childContext = createSubagentContext({
    agentId,
    agentType: definition.id,
    mode: "fresh",
    systemPrompt: definition.instructions,
    messages,
    tools: definition.tools,
    skills: runtime.skills,
    developerContext,
    hookContext: subagentHooks.context,
    hookIds: subagentHooks.hookIds,
    parentReadFileState: new Map([["parent-read-cache", "cloned"]]),
    parentContextVisible: false,
  });

  return {
    agentId,
    agentType: definition.id,
    mode: "fresh",
    systemPrompt: childContext.systemPrompt,
    messages: childContext.messages,
    toolNames: Object.keys(childContext.tools),
    skillNames: childContext.skills.map(skill => skill.id),
    hookIds: childContext.hookIds,
    developerContext: childContext.developerContext,
    hookContext: childContext.hookContext,
    result: await runDeterministicChild(childContext),
  };
}

export async function forkSubagent(args: {
  parent: ParentContext;
  directive: string;
}): Promise<SubagentTranscript> {
  const runtime = await loadRuntimeRegistry({
    toolsById,
    fallbackAgents: agentRegistry,
  });
  const agentId = createAgentId("fork");
  const messages = [
    ...filterIncompleteToolCalls(args.parent.messages),
    buildForkDirectiveMessage(args.directive),
  ];
  const developerContext = renderSkillListing(runtime.skills);
  const subagentHooks = runDeclarativeHooks({
    hooks: runtime.hooks,
    event: "SubagentStart",
    scope: "subagent",
  });

  const childContext = createSubagentContext({
    agentId,
    agentType: "fork",
    mode: "fork",
    systemPrompt: args.parent.renderedSystemPrompt,
    messages,
    tools: args.parent.tools,
    skills: runtime.skills,
    developerContext,
    hookContext: subagentHooks.context,
    hookIds: subagentHooks.hookIds,
    parentReadFileState: new Map([["parent-read-cache", "cloned"]]),
    parentContextVisible: true,
  });

  return {
    agentId,
    agentType: "fork",
    mode: "fork",
    systemPrompt: childContext.systemPrompt,
    messages: childContext.messages,
    toolNames: Object.keys(childContext.tools),
    skillNames: childContext.skills.map(skill => skill.id),
    hookIds: childContext.hookIds,
    developerContext: childContext.developerContext,
    hookContext: childContext.hookContext,
    result: await runDeterministicChild(childContext),
  };
}

export function createDemoParentContext(): ParentContext {
  return {
    renderedSystemPrompt: `You are the parent coordinator.
You have read the Claude Code subagent source and should keep raw worker output out of your own context.`,
    messages: [
      {
        role: "user",
        content:
          "Investigate how Claude Code injects context into subagents and prepare a Mastra POC.",
      },
      {
        role: "assistant",
        content:
          "I found AgentTool.tsx, runAgent.ts, and forkSubagent.ts. Fresh agents get prompts; forks inherit parent messages.",
      },
    ],
    tools: { ...toolsById },
  };
}
