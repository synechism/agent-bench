import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import {
  createDemoParentContext,
  forkSubagent,
  spawnFreshSubagent,
} from "./runtime";

async function main() {
  const parent = createDemoParentContext();

  const fresh = await spawnFreshSubagent({
    parent,
    agentType: "research-agent",
    prompt:
      "Research the Claude Code AgentTool path. Include files to inspect and a concise explanation. Context: we care about subagent context construction.",
  });

  const fork = await forkSubagent({
    parent,
    directive:
      "Using the inherited parent context, verify whether fresh subagents inherit the full parent conversation.",
  });

  const output = {
    explanation:
      "Fresh subagent receives only its specialist system prompt and parent-written brief. Fork subagent receives parent rendered system prompt, parent messages, parent tools, and a fork directive.",
    fresh,
    fork,
  };

  const outputPath = resolve("artifacts/subagent-poc-run.json");
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`);

  console.log(JSON.stringify(output, null, 2));
  console.log(`\nWrote ${outputPath}`);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

