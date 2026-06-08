import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import type {
  AgentDefinition,
  HookDefinition,
  SkillDefinition,
  ToolSpec,
} from "./types";

export type RuntimeRegistry = {
  agents: Record<string, AgentDefinition>;
  skills: SkillDefinition[];
  hooks: HookDefinition[];
};

type Frontmatter = Record<string, string | string[]>;

const registryRoot = new URL("../registry/", import.meta.url);

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function parseScalar(value: string): string | string[] {
  const trimmed = value.trim();
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    return trimmed
      .slice(1, -1)
      .split(",")
      .map(item => item.trim().replace(/^["']|["']$/g, ""))
      .filter(Boolean);
  }
  return trimmed.replace(/^["']|["']$/g, "");
}

export function parseFrontmatter(text: string): {
  frontmatter: Frontmatter;
  body: string;
} {
  if (!text.startsWith("---\n")) {
    return { frontmatter: {}, body: text };
  }

  const end = text.indexOf("\n---", 4);
  if (end === -1) {
    return { frontmatter: {}, body: text };
  }

  const block = text.slice(4, end).split("\n");
  const frontmatter: Frontmatter = {};
  let listKey: string | undefined;

  for (const rawLine of block) {
    const line = rawLine.trimEnd();
    const listItem = line.match(/^\s*-\s+(.+)$/);
    if (listItem && listKey) {
      const current = frontmatter[listKey];
      const values = Array.isArray(current) ? current : [];
      values.push(listItem[1].trim().replace(/^["']|["']$/g, ""));
      frontmatter[listKey] = values;
      continue;
    }

    const emptyList = line.match(/^([A-Za-z][\w-]*):\s*$/);
    if (emptyList) {
      listKey = emptyList[1];
      frontmatter[listKey] = [];
      continue;
    }

    const scalar = line.match(/^([A-Za-z][\w-]*):\s*(.+)$/);
    if (scalar) {
      listKey = undefined;
      frontmatter[scalar[1]] = parseScalar(scalar[2]);
    }
  }

  return {
    frontmatter,
    body: text.slice(end + "\n---".length).trimStart(),
  };
}

function stringValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value.join(", ") : value ?? "";
}

function listValue(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  return value
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
}

async function loadAgentDefinitions(
  agentsDir: string,
  toolsById: Record<string, ToolSpec>,
): Promise<Record<string, AgentDefinition>> {
  if (!(await exists(agentsDir))) return {};

  const entries = await readdir(agentsDir, { withFileTypes: true });
  const agents: Record<string, AgentDefinition> = {};

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".md")) continue;

    const path = join(agentsDir, entry.name);
    const { frontmatter, body } = parseFrontmatter(await readFile(path, "utf8"));
    const id = stringValue(frontmatter.id) || entry.name.replace(/\.md$/, "");
    const toolNames = listValue(frontmatter.tools);
    const tools = Object.fromEntries(
      toolNames
        .map(name => [name, toolsById[name]] as const)
        .filter(([, tool]) => Boolean(tool)),
    );

    agents[id] = {
      id,
      description: stringValue(frontmatter.description),
      instructions: body.trim(),
      tools,
      maxTurns: Number(stringValue(frontmatter.maxTurns)) || undefined,
      source: path,
    };
  }

  return agents;
}

async function findSkillFiles(root: string): Promise<string[]> {
  if (!(await exists(root))) return [];

  const entries = await readdir(root, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await findSkillFiles(path)));
    } else if (entry.isFile() && entry.name === "SKILL.md") {
      files.push(path);
    }
  }

  return files;
}

async function discoverSkills(skillsDir: string): Promise<SkillDefinition[]> {
  const skillFiles = await findSkillFiles(skillsDir);
  const skills: SkillDefinition[] = [];

  for (const bodyPath of skillFiles) {
    const baseDir = dirname(bodyPath);
    const { frontmatter } = parseFrontmatter(await readFile(bodyPath, "utf8"));
    const relativeBase = relative(skillsDir, baseDir);
    const parts = relativeBase.split(/[\\/]/).filter(Boolean);
    const name = stringValue(frontmatter.name) || parts.at(-1) || "unknown";
    const pluginName = parts.length > 1 ? parts[0] : "";
    const id = pluginName ? `${pluginName}:${name}` : name;

    skills.push({
      id,
      name,
      description: stringValue(frontmatter.description),
      baseDir,
      bodyPath,
    });
  }

  return skills.sort((a, b) => a.id.localeCompare(b.id));
}

async function loadHooks(hooksDir: string): Promise<HookDefinition[]> {
  if (!(await exists(hooksDir))) return [];

  const entries = await readdir(hooksDir, { withFileTypes: true });
  const hooks: HookDefinition[] = [];

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;

    const path = join(hooksDir, entry.name);
    const hook = JSON.parse(await readFile(path, "utf8")) as HookDefinition;
    hooks.push({ ...hook, id: hook.id || entry.name.replace(/\.json$/, "") });
  }

  return hooks.sort((a, b) => a.id.localeCompare(b.id));
}

export function renderSkillListing(skills: SkillDefinition[]): string {
  if (skills.length === 0) return "";

  return [
    "The following skills are available for use with the Skill tool:",
    "",
    ...skills.map(skill => `- ${skill.id}: ${skill.description}`),
  ].join("\n");
}

export function runDeclarativeHooks(args: {
  hooks: HookDefinition[];
  event: HookDefinition["event"];
  scope: "parent" | "subagent";
}): { hookIds: string[]; context: string } {
  const active = args.hooks.filter(
    hook =>
      hook.event === args.event &&
      (hook.appliesTo === args.scope || hook.appliesTo === "both"),
  );

  return {
    hookIds: active.map(hook => hook.id),
    context: active.map(hook => hook.additionalContext).join("\n\n"),
  };
}

export async function loadRuntimeRegistry(args: {
  toolsById: Record<string, ToolSpec>;
  fallbackAgents: Record<string, AgentDefinition>;
  root?: URL;
}): Promise<RuntimeRegistry> {
  const root = args.root ?? registryRoot;
  const [fileAgents, skills, hooks] = await Promise.all([
    loadAgentDefinitions(new URL("agents/", root).pathname, args.toolsById),
    discoverSkills(new URL("skills/", root).pathname),
    loadHooks(new URL("hooks/", root).pathname),
  ]);

  return {
    agents: { ...args.fallbackAgents, ...fileAgents },
    skills,
    hooks,
  };
}
