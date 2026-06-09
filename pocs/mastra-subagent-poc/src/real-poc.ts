import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { loadEnvFile } from "node:process";

try {
  loadEnvFile(".env");
} catch {
  // The caller can also provide env vars directly.
}

async function main() {
  const [{ supervisorAgent }, { claudeFreshDelegation }] = await Promise.all([
    import("./mastra/agents"),
    import("./mastra/delegation"),
  ]);

  console.log(`Using model: ${process.env.MASTRA_MODEL ?? "openai/gpt-5-nano"}`);
  console.log("Running real Mastra supervisor -> subagent delegation...");

  const result = await supervisorAgent.generate(
    [
      {
        role: "user",
        content:
          "Delegate exactly once to research-agent. Ask it to inspect the POC's subagent runtime design and answer: what context does a fresh child receive? Then summarize the delegated answer in two short bullet points.",
      },
    ],
    {
      maxSteps: 6,
      delegation: claudeFreshDelegation,
      onStepFinish: ({ toolCalls, toolResults, finishReason, usage }) => {
        console.log(
          JSON.stringify(
            {
              finishReason,
              toolCalls: toolCalls.map(call => {
                const record = call as unknown as Record<string, unknown>;
                return {
                  name: record.toolName ?? record.name,
                  args: record.input ?? record.args,
                };
              }),
              toolResultCount: toolResults.length,
              usage,
            },
            null,
            2,
          ),
        );
      },
    },
  );

  const output = {
    model: process.env.MASTRA_MODEL ?? "openai/gpt-5-nano",
    text: result.text,
    usage: result.usage,
  };

  const outputPath = resolve("artifacts/real-subagent-run.json");
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`);

  console.log("\nFinal text:\n");
  console.log(result.text);
  console.log(`\nWrote ${outputPath}`);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
