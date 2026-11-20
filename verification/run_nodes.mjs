import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const verificationDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.dirname(verificationDir);
const workflowPath = path.join(rootDir, 'n8n', 'fairmatch_template.json');
const lockPath = path.join(verificationDir, 'source-lock.json');

const sha256 = value => createHash('sha256').update(value).digest('hex');
const workflowBytes = readFileSync(workflowPath);
const workflow = JSON.parse(workflowBytes.toString('utf8'));
const lock = JSON.parse(readFileSync(lockPath, 'utf8'));

if (sha256(workflowBytes) !== lock.workflow_sha256) {
  throw new Error('Workflow export differs from the pinned FairMatch source snapshot.');
}

const codeNode = name => {
  const node = workflow.nodes.find(candidate => candidate.name === name);
  if (!node || node.type !== 'n8n-nodes-base.code' || !node.parameters?.jsCode) {
    throw new Error(`Expected n8n Code node not found: ${name}`);
  }
  const code = node.parameters.jsCode;
  if (sha256(code) !== lock.nodes[name]) {
    throw new Error(`Code node differs from the pinned source: ${name}`);
  }
  return code;
};

const input = JSON.parse(readFileSync(0, 'utf8'));
if (!Array.isArray(input.raw_rows) || input.raw_rows.length === 0) {
  throw new Error('Expected non-empty raw_rows input.');
}

const executeCodeNode = (name, code, rows) => {
  const wrappedCode = `(function(items) {\n${code}\n})(items)`;
  const result = vm.runInNewContext(wrappedCode, { items: rows }, {
    timeout: 15000,
    filename: `n8n-code-node:${name}`,
  });
  return JSON.parse(JSON.stringify(result));
};

const clean = executeCodeNode(
  'Clean and Normalize Responses',
  codeNode('Clean and Normalize Responses'),
  input.raw_rows.map(json => ({ json })),
);
if (!Array.isArray(clean) || !clean[0]?.json) {
  throw new Error('Cleaner returned an unexpected n8n item shape.');
}

const solved = executeCodeNode(
  'FairMatch Solver Engine',
  codeNode('FairMatch Solver Engine'),
  [{ json: clean[0].json }],
);
if (!Array.isArray(solved) || !solved[0]?.json) {
  throw new Error('Solver returned an unexpected n8n item shape.');
}

process.stdout.write(JSON.stringify({
  cleaned: clean[0].json,
  solved: solved[0].json,
}));
