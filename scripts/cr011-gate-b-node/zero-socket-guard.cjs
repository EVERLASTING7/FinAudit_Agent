'use strict';

const GUARD_KEY = '__CR011_ZERO_SOCKET_GUARD__';
const DENIED_CODE = 'CR011_ZERO_SOCKET_DENIED';
const BLOCKED_ASYNC_TYPES = new Set([
  'GETADDRINFOREQWRAP',
  'GETNAMEINFOREQWRAP',
  'HTTP2SESSION',
  'HTTP2STREAM',
  'PIPECONNECTWRAP',
  'PIPESERVERWRAP',
  'PIPEWRAP',
  'PROCESSWRAP',
  'QUERYWRAP',
  'TCPCONNECTWRAP',
  'TCPSERVERWRAP',
  'TCPWRAP',
  'TLSWRAP',
  'UDPSENDWRAP',
  'UDPWRAP',
  'WORKER',
]);

if (process.env.NODE_OPTIONS) {
  process.stderr.write('CR011_ZERO_SOCKET_NODE_OPTIONS_FORBIDDEN\n');
  process.exit(2);
}

if (GUARD_KEY in globalThis) {
  process.stderr.write('CR011_ZERO_SOCKET_GUARD_PRESEEDED\n');
  process.exit(2);
}

let attempts = 0;
let state;
let asyncHook;
const patches = [];
const deny = (label) => {
  attempts += 1;
  const error = new Error('CR-011 Gate B forbids network and process access');
  error.code = DENIED_CODE;
  error.operation = label;
  throw error;
};
const denyAsyncResource = () => {
  attempts += 1;
  process.stderr.write('CR011_ZERO_SOCKET_NATIVE_RESOURCE_DENIED\n');
  process.exit(2);
};
const denyFunction = (label) => function deniedGateBOperation() {
  return deny(label);
};
const denyClass = (label) => class DeniedGateBConstructor {
  constructor() {
    deny(label);
  }
};
const replace = (target, key, value) => {
  if (!target) throw new Error('required zero-socket entry point is unavailable');
  const enumerable = Object.prototype.propertyIsEnumerable.call(target, key);
  Object.defineProperty(target, key, {
    configurable: true,
    enumerable,
    writable: true,
    value,
  });
  const descriptor = Object.getOwnPropertyDescriptor(target, key);
  if (!descriptor || descriptor.value !== value) {
    throw new Error('zero-socket entry point patch failed');
  }
  patches.push({ target, key, value, enumerable });
};
const replaceFunctions = (target, names, prefix) => {
  for (const name of names) replace(target, name, denyFunction(`${prefix}.${name}`));
};

try {
  // This is process-local Gate attestation, not an OS sandbox for arbitrary
  // native addons. The frozen test dependency closure contains no addons.
  void process.stdin;
  void process.stdout;
  void process.stderr;
  asyncHook = require('node:async_hooks').createHook({
    init(_asyncId, type) {
      if (BLOCKED_ASYNC_TYPES.has(type)) denyAsyncResource();
    },
  });
  asyncHook.enable();

  const net = require('node:net');
  replaceFunctions(net, ['connect', 'createConnection', 'createServer', '_createServerHandle'], 'net');
  replaceFunctions(net.Socket?.prototype, ['connect'], 'net.Socket');
  replaceFunctions(net.Server?.prototype, ['listen'], 'net.Server');

  const tls = require('node:tls');
  replaceFunctions(tls, ['connect', 'createServer'], 'tls');
  replaceFunctions(tls.TLSSocket?.prototype, ['connect'], 'tls.TLSSocket');

  for (const moduleName of ['http', 'https']) {
    const transport = require(`node:${moduleName}`);
    replaceFunctions(transport, ['request', 'get', 'createServer'], moduleName);
    replaceFunctions(transport.Agent?.prototype, ['createConnection'], `${moduleName}.Agent`);
  }

  const http2 = require('node:http2');
  replaceFunctions(http2, ['connect', 'createServer', 'createSecureServer'], 'http2');

  const dgram = require('node:dgram');
  replaceFunctions(dgram, ['createSocket', '_createSocketHandle'], 'dgram');
  replaceFunctions(dgram.Socket?.prototype, ['bind', 'connect', 'send'], 'dgram.Socket');
  replace(dgram, 'Socket', denyClass('dgram.Socket'));

  const dns = require('node:dns');
  replaceFunctions(
    dns,
    [
      'lookup',
      'lookupService',
      'resolve',
      'resolve4',
      'resolve6',
      'resolveAny',
      'resolveCaa',
      'resolveCname',
      'resolveMx',
      'resolveNaptr',
      'resolveNs',
      'resolvePtr',
      'resolveSoa',
      'resolveSrv',
      'resolveTxt',
      'reverse',
      'setDefaultResultOrder',
      'setServers',
    ],
    'dns',
  );
  replaceFunctions(
    dns.Resolver?.prototype,
    [
      'resolve',
      'resolve4',
      'resolve6',
      'resolveAny',
      'resolveCaa',
      'resolveCname',
      'resolveMx',
      'resolveNaptr',
      'resolveNs',
      'resolvePtr',
      'resolveSoa',
      'resolveSrv',
      'resolveTxt',
      'reverse',
      'setLocalAddress',
      'setServers',
    ],
    'dns.Resolver',
  );
  replaceFunctions(
    dns.promises,
    [
      'lookup',
      'lookupService',
      'resolve',
      'resolve4',
      'resolve6',
      'resolveAny',
      'resolveCaa',
      'resolveCname',
      'resolveMx',
      'resolveNaptr',
      'resolveNs',
      'resolvePtr',
      'resolveSoa',
      'resolveSrv',
      'resolveTxt',
      'reverse',
      'setDefaultResultOrder',
      'setServers',
    ],
    'dns.promises',
  );
  replaceFunctions(
    dns.promises?.Resolver?.prototype,
    [
      'resolve',
      'resolve4',
      'resolve6',
      'resolveAny',
      'resolveCaa',
      'resolveCname',
      'resolveMx',
      'resolveNaptr',
      'resolveNs',
      'resolvePtr',
      'resolveSoa',
      'resolveSrv',
      'resolveTxt',
      'reverse',
      'setLocalAddress',
      'setServers',
    ],
    'dns.promises.Resolver',
  );

  const childProcess = require('node:child_process');
  replaceFunctions(
    childProcess,
    ['exec', 'execFile', 'execFileSync', 'execSync', 'fork', 'spawn', 'spawnSync', '_forkChild'],
    'child_process',
  );
  replaceFunctions(childProcess.ChildProcess?.prototype, ['spawn'], 'child_process.ChildProcess');

  const workerThreads = require('node:worker_threads');
  replace(workerThreads, 'Worker', denyClass('worker_threads.Worker'));

  const inspector = require('node:inspector');
  replaceFunctions(inspector, ['open'], 'inspector');

  replace(globalThis, 'fetch', denyFunction('global.fetch'));
  replace(globalThis, 'WebSocket', denyClass('global.WebSocket'));

  const originalBinding = process.binding;
  const forbiddenBindings = new Set(['cares_wrap', 'pipe_wrap', 'tcp_wrap', 'tls_wrap', 'udp_wrap']);
  replace(process, 'binding', function guardedProcessBinding(name) {
    if (forbiddenBindings.has(name)) return deny(`process.binding.${name}`);
    return Reflect.apply(originalBinding, process, [name]);
  });

  const assertIntegrity = () => {
    const globalDescriptor = Object.getOwnPropertyDescriptor(globalThis, GUARD_KEY);
    return Boolean(
      globalDescriptor
      && globalDescriptor.value === state
      && globalDescriptor.configurable === false
      && globalDescriptor.enumerable === false
      && globalDescriptor.writable === false
      && Object.getPrototypeOf(state) === null
      && Object.isFrozen(state)
      && module.exports === state
      && asyncHook !== undefined
      && patches.every(({ target, key, value, enumerable }) => {
        const descriptor = Object.getOwnPropertyDescriptor(target, key);
        return descriptor?.value === value
          && descriptor.configurable === true
          && descriptor.enumerable === enumerable
          && descriptor.writable === true;
      })
    );
  };

  state = Object.create(null);
  Object.defineProperties(state, {
    guard_id: { enumerable: true, value: 'cr011-zero-socket-guard-v1' },
    deniedCode: { enumerable: true, value: DENIED_CODE },
    patch_count: { enumerable: true, value: patches.length },
    attempts: { enumerable: true, get: () => attempts },
    assertIntegrity: { enumerable: true, value: assertIntegrity },
  });
  Object.freeze(state);
  Object.defineProperty(globalThis, GUARD_KEY, {
    configurable: false,
    enumerable: false,
    writable: false,
    value: state,
  });
  module.exports = state;
  if (!state.assertIntegrity()) throw new Error('zero-socket installation identity failed');
} catch {
  process.stderr.write('CR011_ZERO_SOCKET_GUARD_INSTALL_FAILED\n');
  process.exit(2);
}

if (require.main === module && process.argv.includes('--probe')) {
  const state = globalThis[GUARD_KEY];
  const probes = [
    ['tcp', () => require('node:net').connect({ host: '127.0.0.1', port: 9 })],
    ['dns_localhost', () => require('node:dns').lookup('localhost', () => {})],
    ['dns_other_hostname', () => require('node:dns').lookup('cr011-gate-b.invalid', () => {})],
    ['udp', () => require('node:dgram').createSocket('udp4')],
    ['windows_named_pipe', () => require('node:net').connect('\\\\.\\pipe\\cr011-gate-b-probe')],
    ['local_socket_path', () => require('node:net').connect({ path: 'cr011-gate-b-probe.sock' })],
  ];
  const results = probes.map(([id, probe]) => {
    try {
      probe();
      return { id, denied: false, code: null };
    } catch (error) {
      return { id, denied: error?.code === DENIED_CODE, code: error?.code ?? null };
    }
  });
  const integrity = state.assertIntegrity();
  const passed = results.every((result) => result.denied)
    && state.attempts === probes.length
    && integrity;
  process.stdout.write(JSON.stringify({
    passed,
    attempts: state.attempts,
    integrity,
    patch_count: state.patch_count,
    results,
  }));
  if (!passed) process.exitCode = 1;
}
