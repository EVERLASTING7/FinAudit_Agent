'use strict';

const GUARD_KEY = '__CR011_ZERO_SOCKET_GUARD__';
const guardModuleId = require.resolve('./zero-socket-guard.cjs');
const cachedGuardModule = require.cache[guardModuleId];
const globalGuardDescriptor = Object.getOwnPropertyDescriptor(globalThis, GUARD_KEY);
if (!cachedGuardModule || !cachedGuardModule.loaded || !globalGuardDescriptor) {
  process.stderr.write('CR011_ZERO_SOCKET_GUARD_REQUIRED\n');
  process.exit(2);
}
const guard = cachedGuardModule.exports;
const attemptsDescriptor = guard && Object.getOwnPropertyDescriptor(guard, 'attempts');
let guardIntegrity = false;
try {
  guardIntegrity = globalGuardDescriptor.value === guard
    && globalGuardDescriptor.configurable === false
    && globalGuardDescriptor.enumerable === false
    && globalGuardDescriptor.writable === false
    && cachedGuardModule.id === guardModuleId
    && cachedGuardModule.filename === guardModuleId
    && Object.getPrototypeOf(guard) === null
    && Object.isFrozen(guard)
    && Object.getOwnPropertyNames(guard).sort().join(',')
      === 'assertIntegrity,attempts,deniedCode,guard_id,patch_count'
    && guard.guard_id === 'cr011-zero-socket-guard-v1'
    && guard.deniedCode === 'CR011_ZERO_SOCKET_DENIED'
    && guard.patch_count === 108
    && attemptsDescriptor?.configurable === false
    && attemptsDescriptor.enumerable === true
    && typeof attemptsDescriptor.get === 'function'
    && attemptsDescriptor.set === undefined
    && typeof guard.attempts === 'number'
    && typeof guard.assertIntegrity === 'function'
    && guard.assertIntegrity() === true;
} catch {
  guardIntegrity = false;
}
if (!guardIntegrity) {
  process.stderr.write('CR011_ZERO_SOCKET_GUARD_INTEGRITY_REQUIRED\n');
  process.exit(2);
}
if (guard.attempts !== 0) {
  process.stderr.write('CR011_ZERO_SOCKET_ATTEMPT_DETECTED\n');
  process.exit(2);
}

const GUARD_SOURCE_SHA256 = '0a556afedc71f3a677e51cf6155d6dc9ca6fc0c1cff69f04742f16512c4c7a46';
const crypto = require('node:crypto');
const fs = require('node:fs');
if (crypto.createHash('sha256').update(fs.readFileSync(guardModuleId)).digest('hex')
    !== GUARD_SOURCE_SHA256) {
  process.stderr.write('CR011_ZERO_SOCKET_GUARD_INTEGRITY_REQUIRED\n');
  process.exit(2);
}
const { isDeepStrictEqual } = require('node:util');
const Ajv2020 = require('ajv/dist/2020').default;
const ajvVersion = require('ajv/package.json').version;

const ENGINE_ID = 'ajv@8.20.0-draft2020';
const POLICY_SCHEMA_SHA256 = '8d583164b46cb2cfa6315efa86491bd6cdc17c818be79dd9c7c274903c9399e3';
const REGISTRY_SHA256 = '628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34';
const MAX_SAFE_INTEGER_TEXT = '9007199254740991';
const INTEGER_TOKEN = /^(?:0|[1-9][0-9]*)$/;
const CASE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const HOST_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const LEGACY_IPV4_LABEL = /^(?:[0-9]+|0x[0-9a-f]+)$/;
const FAILURES = {
  'POL-VAL-001': ['raw_parse', 'AI_POLICY_SOURCE_INVALID'],
  'POL-VAL-002': ['source_number', 'AI_POLICY_INTEGER_TOKEN_INVALID'],
  'POL-VAL-003': ['envelope_context', 'AI_POLICY_ENVELOPE_INVALID'],
  'POL-VAL-004': ['schema', 'AI_POLICY_SCHEMA_INVALID'],
  'POL-VAL-005': ['registry_integrity', 'AI_POLICY_REGISTRY_MISMATCH'],
  'POL-VAL-006': ['hash', 'AI_POLICY_HASH_MISMATCH'],
  'POL-VAL-007': ['cross_field', 'AI_POLICY_ARRAY_NOT_CANONICAL'],
  'POL-VAL-008': ['cross_field', 'AI_POLICY_ROUTE_GRAPH_INVALID'],
  'POL-VAL-009': ['cross_field', 'AI_POLICY_HOST_INVALID'],
  'POL-VAL-010': ['network_registry', 'AI_POLICY_CIDR_NOT_CANONICAL'],
  'POL-VAL-011': ['network_registry', 'AI_POLICY_NETWORK_SCOPE_INVALID'],
};

class StrictJsonError extends Error {}

function pointerChild(pointer, segment) {
  return `${pointer}/${segment.replaceAll('~', '~0').replaceAll('/', '~1')}`;
}

class StrictJsonParser {
  constructor(text) {
    this.text = text;
    this.index = 0;
    this.numberTokens = [];
  }

  parse() {
    this.skipWhitespace();
    const value = this.parseValue('');
    this.skipWhitespace();
    if (this.index !== this.text.length) throw new StrictJsonError();
    return { value, numberTokens: this.numberTokens };
  }

  skipWhitespace() {
    while (' \t\r\n'.includes(this.text[this.index] ?? '\0')) this.index += 1;
  }

  parseValue(pointer) {
    const character = this.text[this.index];
    if (character === '{') return this.parseObject(pointer);
    if (character === '[') return this.parseArray(pointer);
    if (character === '"') return this.parseString();
    if (character === 't') return this.parseLiteral('true', true);
    if (character === 'f') return this.parseLiteral('false', false);
    if (character === 'n') return this.parseLiteral('null', null);
    if (character === '-' || (character >= '0' && character <= '9')) {
      return this.parseNumber(pointer);
    }
    throw new StrictJsonError();
  }

  parseLiteral(source, value) {
    if (this.text.slice(this.index, this.index + source.length) !== source) {
      throw new StrictJsonError();
    }
    this.index += source.length;
    return value;
  }

  parseObject(pointer) {
    const result = {};
    const keys = new Set();
    this.index += 1;
    this.skipWhitespace();
    if (this.text[this.index] === '}') {
      this.index += 1;
      return result;
    }
    while (true) {
      if (this.text[this.index] !== '"') throw new StrictJsonError();
      const key = this.parseString();
      if (keys.has(key)) throw new StrictJsonError();
      keys.add(key);
      this.skipWhitespace();
      if (this.text[this.index] !== ':') throw new StrictJsonError();
      this.index += 1;
      this.skipWhitespace();
      const child = this.parseValue(pointerChild(pointer, key));
      Object.defineProperty(result, key, {
        configurable: true,
        enumerable: true,
        writable: true,
        value: child,
      });
      this.skipWhitespace();
      const delimiter = this.text[this.index];
      if (delimiter === '}') {
        this.index += 1;
        return result;
      }
      if (delimiter !== ',') throw new StrictJsonError();
      this.index += 1;
      this.skipWhitespace();
    }
  }

  parseArray(pointer) {
    const result = [];
    this.index += 1;
    this.skipWhitespace();
    if (this.text[this.index] === ']') {
      this.index += 1;
      return result;
    }
    while (true) {
      result.push(this.parseValue(pointerChild(pointer, String(result.length))));
      this.skipWhitespace();
      const delimiter = this.text[this.index];
      if (delimiter === ']') {
        this.index += 1;
        return result;
      }
      if (delimiter !== ',') throw new StrictJsonError();
      this.index += 1;
      this.skipWhitespace();
    }
  }

  parseString() {
    let result = '';
    this.index += 1;
    while (this.index < this.text.length) {
      const character = this.text[this.index++];
      if (character === '"') return result;
      if (character === '\\') {
        const escape = this.text[this.index++];
        const replacements = {
          '"': '"',
          '\\': '\\',
          '/': '/',
          b: '\b',
          f: '\f',
          n: '\n',
          r: '\r',
          t: '\t',
        };
        if (Object.hasOwn(replacements, escape)) {
          result += replacements[escape];
          continue;
        }
        if (escape !== 'u') throw new StrictJsonError();
        const high = this.parseHexCodeUnit();
        if (high >= 0xd800 && high <= 0xdbff) {
          if (this.text.slice(this.index, this.index + 2) !== '\\u') {
            throw new StrictJsonError();
          }
          this.index += 2;
          const low = this.parseHexCodeUnit();
          if (low < 0xdc00 || low > 0xdfff) throw new StrictJsonError();
          result += String.fromCodePoint(0x10000 + ((high - 0xd800) << 10) + low - 0xdc00);
          continue;
        }
        if (high >= 0xdc00 && high <= 0xdfff) throw new StrictJsonError();
        result += String.fromCharCode(high);
        continue;
      }
      const codeUnit = character.charCodeAt(0);
      if (codeUnit < 0x20) throw new StrictJsonError();
      if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
        const low = this.text.charCodeAt(this.index);
        if (low < 0xdc00 || low > 0xdfff) throw new StrictJsonError();
        result += character + this.text[this.index++];
        continue;
      }
      if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) throw new StrictJsonError();
      result += character;
    }
    throw new StrictJsonError();
  }

  parseHexCodeUnit() {
    const digits = this.text.slice(this.index, this.index + 4);
    if (!/^[0-9a-fA-F]{4}$/.test(digits)) throw new StrictJsonError();
    this.index += 4;
    return Number.parseInt(digits, 16);
  }

  parseNumber(pointer) {
    const start = this.index;
    if (this.text[this.index] === '-') this.index += 1;
    if (this.text[this.index] === '0') {
      this.index += 1;
    } else {
      if (this.text[this.index] < '1' || this.text[this.index] > '9') {
        throw new StrictJsonError();
      }
      while (this.text[this.index] >= '0' && this.text[this.index] <= '9') this.index += 1;
    }
    let integerLexeme = true;
    if (this.text[this.index] === '.') {
      integerLexeme = false;
      this.index += 1;
      if (this.text[this.index] < '0' || this.text[this.index] > '9') {
        throw new StrictJsonError();
      }
      while (this.text[this.index] >= '0' && this.text[this.index] <= '9') this.index += 1;
    }
    if (this.text[this.index] === 'e' || this.text[this.index] === 'E') {
      integerLexeme = false;
      this.index += 1;
      if (this.text[this.index] === '+' || this.text[this.index] === '-') this.index += 1;
      if (this.text[this.index] < '0' || this.text[this.index] > '9') {
        throw new StrictJsonError();
      }
      while (this.text[this.index] >= '0' && this.text[this.index] <= '9') this.index += 1;
    }
    const lexeme = this.text.slice(start, this.index);
    let value = Number(lexeme);
    if (!Number.isFinite(value)) {
      if (!integerLexeme) throw new StrictJsonError();
      value = lexeme.startsWith('-') ? -Number.MAX_VALUE : Number.MAX_VALUE;
    }
    this.numberTokens.push({ pointer, lexeme });
    return value;
  }
}

function parseStrictJson(raw) {
  if (!Buffer.isBuffer(raw) || (raw.length >= 3 && raw.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf])))) {
    throw new StrictJsonError();
  }
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  } catch {
    throw new StrictJsonError();
  }
  if (text.startsWith('\ufeff')) throw new StrictJsonError();
  try {
    return new StrictJsonParser(text).parse();
  } catch (error) {
    if (error instanceof StrictJsonError || error instanceof RangeError) throw new StrictJsonError();
    throw error;
  }
}

function asObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : null;
}

function resolveLocalRef(rootSchema, ref) {
  if (typeof ref !== 'string' || !ref.startsWith('#/')) throw new Error('invalid schema artifact');
  let current = rootSchema;
  for (const rawSegment of ref.slice(2).split('/')) {
    const segment = rawSegment.replaceAll('~1', '/').replaceAll('~0', '~');
    current = asObject(current)?.[segment];
    if (current === undefined) throw new Error('invalid schema artifact');
  }
  const resolved = asObject(current);
  if (!resolved) throw new Error('invalid schema artifact');
  return resolved;
}

function selectedSchema(rootSchema, target) {
  const definitions = asObject(rootSchema.$defs);
  const name = target === 'final_envelope' ? 'finalPolicy' : 'preHashPayload';
  const selected = asObject(definitions?.[name]);
  if (!selected) throw new Error('invalid schema artifact');
  return selected;
}

function nodeDeclaresInteger(node) {
  return node.type === 'integer' || (typeof node.const === 'number' && Number.isInteger(node.const));
}

function integerTokenIsValid(value, token) {
  if (typeof value !== 'number' || !Number.isInteger(value) || !token || !INTEGER_TOKEN.test(token.lexeme)) {
    return false;
  }
  if (token.lexeme.length < MAX_SAFE_INTEGER_TEXT.length) return true;
  if (token.lexeme.length > MAX_SAFE_INTEGER_TEXT.length) return false;
  return token.lexeme <= MAX_SAFE_INTEGER_TEXT;
}

function integerTokensAreValid(document, rootSchema, schema) {
  const tokens = new Map(document.numberTokens.map((token) => [token.pointer, token]));
  const nodeIds = new WeakMap();
  let nextNodeId = 1;
  const visited = new Set();
  const idFor = (node) => {
    if (!nodeIds.has(node)) nodeIds.set(node, nextNodeId++);
    return nodeIds.get(node);
  };

  const conditionMatches = (instance, node) => {
    if (typeof node.$ref === 'string' && !conditionMatches(instance, resolveLocalRef(rootSchema, node.$ref))) {
      return false;
    }
    if (Object.hasOwn(node, 'const') && !isDeepStrictEqual(instance, node.const)) return false;
    if (Array.isArray(node.enum) && !node.enum.some((candidate) => isDeepStrictEqual(instance, candidate))) {
      return false;
    }
    if (Array.isArray(node.required)) {
      const mapping = asObject(instance);
      if (!mapping || !node.required.every((key) => typeof key === 'string' && Object.hasOwn(mapping, key))) {
        return false;
      }
    }
    const mapping = asObject(instance);
    const properties = asObject(node.properties);
    if (mapping && properties) {
      for (const [key, childSchema] of Object.entries(properties)) {
        const child = asObject(childSchema);
        if (Object.hasOwn(mapping, key) && child && !conditionMatches(mapping[key], child)) return false;
      }
    }
    for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
      if (!Array.isArray(node[keyword])) continue;
      const outcomes = node[keyword].filter((branch) => asObject(branch)).map((branch) => conditionMatches(instance, branch));
      if (keyword === 'allOf' && !outcomes.every(Boolean)) return false;
      if (keyword === 'anyOf' && !outcomes.some(Boolean)) return false;
      if (keyword === 'oneOf' && outcomes.filter(Boolean).length !== 1) return false;
    }
    return true;
  };

  let valid = true;
  const walk = (instance, node, pointer) => {
    if (!valid) return;
    const visitKey = `${idFor(node)}:${pointer}`;
    if (visited.has(visitKey)) return;
    visited.add(visitKey);

    if (typeof node.$ref === 'string') walk(instance, resolveLocalRef(rootSchema, node.$ref), pointer);
    if (instance !== null && nodeDeclaresInteger(node) && !integerTokenIsValid(instance, tokens.get(pointer))) {
      valid = false;
      return;
    }

    const instanceMapping = asObject(instance);
    const constantMapping = asObject(node.const);
    if (instanceMapping && constantMapping) {
      for (const [key, childConstant] of Object.entries(constantMapping)) {
        if (Object.hasOwn(instanceMapping, key)) {
          walk(instanceMapping[key], { const: childConstant }, pointerChild(pointer, key));
        }
      }
    }
    if (Array.isArray(instance) && Array.isArray(node.const)) {
      for (let index = 0; index < Math.min(instance.length, node.const.length); index += 1) {
        walk(instance[index], { const: node.const[index] }, pointerChild(pointer, String(index)));
      }
    }

    for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
      if (!Array.isArray(node[keyword])) continue;
      for (const branch of node[keyword]) {
        const mapping = asObject(branch);
        if (mapping) walk(instance, mapping, pointer);
      }
    }
    const condition = asObject(node.if);
    if (condition) {
      const branch = asObject(node[conditionMatches(instance, condition) ? 'then' : 'else']);
      if (branch) walk(instance, branch, pointer);
    }

    if (instanceMapping) {
      const properties = asObject(node.properties);
      for (const [key, child] of Object.entries(instanceMapping)) {
        const childSchema = properties && Object.hasOwn(properties, key)
          ? asObject(properties[key])
          : null;
        if (childSchema) {
          walk(child, childSchema, pointerChild(pointer, key));
        } else {
          const additional = asObject(node.additionalProperties);
          if (additional) walk(child, additional, pointerChild(pointer, key));
        }
      }
    }
    const itemSchema = asObject(node.items);
    if (Array.isArray(instance) && itemSchema) {
      instance.forEach((child, index) => walk(child, itemSchema, pointerChild(pointer, String(index))));
    }
  };

  walk(document.value, schema, '');
  return valid;
}

function canonicalizeJcs(value) {
  const serialize = (item) => {
    if (item === null) return 'null';
    if (item === true) return 'true';
    if (item === false) return 'false';
    if (typeof item === 'number') {
      if (!Number.isFinite(item)) throw new Error('unsupported number');
      return JSON.stringify(item);
    }
    if (typeof item === 'string') return JSON.stringify(item);
    if (Array.isArray(item)) return `[${item.map(serialize).join(',')}]`;
    const mapping = asObject(item);
    if (mapping) {
      return `{${Object.keys(mapping).sort().map((key) => `${serialize(key)}:${serialize(mapping[key])}`).join(',')}}`;
    }
    throw new Error('unsupported JSON value');
  };
  return Buffer.from(serialize(value), 'utf8');
}

function sha256(raw) {
  return crypto.createHash('sha256').update(raw).digest('hex');
}

function prehashEvidence(policy, target) {
  const payload = target === 'final_envelope'
    ? Object.fromEntries(Object.entries(policy).filter(([key]) => key !== 'policy_hash'))
    : policy;
  const bytes = canonicalizeJcs(payload);
  return { bytes, digest: sha256(bytes) };
}

function registryMatches(policy, registry, registryBytes) {
  const outbound = asObject(policy.outbound_limits);
  const profiles = asObject(policy.profiles);
  if (!registry || typeof registry.registry_version !== 'string' || !outbound || !profiles) return false;
  if (outbound.ip_deny_registry_version !== registry.registry_version) return false;
  if (outbound.ip_deny_registry_sha256 !== sha256(registryBytes)) return false;
  return Object.values(profiles).every(
    (value) => asObject(value)?.address_policy_version === registry.registry_version,
  );
}

function hashMatches(policy, target) {
  if (target === 'pre_hash_payload') return !Object.hasOwn(policy, 'policy_hash');
  if (typeof policy.policy_hash !== 'string') return false;
  return policy.policy_hash === prehashEvidence(policy, target).digest;
}

function canonicalArrays(policy) {
  const profiles = asObject(policy.profiles);
  if (!profiles) return false;
  for (const value of Object.values(profiles)) {
    const profile = asObject(value);
    if (!profile) return false;
    for (const field of ['allowed_response_model_ids', 'approved_hostnames', 'capabilities']) {
      const values = profile[field];
      if (!Array.isArray(values) || values.length === 0 || !values.every((entry) => typeof entry === 'string')) {
        return false;
      }
      if (new Set(values).size !== values.length || !isDeepStrictEqual(values, [...values].sort())) return false;
    }
  }
  return true;
}

const ADAPTER_MAPPING = {
  'openai-chat-completions-v1': 'openai_chat_completions_v1',
  'openai-embeddings-v1': 'openai_embeddings_v1',
};
const OPERATION_CAPABILITIES = {
  contract_field_extraction: 'llm_extraction',
  embedding: 'embedding',
  invoice_field_extraction: 'llm_extraction',
  rag_answer: 'llm_generation',
  report_draft: 'llm_generation',
  risk_explanation: 'llm_generation',
};

function routeGraphMatches(policy) {
  const profiles = asObject(policy.profiles);
  const operations = asObject(policy.operations);
  if (!profiles || !operations) return false;
  const operationIds = Object.keys(operations);
  if (operationIds.length !== Object.keys(OPERATION_CAPABILITIES).length
      || !operationIds.every((id) => Object.hasOwn(OPERATION_CAPABILITIES, id))) return false;

  const profileMappings = new Map();
  const targetTuples = new Set();
  for (const [profileId, value] of Object.entries(profiles)) {
    const profile = asObject(value);
    if (!profile
        || typeof profile.profile_type !== 'string'
        || ADAPTER_MAPPING[profile.profile_type] !== profile.adapter_id
        || typeof profile.adapter_id !== 'string'
        || typeof profile.endpoint_id !== 'string'
        || typeof profile.model_id !== 'string') return false;
    const target = JSON.stringify([profile.adapter_id, profile.endpoint_id, profile.model_id]);
    if (targetTuples.has(target)) return false;
    targetTuples.add(target);
    profileMappings.set(profileId, profile);
  }

  const referenced = new Set();
  for (const [operationId, requiredCapability] of Object.entries(OPERATION_CAPABILITIES)) {
    const operation = asObject(operations[operationId]);
    if (!operation || typeof operation.primary_profile_id !== 'string'
        || !profileMappings.has(operation.primary_profile_id)) return false;
    const routeIds = [operation.primary_profile_id];
    if (operation.fallback_profile_id !== null) {
      if (typeof operation.fallback_profile_id !== 'string'
          || operation.fallback_profile_id === operation.primary_profile_id) return false;
      routeIds.push(operation.fallback_profile_id);
    }
    for (const profileId of routeIds) {
      const profile = profileMappings.get(profileId);
      if (!profile || !Array.isArray(profile.capabilities)
          || !profile.capabilities.includes(requiredCapability)) return false;
      referenced.add(profileId);
    }
  }

  const report = asObject(operations.report_draft);
  if (!report || typeof report.report_use_fallback !== 'boolean') return false;
  if (report.report_use_fallback === false
      && (report.fallback_profile_id !== null || report.max_attempts !== 2)) return false;
  if (report.report_use_fallback === true
      && (typeof report.fallback_profile_id !== 'string' || report.max_attempts !== 3)) return false;
  return referenced.size === profileMappings.size
    && [...profileMappings.keys()].every((profileId) => referenced.has(profileId));
}

function hostnameIsCanonical(hostname) {
  if (typeof hostname !== 'string' || hostname.length > 253 || hostname.endsWith('.')
      || hostname !== hostname.toLowerCase() || !/^[\x00-\x7f]+$/.test(hostname)) return false;
  const labels = hostname.split('.');
  if (labels.length === 0 || labels.some((label) => !label || label.startsWith('xn--') || !HOST_LABEL.test(label))) {
    return false;
  }
  if (labels.every((label) => LEGACY_IPV4_LABEL.test(label))) return false;
  return true;
}

function rawUrlParts(value) {
  const match = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(\?[^#]*)?(#.*)?$/.exec(value);
  if (!match || !match[2] || match[2].includes('@') || match[2].startsWith('[')) return null;
  let host = match[2];
  let port = null;
  if (host.includes(':')) {
    const split = host.lastIndexOf(':');
    const portText = host.slice(split + 1);
    host = host.slice(0, split);
    if (host.includes(':') || !/^[0-9]+$/.test(portText)) return null;
    port = Number(portText);
  }
  return { scheme: match[1], host, port, path: match[3], query: match[4] ?? '', fragment: match[5] ?? '' };
}

function hostBindingsMatch(policy) {
  const profiles = asObject(policy.profiles);
  if (!profiles) return false;
  for (const value of Object.values(profiles)) {
    const profile = asObject(value);
    if (!profile || typeof profile.base_url !== 'string' || typeof profile.network_scope !== 'string'
        || !Array.isArray(profile.approved_hostnames) || profile.approved_hostnames.length === 0
        || !profile.approved_hostnames.every((host) => typeof host === 'string' && hostnameIsCanonical(host))) {
      return false;
    }
    const parts = rawUrlParts(profile.base_url);
    if (!parts || !hostnameIsCanonical(parts.host) || !profile.approved_hostnames.includes(parts.host)
        || parts.path !== '/v1' || parts.query || parts.fragment
        || (parts.port !== null && (!Number.isInteger(parts.port) || parts.port < 1 || parts.port > 65535))) {
      return false;
    }
    if (profile.network_scope === 'external_public' && parts.scheme !== 'https') return false;
    if (profile.network_scope === 'internal_service' && !['http', 'https'].includes(parts.scheme)) return false;
    if (!['external_public', 'internal_service'].includes(profile.network_scope)) return false;
  }
  return true;
}

function networkFromAddress(version, address, prefix) {
  const bits = version === 4 ? 32 : 128;
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > bits) return null;
  const hostBits = BigInt(bits - prefix);
  const hostMask = hostBits === 0n ? 0n : (1n << hostBits) - 1n;
  const networkAddress = address & ~hostMask;
  if (networkAddress !== address) return null;
  return { version, bits, address, prefix, end: address | hostMask };
}

function parseIpv4Address(text) {
  const parts = text.split('.');
  if (parts.length !== 4 || parts.some((part) => !/^(?:0|[1-9][0-9]{0,2})$/.test(part))) return null;
  const octets = parts.map(Number);
  if (octets.some((octet) => octet > 255)) return null;
  return octets.reduce((address, octet) => (address << 8n) | BigInt(octet), 0n);
}

function formatIpv4(address) {
  return [24n, 16n, 8n, 0n].map((shift) => Number((address >> shift) & 255n)).join('.');
}

function parseIpv6Address(text) {
  if (!text || text.includes('.') || (text.match(/::/g) ?? []).length > 1) return null;
  const hasCompression = text.includes('::');
  const [leftText, rightText = ''] = hasCompression ? text.split('::') : [text, ''];
  const left = leftText ? leftText.split(':') : [];
  const right = rightText ? rightText.split(':') : [];
  if ([...left, ...right].some((part) => !/^[0-9a-fA-F]{1,4}$/.test(part))) return null;
  if ((!hasCompression && left.length !== 8) || (hasCompression && left.length + right.length >= 8)) return null;
  const groups = hasCompression
    ? [...left, ...Array(8 - left.length - right.length).fill('0'), ...right]
    : left;
  return groups.reduce((address, group) => (address << 16n) | BigInt(`0x${group}`), 0n);
}

function formatIpv6(address) {
  const groups = [];
  for (let index = 0; index < 8; index += 1) {
    groups.push(Number((address >> BigInt((7 - index) * 16)) & 0xffffn).toString(16));
  }
  let bestStart = -1;
  let bestLength = 0;
  for (let index = 0; index < groups.length;) {
    if (groups[index] !== '0') {
      index += 1;
      continue;
    }
    let end = index;
    while (end < groups.length && groups[end] === '0') end += 1;
    if (end - index > bestLength && end - index >= 2) {
      bestStart = index;
      bestLength = end - index;
    }
    index = end;
  }
  if (bestStart < 0) return groups.join(':');
  return `${groups.slice(0, bestStart).join(':')}::${groups.slice(bestStart + bestLength).join(':')}`;
}

function parseNetwork(text) {
  if (typeof text !== 'string') return null;
  const slash = text.lastIndexOf('/');
  if (slash <= 0 || slash === text.length - 1 || text.slice(0, slash).includes('/')) return null;
  const addressText = text.slice(0, slash);
  const prefixText = text.slice(slash + 1);
  if (!/^(?:0|[1-9][0-9]*)$/.test(prefixText)) return null;
  const prefix = Number(prefixText);
  const ipv4 = parseIpv4Address(addressText);
  if (ipv4 !== null) {
    const network = networkFromAddress(4, ipv4, prefix);
    return network ? { ...network, canonical: `${formatIpv4(network.address)}/${network.prefix}` } : null;
  }
  const ipv6 = parseIpv6Address(addressText);
  if (ipv6 === null) return null;
  const network = networkFromAddress(6, ipv6, prefix);
  return network ? { ...network, canonical: `${formatIpv6(network.address)}/${network.prefix}` } : null;
}

function networksOverlap(left, right) {
  return left.version === right.version && left.address <= right.end && right.address <= left.end;
}

function networkIsSubnet(left, right) {
  return left.version === right.version && left.address >= right.address && left.end <= right.end;
}

function normalizeMappedNetwork(network) {
  if (network.version === 6 && network.prefix >= 96 && network.address >> 32n === 0xffffn) {
    return networkFromAddress(4, network.address & 0xffffffffn, network.prefix - 96);
  }
  return network;
}

function canonicalCidrSets(policy) {
  const profiles = asObject(policy.profiles);
  if (!profiles) return false;
  for (const value of Object.values(profiles)) {
    const profile = asObject(value);
    if (!profile || !Array.isArray(profile.allowed_cidrs) || profile.allowed_cidrs.length === 0
        || !profile.allowed_cidrs.every((cidr) => typeof cidr === 'string')) return false;
    const networks = profile.allowed_cidrs.map(parseNetwork);
    if (networks.some((network) => !network)
        || networks.some((network, index) => network.canonical !== profile.allowed_cidrs[index] || network.prefix === 0)
        || new Set(profile.allowed_cidrs).size !== profile.allowed_cidrs.length) return false;
    const sorted = [...networks].sort((left, right) => {
      if (left.version !== right.version) return left.version - right.version;
      if (left.address !== right.address) return left.address < right.address ? -1 : 1;
      return left.prefix - right.prefix;
    });
    if (!networks.every((network, index) => network === sorted[index])) return false;
    for (let index = 0; index < networks.length; index += 1) {
      if (networks.slice(index + 1).some((other) => networksOverlap(networks[index], other))) return false;
    }
  }
  return true;
}

function registryEntries(registry) {
  if (!registry || !Array.isArray(registry.entries)) return null;
  const entries = [];
  for (const value of registry.entries) {
    const entry = asObject(value);
    if (!entry || typeof entry.cidr !== 'string' || !Array.isArray(entry.categories)
        || !entry.categories.every((category) => typeof category === 'string')) return null;
    const network = parseNetwork(entry.cidr);
    if (!network) return null;
    entries.push({ network, categories: new Set(entry.categories) });
  }
  return entries;
}

function networkScopeMatches(policy, registry) {
  const entries = registryEntries(registry);
  const profiles = asObject(policy.profiles);
  if (!entries || !profiles) return false;
  const forbiddenInternal = new Set(['loopback', 'link_local', 'metadata']);
  for (const value of Object.values(profiles)) {
    const profile = asObject(value);
    if (!profile || typeof profile.network_scope !== 'string'
        || !Array.isArray(profile.allowed_cidrs) || profile.allowed_cidrs.length === 0) return false;
    const networks = profile.allowed_cidrs.map(parseNetwork);
    if (networks.some((network) => !network || network.prefix === 0)) return false;
    for (const parsed of networks) {
      const network = normalizeMappedNetwork(parsed);
      if (profile.network_scope === 'external_public') {
        if (entries.some((entry) => networksOverlap(network, entry.network))) return false;
        continue;
      }
      if (profile.network_scope !== 'internal_service') return false;
      const eligible = entries.some(
        (entry) => entry.categories.has('app_network_eligible') && networkIsSubnet(network, entry.network),
      );
      const denied = entries.some(
        (entry) => networksOverlap(network, entry.network)
          && [...forbiddenInternal].some((category) => entry.categories.has(category)),
      );
      if (!eligible || denied) return false;
    }
  }
  return true;
}

function rejection(id, ruleId) {
  const [stage, safeErrorCode] = FAILURES[ruleId];
  return {
    id,
    accepted: false,
    stage,
    rule_id: ruleId,
    safe_error_code: safeErrorCode,
    prehash_base64: null,
    prehash_sha256: null,
  };
}

function acceptance(id, evidence) {
  return {
    id,
    accepted: true,
    stage: 'complete',
    rule_id: null,
    safe_error_code: null,
    prehash_base64: evidence.bytes.toString('base64'),
    prehash_sha256: evidence.digest,
  };
}

function canonicalBase64(value, allowEmpty = false) {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0) || value.length % 4 !== 0
      || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error('invalid protocol');
  }
  const decoded = Buffer.from(value, 'base64');
  if (decoded.toString('base64') !== value) throw new Error('invalid protocol');
  return decoded;
}

function hasExactKeys(value, expected) {
  return isDeepStrictEqual(Object.keys(value).sort(), [...expected].sort());
}

function buildAjvValidator(rootSchema) {
  if (ajvVersion !== '8.20.0') throw new Error('unexpected Ajv identity');
  // Frozen allOf branches apply unevaluatedProperties without a sibling type;
  // keep every other Ajv strict check and relax only that strictTypes lint.
  const ajv = new Ajv2020({
    strict: true,
    strictTypes: false,
    allErrors: false,
    validateFormats: false,
  });
  for (const [keyword, schemaType] of [
    ['x-finaudit-invariants', 'array'],
    ['x-finaudit-source-number-grammar', 'string'],
    ['x-finaudit-companion-validator', 'object'],
    ['x-finaudit-cross-field-validation', 'string'],
  ]) {
    ajv.addKeyword({ keyword, schemaType, valid: true, errors: false });
  }
  return ajv.compile(rootSchema);
}

function main() {
  const protocol = asObject(parseStrictJson(fs.readFileSync(0)).value);
  if (!protocol
      || !hasExactKeys(protocol, ['schema_base64', 'registry_base64', 'cases'])
      || !Array.isArray(protocol.cases)
      || protocol.cases.length === 0) throw new Error('invalid protocol');
  const schemaBytes = canonicalBase64(protocol.schema_base64);
  const registryBytes = canonicalBase64(protocol.registry_base64);
  if (sha256(schemaBytes) !== POLICY_SCHEMA_SHA256 || sha256(registryBytes) !== REGISTRY_SHA256) {
    throw new Error('invalid artifact identity');
  }
  const rootSchema = asObject(parseStrictJson(schemaBytes).value);
  if (!rootSchema) throw new Error('invalid schema artifact');
  const schemaValidator = buildAjvValidator(rootSchema);
  let registry = null;
  try {
    registry = asObject(parseStrictJson(registryBytes).value);
  } catch {
    registry = null;
  }

  const ids = new Set();
  const cases = protocol.cases.map((value) => {
    const item = asObject(value);
    if (!item
        || !hasExactKeys(item, ['id', 'raw_policy_base64', 'validation_target'])
        || typeof item.id !== 'string'
        || !CASE_ID.test(item.id)
        || ids.has(item.id)
        || !['final_envelope', 'pre_hash_payload'].includes(item.validation_target)) {
      throw new Error('invalid protocol');
    }
    ids.add(item.id);
    return {
      id: item.id,
      target: item.validation_target,
      raw: canonicalBase64(item.raw_policy_base64, true),
    };
  });

  let schemaCalls = 0;
  const results = cases.map(({ id, target, raw }) => {
    let document;
    try {
      document = parseStrictJson(raw);
    } catch {
      return rejection(id, 'POL-VAL-001');
    }
    if (!integerTokensAreValid(document, rootSchema, selectedSchema(rootSchema, target))) {
      return rejection(id, 'POL-VAL-002');
    }
    const policy = asObject(document.value);
    const hasHash = Boolean(policy && Object.hasOwn(policy, 'policy_hash'));
    if ((target === 'final_envelope' && !hasHash) || (target === 'pre_hash_payload' && hasHash)) {
      return rejection(id, 'POL-VAL-003');
    }
    schemaCalls += 1;
    if (!schemaValidator(document.value)) return rejection(id, 'POL-VAL-004');
    if (!registryMatches(policy, registry, registryBytes)) return rejection(id, 'POL-VAL-005');
    if (!hashMatches(policy, target)) return rejection(id, 'POL-VAL-006');
    if (!canonicalArrays(policy)) return rejection(id, 'POL-VAL-007');
    if (!routeGraphMatches(policy)) return rejection(id, 'POL-VAL-008');
    if (!hostBindingsMatch(policy)) return rejection(id, 'POL-VAL-009');
    if (!canonicalCidrSets(policy)) return rejection(id, 'POL-VAL-010');
    if (!networkScopeMatches(policy, registry)) return rejection(id, 'POL-VAL-011');
    return acceptance(id, prehashEvidence(policy, target));
  });

  if (!guard.assertIntegrity()) {
    process.stderr.write('CR011_ZERO_SOCKET_GUARD_INTEGRITY_REQUIRED\n');
    process.exit(2);
  }
  if (guard.attempts !== 0) {
    process.stderr.write('CR011_ZERO_SOCKET_ATTEMPT_DETECTED\n');
    process.exit(2);
  }
  process.stdout.write(JSON.stringify({
    engine_id: ENGINE_ID,
    schema_calls: schemaCalls,
    results,
    socket_attempts: guard.attempts,
  }));
}

try {
  main();
} catch {
  process.stderr.write('CR011_GATE_B_VALIDATOR_FATAL\n');
  process.exitCode = 2;
}
