'use strict';

if (process.env.NODE_OPTIONS) {
  process.stderr.write('CR011_NODE_SELF_TEST_NODE_OPTIONS_FORBIDDEN\n');
  process.exit(2);
}

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const ARTIFACTS = path.join(ROOT, 'docs', 'change-requests', 'artifacts', 'CR-011');
const VALIDATOR = path.join(__dirname, 'validate-policy.cjs');
const GUARD = path.join(__dirname, 'zero-socket-guard.cjs');
const read = (name) => fs.readFileSync(path.join(ARTIFACTS, name));
const schemaBytes = read('ai-policy-v1.schema.json');
const registryBytes = read('ip-deny-cidrs-v1.json');
const positiveBytes = read('ai-policy-v1.positive.json');
const prehashBytes = read('ai-policy-v1.prehash.jcs.json');
const manifest = JSON.parse(read('ai-policy-v1.negative-vectors.json').toString('utf8'));

function clone(value) {
  return structuredClone(value);
}

function pointerSegments(pointer) {
  assert.match(pointer, /^\/(?:[^/]|~[01])+(?:\/(?:[^/]|~[01])+)*$/);
  return pointer.slice(1).split('/').map((segment) => segment.replaceAll('~1', '/').replaceAll('~0', '~'));
}

function lookup(document, pointer) {
  let current = document;
  for (const segment of pointerSegments(pointer)) {
    current = Array.isArray(current) ? current[Number(segment)] : current[segment];
  }
  return current;
}

function applyMutation(document, mutation) {
  const segments = pointerSegments(mutation.path);
  let parent = document;
  for (const segment of segments.slice(0, -1)) {
    parent = Array.isArray(parent) ? parent[Number(segment)] : parent[segment];
  }
  const key = segments.at(-1);
  if (mutation.op === 'remove') {
    if (Array.isArray(parent)) parent.splice(Number(key), 1);
    else delete parent[key];
    return;
  }
  const value = clone(Object.hasOwn(mutation, 'value_from')
    ? lookup(document, mutation.value_from)
    : mutation.value);
  if (Array.isArray(parent)) {
    if (mutation.op === 'add') parent.splice(Number(key), 0, value);
    else parent[Number(key)] = value;
  } else {
    parent[key] = value;
  }
}

function canonicalize(value) {
  const serialize = (item) => {
    if (item === null || typeof item === 'boolean' || typeof item === 'number' || typeof item === 'string') {
      return JSON.stringify(item);
    }
    if (Array.isArray(item)) return `[${item.map(serialize).join(',')}]`;
    return `{${Object.keys(item).sort().map((key) => `${serialize(key)}:${serialize(item[key])}`).join(',')}}`;
  };
  return Buffer.from(serialize(value), 'utf8');
}

function refreshHash(policy) {
  const projection = clone(policy);
  delete projection.policy_hash;
  policy.policy_hash = crypto.createHash('sha256').update(canonicalize(projection)).digest('hex');
}

function sourceWithToken(pointer, token) {
  const document = JSON.parse(positiveBytes.toString('utf8'));
  const sentinel = '__CR011_RAW_NUMBER_TOKEN_SENTINEL__';
  applyMutation(document, { op: 'replace', path: pointer, value: sentinel });
  return Buffer.from(JSON.stringify(document).replace(JSON.stringify(sentinel), token), 'utf8');
}

function integerPointers(value, pointer = '') {
  if (typeof value === 'number' && Number.isInteger(value)) return [pointer];
  if (Array.isArray(value)) {
    return value.flatMap((child, index) => integerPointers(child, `${pointer}/${index}`));
  }
  if (value !== null && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, child]) => integerPointers(
      child,
      `${pointer}/${key.replaceAll('~', '~0').replaceAll('/', '~1')}`,
    ));
  }
  return [];
}

function negativeSource(testCase) {
  if (Object.hasOwn(testCase, 'source_text')) return Buffer.from(testCase.source_text, 'utf8');
  if (Object.hasOwn(testCase, 'source_mutation')) {
    return sourceWithToken(
      testCase.source_mutation.path,
      testCase.source_mutation.replacement_json_token,
    );
  }
  const document = JSON.parse(positiveBytes.toString('utf8'));
  for (const mutation of testCase.mutations ?? [testCase.mutation]) applyMutation(document, mutation);
  if (['POL-VAL-007', 'POL-VAL-008', 'POL-VAL-009', 'POL-VAL-010', 'POL-VAL-011'].includes(testCase.expected_rule_id)) {
    refreshHash(document);
  }
  return Buffer.from(JSON.stringify(document), 'utf8');
}

function runValidatorProtocol(protocol) {
  return spawnSync(process.execPath, ['--require', GUARD, VALIDATOR], {
    cwd: ROOT,
    input: JSON.stringify(protocol),
    encoding: 'utf8',
    windowsHide: true,
  });
}

function invoke(cases) {
  const protocol = {
    schema_base64: schemaBytes.toString('base64'),
    registry_base64: registryBytes.toString('base64'),
    cases: cases.map(({ id, raw, target }) => ({
      id,
      raw_policy_base64: raw.toString('base64'),
      validation_target: target,
    })),
  };
  const child = runValidatorProtocol(protocol);
  assert.equal(child.status, 0, child.stderr);
  assert.equal(child.stderr, '');
  return JSON.parse(child.stdout);
}

const fixedCases = [
  { id: 'POL-ENTRY-001-final-positive', raw: positiveBytes, target: 'final_envelope' },
  { id: 'POL-ENTRY-002-prehash-positive', raw: prehashBytes, target: 'pre_hash_payload' },
  ...manifest.cases.map((testCase) => ({
    id: testCase.id,
    raw: negativeSource(testCase),
    target: testCase.validation_target ?? 'final_envelope',
  })),
];
const output = invoke(fixedCases);
assert.equal(output.engine_id, 'ajv@8.20.0-draft2020');
assert.equal(output.schema_calls, 20);
assert.equal(output.socket_attempts, 0);
assert.equal(output.results.length, 27);
assert.deepEqual(output.results.map((result) => result.id), fixedCases.map((testCase) => testCase.id));

for (const result of output.results.slice(0, 2)) {
  assert.equal(result.accepted, true);
  assert.equal(result.stage, 'complete');
  assert.equal(result.rule_id, null);
  assert.equal(result.safe_error_code, null);
  assert.equal(result.prehash_sha256, 'db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d');
  assert.deepEqual(Buffer.from(result.prehash_base64, 'base64'), prehashBytes);
}
for (const [index, testCase] of manifest.cases.entries()) {
  const result = output.results[index + 2];
  assert.equal(result.accepted, false, testCase.id);
  assert.equal(result.stage, testCase.expected_stage, testCase.id);
  assert.equal(result.rule_id, testCase.expected_rule_id, testCase.id);
  assert.equal(result.safe_error_code, testCase.expected_safe_error_code, testCase.id);
  assert.equal(result.prehash_base64, null, testCase.id);
  assert.equal(result.prehash_sha256, null, testCase.id);
}

const validProtocolCase = {
  id: 'protocol-boundary',
  raw_policy_base64: positiveBytes.toString('base64'),
  validation_target: 'final_envelope',
};
const validProtocol = {
  schema_base64: schemaBytes.toString('base64'),
  registry_base64: registryBytes.toString('base64'),
  cases: [validProtocolCase],
};
const assertProtocolFatal = (protocol) => {
  const child = runValidatorProtocol(protocol);
  assert.equal(child.status, 2);
  assert.equal(child.stdout, '');
  assert.equal(child.stderr, 'CR011_GATE_B_VALIDATOR_FATAL\n');
};
assertProtocolFatal({ ...validProtocol, unexpected: null });
assertProtocolFatal({ ...validProtocol, cases: [] });
assertProtocolFatal({
  ...validProtocol,
  cases: [{ ...validProtocolCase, api_key: null }],
});
assertProtocolFatal({
  ...validProtocol,
  cases: [{ ...validProtocolCase, id: '../unsafe-id' }],
});
assertProtocolFatal({
  ...validProtocol,
  cases: [{ ...validProtocolCase, id: 'x'.repeat(129) }],
});
assertProtocolFatal({
  ...validProtocol,
  schema_base64: Buffer.from('{}', 'utf8').toString('base64'),
});
assertProtocolFatal({
  ...validProtocol,
  registry_base64: Buffer.concat([registryBytes, Buffer.from(' ')]).toString('base64'),
});

const boundary = invoke([
  { id: 'empty-raw', raw: Buffer.alloc(0), target: 'final_envelope' },
  { id: 'bom', raw: Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('{}')]), target: 'final_envelope' },
  { id: 'invalid-utf8', raw: Buffer.from([0xff]), target: 'final_envelope' },
  { id: 'lone-surrogate', raw: Buffer.from('{"value":"\\ud800"}'), target: 'final_envelope' },
  { id: 'non-finite-number', raw: Buffer.from('{"value":1e400}'), target: 'final_envelope' },
  { id: 'escaped-duplicate', raw: Buffer.from('{"policy_version":1,"policy_\\u0076ersion":1}'), target: 'final_envelope' },
  { id: 'very-long-integer', raw: sourceWithToken('/policy_version', '9'.repeat(5000)), target: 'final_envelope' },
]);
assert.equal(boundary.schema_calls, 0);
assert.equal(boundary.socket_attempts, 0);
assert.deepEqual(
  boundary.results.map((result) => result.rule_id),
  [
    'POL-VAL-001',
    'POL-VAL-001',
    'POL-VAL-001',
    'POL-VAL-001',
    'POL-VAL-001',
    'POL-VAL-001',
    'POL-VAL-002',
  ],
);

const positiveObject = JSON.parse(positiveBytes.toString('utf8'));
const compactPositive = JSON.stringify(positiveObject);
const poisonKeyTokens = [
  '"__proto__"',
  '"\\u005f\\u005fproto__"',
  '"constructor"',
  '"\\u0063onstructor"',
  '"prototype"',
  '"\\u0070rototype"',
];
const poisonCases = poisonKeyTokens.flatMap((keyToken, index) => {
  const nestedNeedle = '"embedding_primary":{';
  const nested = compactPositive.replace(
    nestedNeedle,
    `${nestedNeedle}${keyToken}:{"polluted":true},`,
  );
  assert.notEqual(nested, compactPositive);
  return [
    {
      id: `poison-top-${index}`,
      raw: Buffer.from(`{${keyToken}:{"polluted":true},${compactPositive.slice(1)}`, 'utf8'),
      target: 'final_envelope',
    },
    {
      id: `poison-nested-${index}`,
      raw: Buffer.from(nested, 'utf8'),
      target: 'final_envelope',
    },
  ];
});
const poison = invoke(poisonCases);
assert.equal(poison.schema_calls, poisonCases.length);
assert.equal(poison.socket_attempts, 0);
assert.ok(poison.results.every(
  (result) => !result.accepted
    && result.stage === 'schema'
    && result.rule_id === 'POL-VAL-004'
    && result.safe_error_code === 'AI_POLICY_SCHEMA_INVALID'
    && result.prehash_base64 === null
    && result.prehash_sha256 === null,
));
assert.equal({}.polluted, undefined);

const legacyIpv4Hosts = [
  '2130706433',
  '127.1',
  '0x7f000001',
  '0xffffffff',
  '0x7f.1',
  '0177.1',
];
const legacyIpv4 = invoke(legacyIpv4Hosts.map((hostname) => {
  const document = clone(positiveObject);
  const profile = document.profiles.embedding_primary;
  profile.approved_hostnames = [hostname];
  profile.base_url = `http://${hostname}:8003/v1`;
  refreshHash(document);
  return {
    id: `legacy-ipv4-${hostname}`,
    raw: Buffer.from(JSON.stringify(document), 'utf8'),
    target: 'final_envelope',
  };
}));
assert.equal(legacyIpv4.schema_calls, legacyIpv4Hosts.length);
assert.equal(legacyIpv4.socket_attempts, 0);
assert.ok(legacyIpv4.results.every(
  (result) => !result.accepted
    && result.stage === 'cross_field'
    && result.rule_id === 'POL-VAL-009'
    && result.safe_error_code === 'AI_POLICY_HOST_INVALID',
));

const integerPaths = integerPointers(positiveObject);
assert.equal(integerPaths.length, 99);
const everyInteger = invoke(integerPaths.map((pointer, index) => ({
  id: `integer-path-${index}`,
  raw: sourceWithToken(pointer, `${lookup(positiveObject, pointer)}.0`),
  target: 'final_envelope',
})));
assert.equal(everyInteger.schema_calls, 0);
assert.equal(everyInteger.socket_attempts, 0);
assert.ok(everyInteger.results.every(
  (result) => result.rule_id === 'POL-VAL-002'
    && result.stage === 'source_number'
    && result.safe_error_code === 'AI_POLICY_INTEGER_TOKEN_INVALID',
));

const probe = spawnSync(process.execPath, [GUARD, '--probe'], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(probe.status, 0, probe.stderr);
assert.equal(probe.stderr, '');
assert.deepEqual(JSON.parse(probe.stdout), {
  passed: true,
  attempts: 6,
  integrity: true,
  patch_count: 108,
  results: [
    'tcp',
    'dns_localhost',
    'dns_other_hostname',
    'udp',
    'windows_named_pipe',
    'local_socket_path',
  ].map((id) => ({
    id,
    denied: true,
    code: 'CR011_ZERO_SOCKET_DENIED',
  })),
});

const preseededGuard = spawnSync(process.execPath, ['-e', [
  `globalThis.__CR011_ZERO_SOCKET_GUARD__={attempts:0};`,
  `require(${JSON.stringify(GUARD)});`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(preseededGuard.status, 2);
assert.equal(preseededGuard.stdout, '');
assert.equal(preseededGuard.stderr, 'CR011_ZERO_SOCKET_GUARD_PRESEEDED\n');

const preseededValidator = spawnSync(process.execPath, ['-e', [
  `globalThis.__CR011_ZERO_SOCKET_GUARD__={attempts:0};`,
  `require(${JSON.stringify(VALIDATOR)});`,
].join('')], {
  cwd: ROOT,
  input: '{}',
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(preseededValidator.status, 2);
assert.equal(preseededValidator.stdout, '');
assert.equal(preseededValidator.stderr, 'CR011_ZERO_SOCKET_GUARD_REQUIRED\n');

const tamperedPatch = spawnSync(process.execPath, ['--require', GUARD, '-e', [
  `'use strict';`,
  `require('node:net').connect=function forgedConnect(){};`,
  `require(${JSON.stringify(VALIDATOR)});`,
].join('')], {
  cwd: ROOT,
  input: '{}',
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(tamperedPatch.status, 2);
assert.equal(tamperedPatch.stdout, '');
assert.equal(tamperedPatch.stderr, 'CR011_ZERO_SOCKET_GUARD_INTEGRITY_REQUIRED\n');

const preexistingAttempt = spawnSync(process.execPath, ['--require', GUARD, '-e', [
  `'use strict';`,
  `try{require('node:net').connect({host:'127.0.0.1',port:9});}catch{}`,
  `require(${JSON.stringify(VALIDATOR)});`,
].join('')], {
  cwd: ROOT,
  input: '{}',
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(preexistingAttempt.status, 2);
assert.equal(preexistingAttempt.stdout, '');
assert.equal(preexistingAttempt.stderr, 'CR011_ZERO_SOCKET_ATTEMPT_DETECTED\n');

const lockedState = spawnSync(process.execPath, ['--require', GUARD, '-e', [
  `'use strict';`,
  `const key='__CR011_ZERO_SOCKET_GUARD__';const state=globalThis[key];`,
  `let globalReplaced=false,stateReplaced=false;`,
  `try{Object.defineProperty(globalThis,key,{value:{}});globalReplaced=true;}catch{}`,
  `try{state.attempts=99;stateReplaced=true;}catch{}`,
  `process.stdout.write(JSON.stringify({`,
  `globalReplaced,stateReplaced,frozen:Object.isFrozen(state),attempts:state.attempts,`,
  `same:Object.getOwnPropertyDescriptor(globalThis,key).value===state,integrity:state.assertIntegrity()`,
  `}));`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(lockedState.status, 0, lockedState.stderr);
assert.equal(lockedState.stderr, '');
assert.deepEqual(JSON.parse(lockedState.stdout), {
  globalReplaced: false,
  stateReplaced: false,
  frozen: true,
  attempts: 0,
  same: true,
  integrity: true,
});

const versionProbe = spawnSync(process.execPath, ['--require', GUARD, '-e', [
  `const state=globalThis.__CR011_ZERO_SOCKET_GUARD__;`,
  `process.stdout.write(JSON.stringify({`,
  `guard_id:state.guard_id,patch_count:state.patch_count,attempts:state.attempts,`,
  `integrity:state.assertIntegrity()`,
  `}));`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(versionProbe.status, 0, versionProbe.stderr);
assert.equal(versionProbe.stderr, '');
assert.deepEqual(JSON.parse(versionProbe.stdout), {
  guard_id: 'cr011-zero-socket-guard-v1',
  patch_count: 108,
  attempts: 0,
  integrity: true,
});

const cachedNetConnect = spawnSync(process.execPath, ['-e', [
  `const net=require('node:net');const cached=net.connect;`,
  `const state=require(${JSON.stringify(GUARD)});let code=null;`,
  `try{cached({host:'127.0.0.1',port:9});}catch(error){code=error.code;}`,
  `process.stdout.write(JSON.stringify({code,attempts:state.attempts,integrity:state.assertIntegrity()}));`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(cachedNetConnect.status, 0, cachedNetConnect.stderr);
assert.equal(cachedNetConnect.stderr, '');
assert.deepEqual(JSON.parse(cachedNetConnect.stdout), {
  code: 'CR011_ZERO_SOCKET_DENIED',
  attempts: 1,
  integrity: true,
});

const cachedSocketConnect = spawnSync(process.execPath, ['-e', [
  `const net=require('node:net');const cached=net.Socket.prototype.connect;`,
  `require(${JSON.stringify(GUARD)});`,
  `cached.call(new net.Socket(),{host:'127.0.0.1',port:9});`,
  `process.stdout.write('BYPASS');`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(cachedSocketConnect.status, 2);
assert.equal(cachedSocketConnect.stdout, '');
assert.equal(cachedSocketConnect.stderr, 'CR011_ZERO_SOCKET_NATIVE_RESOURCE_DENIED\n');

const publicBypasses = spawnSync(process.execPath, ['--require', GUARD, '-e', [
  `const state=globalThis.__CR011_ZERO_SOCKET_GUARD__;`,
  `const calls=[`,
  `()=>require('node:inspector').open(),`,
  `()=>require('node:net')._createServerHandle(),`,
  `()=>require('node:dgram')._createSocketHandle(),`,
  `()=>new (require('node:dgram').Socket)(),`,
  `()=>require('node:child_process').ChildProcess.prototype.spawn.call({}),`,
  `()=>require('node:child_process')._forkChild(),`,
  `()=>process.binding('tcp_wrap')`,
  `];`,
  `const codes=calls.map((call)=>{try{call();return null;}catch(error){return error.code;}});`,
  `process.stdout.write(JSON.stringify({codes,attempts:state.attempts,integrity:state.assertIntegrity()}));`,
].join('')], {
  cwd: ROOT,
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(publicBypasses.status, 0, publicBypasses.stderr);
assert.equal(publicBypasses.stderr, '');
assert.deepEqual(JSON.parse(publicBypasses.stdout), {
  codes: Array(7).fill('CR011_ZERO_SOCKET_DENIED'),
  attempts: 7,
  integrity: true,
});

const nodeOptionsEnvironment = { NODE_OPTIONS: '--no-warnings' };
const nodeOptionsGuard = spawnSync(process.execPath, ['--require', GUARD, '-e', ''], {
  cwd: ROOT,
  encoding: 'utf8',
  env: nodeOptionsEnvironment,
  windowsHide: true,
});
assert.equal(nodeOptionsGuard.status, 2);
assert.equal(nodeOptionsGuard.stdout, '');
assert.equal(nodeOptionsGuard.stderr, 'CR011_ZERO_SOCKET_NODE_OPTIONS_FORBIDDEN\n');

const nodeOptionsSelfTest = spawnSync(process.execPath, [__filename], {
  cwd: ROOT,
  encoding: 'utf8',
  env: nodeOptionsEnvironment,
  windowsHide: true,
});
assert.equal(nodeOptionsSelfTest.status, 2);
assert.equal(nodeOptionsSelfTest.stdout, '');
assert.equal(nodeOptionsSelfTest.stderr, 'CR011_NODE_SELF_TEST_NODE_OPTIONS_FORBIDDEN\n');

const unguarded = spawnSync(process.execPath, [VALIDATOR], {
  cwd: ROOT,
  input: '{}',
  encoding: 'utf8',
  windowsHide: true,
});
assert.equal(unguarded.status, 2);
assert.equal(unguarded.stdout, '');
assert.equal(unguarded.stderr, 'CR011_ZERO_SOCKET_GUARD_REQUIRED\n');

process.stdout.write('CR011_NODE_VALIDATOR_SELF_TEST=PASS\n');
