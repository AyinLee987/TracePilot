/** Pinned Pi SDK smoke. Default is fake transport; paid mode requires --execute-paid. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PREFIX = path.join(ROOT, '.local/oss/pi');
const VERSION = '1.0.3';
const IMAGE = 'python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4';
const ENDPOINT = 'https://api.deepseek.com/chat/completions';
const MAX_REQUESTS = 8, MAX_OUTPUT = 1024, MAX_INPUT = 25024, MAX_BODY_ASCII = 24000;
const BUDGET_CNY = 2, CNY_PER_USD = 8;
const RESERVE = (MAX_INPUT * 0.30 + MAX_OUTPUT * 1.20) / 1e6 * CNY_PER_USD;
const sha = (text) => createHash('sha256').update(text).digest('hex');
const ascii = (value) => JSON.stringify(value).replace(/[^\x00-\x7f]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
const FIX = `def normalize_tags(tags):
    """Normalize tag strings without changing the input list."""
    result = []
    seen = set()
    for tag in tags:
        value = tag.strip().lower()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
`;
const SYSTEM = 'You repair a single synthetic Python file. Only read_tags, write_tags, and validate are available. Read the file, make the smallest clear repair, and validate it. Do not use shell commands, external files, git, or additional packages. Finish after validation succeeds.';
const CHECKS = `import json, os, sys
sys.path.insert(0, '/work')
from tags import normalize_tags
cases = [([], []), ([' ', '\\t', ''], []), ([' A ', 'a', 'B', ' b ', 'A'], ['a', 'b']), ([' Z', 'Y', 'z', ' x '], ['z', 'y', 'x']), (['Straße', 'STRASSE'], ['straße', 'strasse'])]
passed = []
for original, expected in cases:
    before = list(original)
    result = normalize_tags(original)
    passed.append(isinstance(result, list) and result == expected and original == before and result is not original)
key_absent = 'DEEPSEEK_API_KEY' not in os.environ
print(json.dumps({'passed': all(passed) and key_absent, 'cases': passed, 'api_key_absent': key_absent}))
sys.exit(0 if all(passed) and key_absent else 1)
`;

async function main() {
  const { values } = parseArgs({ options: { 'execute-paid': { type: 'boolean' }, 'dry-run': { type: 'boolean' }, version: { type: 'boolean' }, output: { type: 'string' } } });
  if (values['execute-paid'] && values['dry-run']) throw new Error('conflicting_modes');
  const fake = !values['execute-paid'];
  const pkgPath = path.join(PREFIX, 'node_modules/@earendil-works/pi-coding-agent/package.json');
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
  if (pkg.version !== VERSION) throw new Error('unexpected_pi_version');
  if (values.version) { console.log(JSON.stringify({ package: pkg.name, version: pkg.version, node: process.version })); return; }
  if (!fake && !process.env.DEEPSEEK_API_KEY) throw new Error('missing_DEEPSEEK_API_KEY');
  if (fake) process.env.DEEPSEEK_API_KEY = 'TRACEPILOT_FAKE_CANARY';
  const runRoot = path.join(PREFIX, 'runs');
  fs.mkdirSync(runRoot, { recursive: true });
  const out = path.resolve(values.output ?? path.join(runRoot, `${Date.now()}-${randomUUID()}`));
  const relative = path.relative(runRoot, out);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('output_outside_pi_runs');
  fs.mkdirSync(out, { recursive: false });
  const workspace = path.join(out, 'workspace'), checks = path.join(out, 'checks'), config = path.join(out, 'config');
  for (const dir of [workspace, checks, config]) fs.mkdirSync(dir);
  const initial = fs.readFileSync(path.join(ROOT, 'research/agents/fixtures/tags.py'), 'utf8');
  const task = fs.readFileSync(path.join(ROOT, 'research/agents/fixtures/task.txt'), 'utf8');
  fs.writeFileSync(path.join(workspace, 'tags.py'), initial, { flag: 'wx' });
  fs.writeFileSync(path.join(checks, 'validate.py'), CHECKS, { flag: 'wx' });
  process.env.PI_AGENT_DIR = config;
  process.env.PI_OFFLINE = '1';
  const started = performance.now();
  const elapsed = () => (performance.now() - started) / 1000;
  const fd = fs.openSync(path.join(out, 'events.jsonl'), 'wx');
  let eventCount = 0, closed = false;
  const log = (event, data = {}) => {
    if (closed) return;
    if (++eventCount > 1000) throw new Error('event_cap');
    fs.writeSync(fd, ascii({ event, elapsed_s: elapsed(), synthetic_model: fake, ...data }) + '\n');
    fs.fsyncSync(fd);
  };
  let calls = 0, toolCalls = 0, charged = 0, stopReason = null, current = null, session, unsubscribe;
  let lastValidation = null, lastStopReason = null;
  const controller = new AbortController();
  const nativeFetch = globalThis.fetch;
  // SDK discovery is disabled. Any unexpected implicit fetch is denied as well.
  globalThis.fetch = async () => { throw new Error('implicit_network_disabled'); };
  const childEnv = Object.fromEntries(['PATH', 'Path', 'SystemRoot', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE'].filter(key => process.env[key]).map(key => [key, process.env[key]]));
  const docker = args => spawnSync('docker', args, { encoding: 'utf8', env: childEnv, timeout: 15000, maxBuffer: 16384, windowsHide: true });

  function validate() {
    const name = 'tracepilot-pi-' + randomUUID().replaceAll('-', '');
    const begin = elapsed();
    const args = ['run', '--rm', '--pull', 'never', '--name', name, '--network', 'none', '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32', '--memory', '128m', '--cpus', '0.5', '--mount', `type=bind,source=${workspace},target=/work,readonly`, '--mount', `type=bind,source=${checks},target=/checks,readonly`, IMAGE, 'python', '-I', '-B', '/checks/validate.py'];
    let result;
    try {
      const reply = docker(args);
      try { result = JSON.parse(reply.stdout ?? ''); } catch { result = { passed: false, api_key_absent: null }; }
      result = { passed: reply.status === 0 && result.passed === true, cases: result.cases ?? null, api_key_absent: result.api_key_absent ?? null, exit_code: reply.status, timed_out: reply.error?.code === 'ETIMEDOUT', validation_seconds: elapsed() - begin };
    } finally {
      // This exact UUID name belongs only to this invocation, including after CLI timeout.
      docker(['rm', '-f', name]);
      const inventory = docker(['ps', '-a', '--filter', `name=^/${name}$`, '--format', '{{.Names}}']);
      const cleanupVerified = inventory.status === 0 && inventory.stdout.trim() === '';
      log('container_cleanup', { container_name: name, absent_verified: cleanupVerified });
      if (!cleanupVerified) { stopReason ??= 'container_cleanup_failed'; throw new Error('container_cleanup_failed'); }
    }
    return result;
  }

  function usageOf(raw) {
    if (!raw) return null;
    const input = raw.prompt_tokens, output = raw.completion_tokens, hit = raw.prompt_cache_hit_tokens, miss = raw.prompt_cache_miss_tokens;
    if (![input, output, hit, miss].every(n => Number.isSafeInteger(n) && n >= 0) || hit + miss !== input) return null;
    return { input, output, cache_hit: hit, cache_miss: miss, cost_cny: (miss * 0.30 + hit * 0.006 + output * 1.20) / 1e6 * CNY_PER_USD };
  }

  function fakeSse(payload) {
    const chosen = calls === 1 ? { name: 'read_tags', arguments: {} } : calls === 2 ? { name: 'write_tags', arguments: { content: FIX } } : calls === 3 ? { name: 'validate', arguments: {} } : null;
    const delta = chosen ? { role: 'assistant', tool_calls: [{ index: 0, id: `fake-${calls}`, type: 'function', function: { name: chosen.name, arguments: JSON.stringify(chosen.arguments) } }] } : { role: 'assistant', content: 'Repaired and validated.' };
    const base = { id: `fake-${calls}`, object: 'chat.completion.chunk', created: 0, model: 'FAKE-NO-PAID-MODEL' };
    const input = Math.ceil(ascii(payload).length / 4);
    const chunks = [{ ...base, choices: [{ index: 0, delta, finish_reason: null }] }, { ...base, choices: [{ index: 0, delta: {}, finish_reason: chosen ? 'tool_calls' : 'stop' }] }, { ...base, choices: [], usage: { prompt_tokens: input, completion_tokens: 180, prompt_cache_hit_tokens: 0, prompt_cache_miss_tokens: input, total_tokens: input + 180 } }];
    return new Response(chunks.map(chunk => 'data: ' + JSON.stringify(chunk) + '\n\n').join('') + 'data: [DONE]\n\n', { status: 200, headers: { 'content-type': 'text/event-stream' } });
  }

  async function guardedFetch(input, options = {}) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url !== ENDPOINT) throw new Error('endpoint_not_allowed');
    if (stopReason || controller.signal.aborted) throw new Error('run_stopped');
    if (calls >= MAX_REQUESTS || charged + RESERVE > BUDGET_CNY) { stopReason = 'request_or_budget_cap'; throw new Error(stopReason); }
    if (current) throw new Error('concurrent_model_call');
    const body = typeof options.body === 'string' ? options.body : await input.clone().text();
    const payload = JSON.parse(body);
    const headers = new Headers(options.headers ?? (input instanceof Request ? input.headers : undefined));
    const authorizationVerified = headers.get('authorization') === 'Bearer ' + process.env.DEEPSEEK_API_KEY;
    if (!authorizationVerified) { stopReason = 'authorization_reference_mismatch'; throw new Error(stopReason); }
    if (ascii(payload).length > MAX_BODY_ASCII) { stopReason = 'context_cap'; throw new Error(stopReason); }
    if (payload.model !== 'deepseek-flash' || payload.max_tokens !== MAX_OUTPUT || payload.thinking?.type !== 'disabled' || payload.stream !== true || payload.stream_options?.include_usage !== true) throw new Error('unexpected_payload');
    calls++;
    charged += RESERVE;
    current = { index: calls, started_s: elapsed(), raw_usage: null, response_model: null };
    log('request_started', { index: calls, reservation_cny: RESERVE, authorization_verified: authorizationVerified, payload });
    try {
      const response = fake ? fakeSse(payload) : await nativeFetch(input, { ...options, redirect: 'error', signal: AbortSignal.any([controller.signal, options.signal ?? new AbortController().signal, AbortSignal.timeout(60000)]) });
      if (!response.ok) {
        stopReason = response.status === 402 ? 'insufficient_balance' : `http_error_${response.status}`;
        log('http_error', { index: calls, status: response.status, stop_reason: stopReason });
        await response.body?.cancel();
        throw new Error(stopReason);
      }
      log('response_headers_received', { index: calls, status: response.status });
      return response;
    } catch {
      stopReason ??= 'network_error';
      log('request_transport_failed', { index: calls, stop_reason: stopReason, reservation_retained_cny: RESERVE });
      throw new Error(stopReason);
    }
  }

  const guardTool = (name, fn) => async (_id, params, signal) => {
    if (stopReason || signal?.aborted || controller.signal.aborted) throw new Error('run_stopped');
    if (++toolCalls > 24) { stopReason = 'tool_cap'; throw new Error(stopReason); }
    const begin = elapsed();
    log('tool_started', { name, tool_index: toolCalls });
    const result = await fn(params);
    log('tool_completed', { name, tool_index: toolCalls, tool_seconds: elapsed() - begin, result });
    return { content: [{ type: 'text', text: typeof result === 'string' ? result : JSON.stringify(result) }], details: {} };
  };
  const emptySchema = { type: 'object', properties: {}, additionalProperties: false };
  const tools = [
    { name: 'read_tags', label: 'Read tags.py', description: 'Read the only editable file, tags.py.', parameters: emptySchema, executionMode: 'sequential', execute: guardTool('read_tags', () => fs.readFileSync(path.join(workspace, 'tags.py'), 'utf8')) },
    { name: 'write_tags', label: 'Write tags.py', description: 'Replace the complete contents of tags.py only.', parameters: { type: 'object', properties: { content: { type: 'string', maxLength: 8000 } }, required: ['content'], additionalProperties: false }, executionMode: 'sequential', execute: guardTool('write_tags', ({ content }) => {
      if (typeof content !== 'string' || content.length > 8000) throw new Error('invalid_content');
      const target = path.join(workspace, 'tags.py');
      if (!fs.lstatSync(target).isFile()) throw new Error('not_regular_file');
      fs.writeFileSync(target, content, 'utf8');
      return { written: 'tags.py', bytes: Buffer.byteLength(content) };
    }) },
    { name: 'validate', label: 'Validate repair', description: 'Run independent deterministic checks in an isolated Python container.', parameters: emptySchema, executionMode: 'sequential', execute: guardTool('validate', () => (lastValidation = validate())) },
  ];
  let timeout;
  try {
    const { createAgentSession, createExtensionRuntime, ModelRuntime, SessionManager, SettingsManager } = await import(pathToFileURL(path.join(path.dirname(pkgPath), 'dist/index.js')).href);
    const resourceLoader = {
      getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
      getSkills: () => ({ skills: [], diagnostics: [] }), getPrompts: () => ({ prompts: [], diagnostics: [] }), getThemes: () => ({ themes: [], diagnostics: [] }),
      getAgentsFiles: () => ({ agentsFiles: [] }), getSystemPrompt: () => SYSTEM, getSystemPromptSource: () => undefined,
      getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [], extendResources: () => {}, reload: async () => {},
    };
    const runtime = await ModelRuntime.create({ authPath: path.join(config, 'auth.json'), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
    runtime.registerProvider('tracepilot-deepseek', { baseUrl: 'https://api.deepseek.com', apiKey: '$DEEPSEEK_API_KEY', api: 'openai-completions', authHeader: true, models: [{ id: 'deepseek-flash', name: 'DeepSeek flash smoke', reasoning: true, input: ['text'], contextWindow: 32768, maxTokens: MAX_OUTPUT, cost: { input: 0.30, output: 1.20, cacheRead: 0.006, cacheWrite: 0.30 }, compat: { maxTokensField: 'max_tokens', thinkingFormat: 'deepseek', supportsDeveloperRole: false } }] });
    const nativeStream = runtime.streamSimple.bind(runtime);
    runtime.streamSimple = (model, context, options = {}) => nativeStream(model, context, {
      ...options, maxTokens: MAX_OUTPUT, temperature: 0, maxRetries: 0, timeoutMs: 60000, fetch: guardedFetch,
      signal: AbortSignal.any([controller.signal, options.signal ?? new AbortController().signal]),
      onPayload: async (payload) => { const transformed = await options.onPayload?.(payload, model) ?? payload; return { ...transformed, max_tokens: MAX_OUTPUT, stream_options: { include_usage: true }, thinking: { type: 'disabled' }, temperature: 0 }; },
      onProviderStreamEvent: async (data, selected) => {
        if (current && data?.usage) current.raw_usage = data.usage;
        if (current && typeof data?.model === 'string') {
          current.response_model = data.model;
          if (!fake && data.model !== 'deepseek-flash') { stopReason = 'unexpected_response_model'; controller.abort(); }
        }
        await options.onProviderStreamEvent?.(data, selected);
      },
    });
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0, timeoutMs: 60000 } }, cacheWarming: 'off', enableAnalytics: false, enableInstallTelemetry: false, packages: [], extensions: [], skills: [], prompts: [], themes: [], defaultProjectTrust: 'never', enableSkillCommands: false, transport: 'sse' });
    ({ session } = await createAgentSession({ cwd: workspace, agentDir: config, modelRuntime: runtime, model: runtime.getModel('tracepilot-deepseek', 'deepseek-flash'), thinkingLevel: 'off', resourceLoader, tools: tools.map(tool => tool.name), customTools: tools, settingsManager, sessionManager: SessionManager.inMemory(workspace) }));
    const active = session.getActiveToolNames().sort();
    if (JSON.stringify(active) !== JSON.stringify(tools.map(tool => tool.name).sort())) throw new Error('unexpected_tools');
    if (session.systemPrompt.replace(/<cwd>\n[^]*?\n<\/cwd>/g, '').trim() !== SYSTEM) throw new Error('unexpected_instruction_discovery');
    const manifest = { version: 1, package: pkg.name, package_version: VERSION, node: process.version, synthetic_model: fake, endpoint: ENDPOINT, model: 'deepseek-flash', thinking: 'disabled', max_requests: MAX_REQUESTS, max_output: MAX_OUTPUT, max_input_reservation: MAX_INPUT, max_payload_ascii_chars: MAX_BODY_ASCII, budget_cny: BUDGET_CNY, reservation_cny: RESERVE, cny_per_usd_planning: CNY_PER_USD, usd_per_million: { input_miss: 0.30, input_hit: 0.006, output: 1.20 }, cost_basis: 'peak_price_estimate_not_invoice', retries: { framework: 0, provider: 0, http_sdk: 0 }, docker_image: IMAGE, active_tools: active, system_prompt: SYSTEM, ancestor_instructions_loaded: false, task, initial_sha256: sha(initial), script_sha256: sha(fs.readFileSync(fileURLToPath(import.meta.url))), npm_lock_sha256: sha(fs.readFileSync(path.join(PREFIX, 'package-lock.json'))) };
    fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2), { flag: 'wx' });
    log('session_configured', { active_tools: active, ancestor_instructions_loaded: false, effective_system_prompt: session.systemPrompt });
    const before = validate();
    if (before.passed || before.api_key_absent !== true) throw new Error('invalid_initial_validation_or_key_leak');
    log('initial_validation', before);
    unsubscribe = session.subscribe(event => {
      if (event.type === 'message_end' && event.message?.role === 'assistant') {
        const message = event.message;
        lastStopReason = message.stopReason;
        if (current && !fake && current.response_model !== 'deepseek-flash') stopReason ??= 'unexpected_response_model';
        const usage = stopReason === 'unexpected_response_model' ? null : usageOf(current?.raw_usage);
        if (current) {
          if (usage) charged += usage.cost_cny - RESERVE;
          else stopReason ??= 'unknown_usage';
          if (usage && (usage.input > MAX_INPUT || usage.output > MAX_OUTPUT)) stopReason ??= 'usage_bound_exceeded';
          log('request_completed', { index: current.index, request_seconds: elapsed() - current.started_s, usage: usage ?? { state: 'unknown', input: null, output: null, cache_hit: null, cache_miss: null }, framework_usage: usage ? message.usage : null, response_model: current.response_model, stop_reason: message.stopReason, content: message.stopReason === 'error' ? null : message.content, charged_cny: charged });
          current = null;
        }
        if (message.stopReason === 'error' || message.stopReason === 'aborted') stopReason ??= 'model_error_or_abort';
        if (stopReason) controller.abort();
      } else if (['agent_start', 'agent_end', 'agent_settled', 'auto_retry_start', 'auto_compaction_start'].includes(event.type)) {
        log(event.type);
        if (event.type.startsWith('auto_')) { stopReason = 'unexpected_automatic_call'; controller.abort(); }
      }
    });
    timeout = setTimeout(() => { stopReason ??= 'wall_time_cap'; controller.abort(); void session.abort(); }, 180000);
    await session.prompt(task);
    if (stopReason === 'container_cleanup_failed') {
      log('independent_final_validation_skipped', { reason: stopReason });
    } else {
      lastValidation = validate();
      log('independent_final_validation', lastValidation);
    }
  } catch (error) {
    stopReason ??= 'runner_error';
    log('runner_stopped', { stop_reason: stopReason, error_type: error?.name ?? 'Error', local_guard: /^[a-z_]+$/.test(error?.message ?? '') ? error.message : null });
  } finally {
    clearTimeout(timeout);
    unsubscribe?.();
    session?.dispose();
    globalThis.fetch = nativeFetch;
    const summary = { output: out, synthetic_model: fake, package_version: VERSION, calls, tool_calls: toolCalls, peak_price_estimate_cny: charged, stop_reason: stopReason, model_stop_reason: lastStopReason, validation: lastValidation, passed: lastValidation?.passed === true && !stopReason, elapsed_s: elapsed(), unknown_inflight_usage: current !== null };
    fs.writeFileSync(path.join(out, 'summary.json'), JSON.stringify(summary, null, 2), { flag: 'wx' });
    log('run_completed', summary);
    closed = true;
    fs.closeSync(fd);
    console.log(JSON.stringify(summary, null, 2));
    if (!summary.passed) process.exitCode = 1;
  }
}

main().catch(error => { console.error(JSON.stringify({ stopped: true, error_type: error?.name ?? 'Error' })); process.exitCode = 1; });
