import type { DelegationConfig } from "@mastra/core/agent";

export const claudeFreshDelegation = {
  onDelegationStart: ({ primitiveId, prompt }) => {
    console.log(
      `[delegation:fresh] ${primitiveId} receives prompt-only brief: ${prompt.length} chars`,
    );
  },
  messageFilter: ({ primitiveId }) => {
    console.log(
      `[delegation:fresh] ${primitiveId} receives 0 parent history messages`,
    );
    return [];
  },
  includeSubAgentToolResultsInModelContext: false,
} satisfies DelegationConfig;

export const claudeForkDelegation = {
  onDelegationStart: ({ primitiveId, prompt, messages }) => {
    console.log(
      `[delegation:fork] ${primitiveId} receives directive plus ${messages.length} parent messages; prompt=${prompt.length} chars`,
    );
  },
  messageFilter: ({ messages, primitiveId }) => {
    console.log(
      `[delegation:fork] ${primitiveId} receives ${messages.length} inherited parent messages`,
    );
    return messages;
  },
  includeSubAgentToolResultsInModelContext: false,
} satisfies DelegationConfig;
