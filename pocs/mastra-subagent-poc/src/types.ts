export type Role = "system" | "user" | "assistant" | "tool";

export type Message = {
  role: Role;
  content: string;
  name?: string;
};

export type ToolSpec = {
  id: string;
  description: string;
  execute(input: unknown): Promise<unknown>;
};

export type SkillDefinition = {
  id: string;
  name: string;
  description: string;
  baseDir: string;
  bodyPath: string;
};

export type HookDefinition = {
  id: string;
  event: "SessionStart" | "SubagentStart" | "SubagentStop";
  appliesTo: "parent" | "subagent" | "both";
  additionalContext: string;
};

export type AgentDefinition = {
  id: string;
  description: string;
  instructions: string;
  tools: Record<string, ToolSpec>;
  source?: string;
  maxTurns?: number;
};

export type ParentContext = {
  renderedSystemPrompt: string;
  messages: Message[];
  tools: Record<string, ToolSpec>;
};

export type SubagentTranscript = {
  agentId: string;
  agentType: string;
  mode: "fresh" | "fork";
  systemPrompt: string;
  messages: Message[];
  toolNames: string[];
  skillNames: string[];
  hookIds: string[];
  developerContext: string;
  hookContext: string;
  result: string;
};
