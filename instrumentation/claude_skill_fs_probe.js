// Node preload probe for Claude Code skill/plugin file access.
//
// Enabled by the harness with:
//   NODE_OPTIONS=--require=/runs/<run_id>/claude_skill_fs_probe.js
//   CLAUDE_SKILL_FS_LOG=/runs/<run_id>/claude_skill_fs_log.jsonl
//
// The probe logs only skill/plugin-looking paths and short call stacks.

const fs = require("fs");
const path = require("path");

const logPath = process.env.CLAUDE_SKILL_FS_LOG;
const original = {
  readFileSync: fs.readFileSync,
  readFile: fs.readFile,
  readdirSync: fs.readdirSync,
  readdir: fs.readdir,
  statSync: fs.statSync,
  stat: fs.stat,
  appendFileSync: fs.appendFileSync,
};

let writing = false;

function pathString(value) {
  if (typeof value === "string") return value;
  if (value && typeof value.toString === "function") return value.toString();
  return "";
}

function interesting(filePath) {
  const p = pathString(filePath);
  if (!p || p === logPath) return false;
  return (
    p.includes("/.claude/") ||
    p.includes("/skills/") ||
    p.includes("/.claude-plugin/") ||
    p.endsWith("SKILL.md") ||
    p.endsWith("hooks.json") ||
    p.endsWith("plugin.json")
  );
}

function stackFrames() {
  const stack = new Error().stack || "";
  return stack
    .split("\n")
    .slice(3, 11)
    .map((line) => line.trim())
    .filter(Boolean);
}

function log(event, target) {
  if (!logPath || writing || !interesting(target)) return;
  writing = true;
  try {
    original.appendFileSync(
      logPath,
      JSON.stringify({
        ts: new Date().toISOString(),
        pid: process.pid,
        event,
        path: pathString(target),
        stack: stackFrames(),
      }) + "\n"
    );
  } catch (_err) {
    // Instrumentation must never affect the agent.
  } finally {
    writing = false;
  }
}

fs.readFileSync = function patchedReadFileSync(filePath, ...args) {
  log("readFileSync", filePath);
  return original.readFileSync.call(this, filePath, ...args);
};

fs.readFile = function patchedReadFile(filePath, ...args) {
  log("readFile", filePath);
  return original.readFile.call(this, filePath, ...args);
};

fs.readdirSync = function patchedReaddirSync(filePath, ...args) {
  log("readdirSync", filePath);
  return original.readdirSync.call(this, filePath, ...args);
};

fs.readdir = function patchedReaddir(filePath, ...args) {
  log("readdir", filePath);
  return original.readdir.call(this, filePath, ...args);
};

fs.statSync = function patchedStatSync(filePath, ...args) {
  log("statSync", filePath);
  return original.statSync.call(this, filePath, ...args);
};

fs.stat = function patchedStat(filePath, ...args) {
  log("stat", filePath);
  return original.stat.call(this, filePath, ...args);
};

if (fs.promises) {
  const promises = fs.promises;
  const promiseOriginal = {
    readFile: promises.readFile.bind(promises),
    readdir: promises.readdir.bind(promises),
    stat: promises.stat.bind(promises),
  };
  promises.readFile = async function patchedPromiseReadFile(filePath, ...args) {
    log("promises.readFile", filePath);
    return promiseOriginal.readFile(filePath, ...args);
  };
  promises.readdir = async function patchedPromiseReaddir(filePath, ...args) {
    log("promises.readdir", filePath);
    return promiseOriginal.readdir(filePath, ...args);
  };
  promises.stat = async function patchedPromiseStat(filePath, ...args) {
    log("promises.stat", filePath);
    return promiseOriginal.stat(filePath, ...args);
  };
}
