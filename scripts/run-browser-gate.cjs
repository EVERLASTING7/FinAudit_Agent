'use strict'

const { spawn } = require('node:child_process')
const { createHash } = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const projectRoot = path.resolve(__dirname, '..')
const WebSocket = require(require.resolve('ws', { paths: [path.join(projectRoot, 'frontend')] }))

const COMPLETE_TOKENS = Object.freeze({
  Accessibility: 'COMPLETE_DISPOSABLE_REPORT_BROWSER_V1',
  DocumentCorrection: 'COMPLETE_DISPOSABLE_DOCUMENT_CORRECTION_BROWSER_V1',
  InvoiceDuplicate: 'COMPLETE_DISPOSABLE_INVOICE_DUPLICATE_BROWSER_V1',
  PolicyRevocation: 'COMPLETE_DISPOSABLE_POLICY_REVOCATION_BROWSER_V1',
  Report: 'COMPLETE_DISPOSABLE_REPORT_BROWSER_V1',
})
const READY_MARKERS = Object.freeze({
  Accessibility: 'BROWSER_GATE_REPORT_RUNTIME=READY',
  DocumentCorrection: 'BROWSER_GATE_DOCUMENT_CORRECTION_RUNTIME=READY',
  InvoiceDuplicate: 'BROWSER_GATE_INVOICE_DUPLICATE_RUNTIME=READY',
  PolicyRevocation: 'BROWSER_GATE_POLICY_REVOCATION_RUNTIME=READY',
  Report: 'BROWSER_GATE_REPORT_RUNTIME=READY',
})
const PASSWORDS = Object.freeze({
  admin: 'Synthetic-Admin-Read-2026!',
  finance: 'Synthetic-Financial-Read-2026!',
  matrix: 'Synthetic-Role-Matrix-2026!',
})

function invariant(condition, code) {
  if (!condition) throw new Error(code)
}

function delay(milliseconds) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds)
    timer.unref?.()
  })
}

async function runProcess(file, arguments_, timeoutMilliseconds = 15000) {
  return new Promise((resolve, reject) => {
    const child = spawn(file, arguments_, {
      cwd: projectRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => {
      if (stdout.length < 16000) stdout += chunk.toString('utf8')
    })
    child.stderr.on('data', (chunk) => {
      if (stderr.length < 16000) stderr += chunk.toString('utf8')
    })
    const timeout = setTimeout(() => {
      child.kill()
      reject(new Error('BROWSER_RUNNER_CHILD_PROCESS_TIMEOUT'))
    }, timeoutMilliseconds)
    child.once('error', (error) => {
      clearTimeout(timeout)
      reject(error)
    })
    child.once('exit', (code, signal) => {
      clearTimeout(timeout)
      resolve({ code, signal, stderr, stdout })
    })
  })
}

async function focusAccessibilityEdge(profilePath) {
  const powershellPath = process.env.FINAUDIT_POWERSHELL_PATH
  const helperPath = path.join(projectRoot, 'scripts', 'focus-accessibility-edge.ps1')
  invariant(
    typeof powershellPath === 'string' &&
      path.isAbsolute(powershellPath) &&
      fs.existsSync(powershellPath) &&
      fs.existsSync(helperPath),
    'BROWSER_ACCESSIBILITY_EDGE_FOCUS_RUNTIME_MISSING',
  )
  const result = await runProcess(
    powershellPath,
    ['-NoProfile', '-File', helperPath, '-ProfilePath', profilePath],
  )
  invariant(
    result.code === 0 && result.signal === null,
    `BROWSER_ACCESSIBILITY_EDGE_FOCUS_FAILED_${result.stderr.trim()}`,
  )
  const payload = JSON.parse(result.stdout.trim())
  invariant(
    payload.schema_version === 'finaudit-accessibility-edge-focus-v1' &&
      Number.isInteger(payload.owned_process_count) &&
      payload.owned_process_count > 0,
    'BROWSER_ACCESSIBILITY_EDGE_FOCUS_RESULT_INVALID',
  )
  console.log('BROWSER_ACCESSIBILITY_EDGE_FOREGROUND=PASS')
}

function parseArguments() {
  const values = Object.create(null)
  for (let index = 2; index < process.argv.length; index += 2) {
    const name = process.argv[index]
    const value = process.argv[index + 1]
    invariant(typeof name === 'string' && name.startsWith('--') && typeof value === 'string', 'BROWSER_RUNNER_ARGUMENTS_INVALID')
    values[name.slice(2)] = value
  }
  invariant(Object.hasOwn(COMPLETE_TOKENS, values.mode), 'BROWSER_RUNNER_MODE_INVALID')
  invariant(path.isAbsolute(values.python) && fs.existsSync(values.python), 'BROWSER_RUNNER_PYTHON_INVALID')
  invariant(/^\d{4,5}$/.test(values.port), 'BROWSER_RUNNER_PORT_INVALID')
  const port = Number(values.port)
  invariant(port >= 1024 && port <= 65535, 'BROWSER_RUNNER_PORT_INVALID')
  return { mode: values.mode, python: values.python, port }
}

function browserPath(mode) {
  const edge = mode === 'Accessibility'
  const configured = edge
    ? process.env.FINAUDIT_BROWSER_EDGE_PATH
    : process.env.FINAUDIT_BROWSER_CHROME_PATH
  const candidates = (edge
    ? [
        configured,
        'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
        'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
        process.env.LOCALAPPDATA
          ? path.join(process.env.LOCALAPPDATA, 'Microsoft', 'Edge', 'Application', 'msedge.exe')
          : undefined,
      ]
    : [
        configured,
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        process.env.LOCALAPPDATA
          ? path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe')
          : undefined,
      ]).filter((value) => typeof value === 'string' && value.length > 0)
  const resolved = candidates.find((candidate) => fs.existsSync(candidate))
  invariant(resolved !== undefined, edge ? 'BROWSER_RUNNER_EDGE_MISSING' : 'BROWSER_RUNNER_CHROME_MISSING')
  return resolved
}

function startApplication(python, mode) {
  const child = spawn(python, ['-m', 'tests.manual_financial_read_browser'], {
    cwd: path.join(projectRoot, 'backend'),
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  const markers = new Map()
  let readyResolve
  let readyReject
  let ready = false
  let stdoutBuffer = ''
  const readyPromise = new Promise((resolve, reject) => {
    readyResolve = resolve
    readyReject = reject
  })
  const consume = (chunk, stream) => {
    stream.write(chunk)
    if (stream !== process.stdout) return
    stdoutBuffer += chunk.toString('utf8')
    const lines = stdoutBuffer.split(/\r?\n/)
    stdoutBuffer = lines.pop() ?? ''
    for (const line of lines) {
      const separator = line.indexOf('=')
      if (separator > 0) markers.set(line.slice(0, separator), line.slice(separator + 1))
      if (!ready && line === READY_MARKERS[mode]) {
        ready = true
        readyResolve()
      }
    }
  }
  child.stdout.on('data', (chunk) => consume(chunk, process.stdout))
  child.stderr.on('data', (chunk) => consume(chunk, process.stderr))
  child.once('error', (error) => readyReject(error))
  const exitPromise = new Promise((resolve) => {
    child.once('exit', (code, signal) => {
      if (!ready) readyReject(new Error(`BROWSER_GATE_APPLICATION_EARLY_EXIT_${code ?? signal ?? 'UNKNOWN'}`))
      resolve({ code, signal })
    })
  })
  return { child, exitPromise, markers, readyPromise }
}

async function waitForFile(file, timeoutMilliseconds) {
  const deadline = Date.now() + timeoutMilliseconds
  while (Date.now() < deadline) {
    if (fs.existsSync(file)) return
    await delay(100)
  }
  throw new Error('BROWSER_RUNNER_DEVTOOLS_TIMEOUT')
}

async function startBrowser(mode) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'finaudit-browser-gate-'))
  const activePortFile = path.join(profile, 'DevToolsActivePort')
  const arguments_ = [
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-default-apps',
    '--disable-sync',
    '--metrics-recording-only',
    '--no-pings',
    '--proxy-server=direct://',
    '--proxy-bypass-list=*',
    '--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1',
    '--window-size=1440,1200',
    'about:blank',
  ]
  if (mode !== 'Accessibility') arguments_.unshift('--headless=new')
  const child = spawn(
    browserPath(mode),
    arguments_,
    { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: mode !== 'Accessibility' },
  )
  let stderr = ''
  child.stderr.on('data', (chunk) => {
    if (stderr.length < 4000) stderr += chunk.toString('utf8')
  })
  try {
    await waitForFile(activePortFile, 15000)
    const [port, browserPath] = fs.readFileSync(activePortFile, 'utf8').trim().split(/\r?\n/)
    invariant(/^\d{2,5}$/.test(port ?? '') && browserPath?.startsWith('/devtools/browser/'), 'BROWSER_RUNNER_DEVTOOLS_IDENTITY_INVALID')
    return {
      child,
      profile,
      stderr: () => stderr,
      url: `ws://127.0.0.1:${port}${browserPath}`,
    }
  } catch (error) {
    child.kill()
    fs.rmSync(profile, { force: true, recursive: true })
    throw error
  }
}

class CdpClient {
  constructor(url) {
    this.nextId = 1
    this.pending = new Map()
    this.handlers = new Set()
    this.socket = new WebSocket(url)
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.once('open', resolve)
      this.socket.once('error', reject)
    })
    this.socket.on('message', (raw) => {
      const message = JSON.parse(raw.toString('utf8'))
      if (message.id !== undefined) {
        const pending = this.pending.get(message.id)
        if (!pending) return
        this.pending.delete(message.id)
        clearTimeout(pending.timeout)
        if (message.error) pending.reject(new Error(`CDP_${message.error.code}_${message.error.message}`))
        else pending.resolve(message.result ?? {})
        return
      }
      for (const handler of this.handlers) handler(message)
    })
  }

  onEvent(handler) {
    this.handlers.add(handler)
  }

  send(method, params = {}, sessionId = undefined, timeoutMilliseconds = 20000) {
    const id = this.nextId++
    const payload = { id, method, params }
    if (sessionId !== undefined) payload.sessionId = sessionId
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`CDP_${method}_TIMEOUT`))
      }, timeoutMilliseconds)
      this.pending.set(id, { reject, resolve, timeout })
      this.socket.send(JSON.stringify(payload))
    })
  }

  close() {
    if (this.socket.readyState === WebSocket.OPEN) this.socket.close()
  }
}

async function attachPage(client) {
  const targets = await client.send('Target.getTargets')
  const pages = targets.targetInfos.filter((target) => target.type === 'page')
  invariant(pages.length === 1, 'BROWSER_RUNNER_PAGE_TARGET_INVALID')
  const attached = await client.send('Target.attachToTarget', {
    flatten: true,
    targetId: pages[0].targetId,
  })
  const sessionId = attached.sessionId
  await Promise.all([
    client.send('Accessibility.enable', {}, sessionId),
    client.send('Page.enable', {}, sessionId),
    client.send('Runtime.enable', {}, sessionId),
    client.send('Log.enable', {}, sessionId),
    client.send('Network.enable', {}, sessionId),
  ])
  return sessionId
}

function createPage(client, sessionId, baseUrl) {
  const consoleProblems = new Set()
  const expectedNetworkProblems = new Set()
  let phase = 'initial'
  client.onEvent((message) => {
    if (message.sessionId !== sessionId) return
    if (message.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(message.params.type)) {
      const text = message.params.args.map((arg) => arg.value ?? arg.description ?? arg.type).join(' ')
      consoleProblems.add(`${phase}: console.${message.params.type}: ${text}`)
    }
    if (message.method === 'Runtime.exceptionThrown') {
      consoleProblems.add(`${phase}: exception: ${message.params.exceptionDetails.text}`)
    }
    if (message.method === 'Log.entryAdded' && ['error', 'warning'].includes(message.params.entry.level)) {
      const entry = message.params.entry
      const url = entry.url ?? ''
      const expectedContractEvidence =
        phase.startsWith('accessibility.edge-route./contracts/') &&
        /\/api\/v1\/contracts\/[0-9a-f-]{36}\/evidence$/.test(url) &&
        entry.text.includes('409')
      const expectedAnonymousRefresh =
        phase === 'accessibility.edge-narrator' &&
        url === `${baseUrl}/api/v1/auth/refresh` &&
        entry.text.includes('401')
      const expectedFileFixtureBoundary =
        phase.startsWith('accessibility.edge-route./files/') &&
        (
          (/\/api\/v1\/files\/[0-9a-f-]{36}\/preview$/.test(url) && entry.text.includes('503')) ||
          (/\/api\/v1\/files\/[0-9a-f-]{36}\/text-preview\?max_chars=100000$/.test(url) && entry.text.includes('409')) ||
          (/\/api\/v1\/files\/[0-9a-f-]{36}\/document-correction-blocks\?page_size=50$/.test(url) && entry.text.includes('409'))
        )
      if (expectedContractEvidence || expectedAnonymousRefresh || expectedFileFixtureBoundary) {
        expectedNetworkProblems.add(`${phase}:${entry.text}:${url}`)
        return
      }
      consoleProblems.add(
        `${phase}: log.${entry.level}: ${entry.text} [${url || entry.source || 'unknown'}]`,
      )
    }
  })

  async function evaluate(expression) {
    const response = await client.send(
      'Runtime.evaluate',
      { expression, awaitPromise: true, returnByValue: true },
      sessionId,
    )
    if (response.exceptionDetails) {
      throw new Error(`BROWSER_EVALUATION_FAILED_${response.exceptionDetails.text}`)
    }
    return response.result.value
  }

  async function waitFor(code, expression, timeoutMilliseconds = 30000) {
    const deadline = Date.now() + timeoutMilliseconds
    while (Date.now() < deadline) {
      if (await evaluate(`Boolean(${expression})`)) return
      await delay(100)
    }
    throw new Error(code)
  }

  async function navigate(route) {
    await client.send('Page.navigate', { url: `${baseUrl}${route}` }, sessionId)
    await waitFor('BROWSER_NAVIGATION_TIMEOUT', `location.href.startsWith(${JSON.stringify(baseUrl)}) && document.readyState === 'complete'`)
  }

  async function reload() {
    await client.send('Page.reload', { ignoreCache: true }, sessionId)
    await waitFor('BROWSER_RELOAD_TIMEOUT', `document.readyState === 'complete'`)
  }

  async function bringToFront() {
    await client.send('Page.bringToFront', {}, sessionId)
  }

  async function pressKey(key) {
    const definitions = {
      ArrowRight: { code: 'ArrowRight', keyCode: 39 },
      End: { code: 'End', keyCode: 35 },
      Enter: { code: 'Enter', keyCode: 13 },
      Home: { code: 'Home', keyCode: 36 },
      Tab: { code: 'Tab', keyCode: 9 },
    }
    const definition = definitions[key]
    invariant(definition !== undefined, 'BROWSER_KEY_UNSUPPORTED')
    await client.send(
      'Input.dispatchKeyEvent',
      {
        type: 'rawKeyDown',
        key,
        code: definition.code,
        windowsVirtualKeyCode: definition.keyCode,
        nativeVirtualKeyCode: definition.keyCode,
      },
      sessionId,
    )
    await client.send(
      'Input.dispatchKeyEvent',
      {
        type: 'keyUp',
        key,
        code: definition.code,
        windowsVirtualKeyCode: definition.keyCode,
        nativeVirtualKeyCode: definition.keyCode,
      },
      sessionId,
    )
  }

  async function accessibilityTree() {
    const response = await client.send('Accessibility.getFullAXTree', {}, sessionId)
    return response.nodes
  }

  async function setValue(selector, value) {
    const result = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value');
      if (!descriptor || typeof descriptor.set !== 'function') return false;
      descriptor.set.call(element, ${JSON.stringify(value)});
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`)
    invariant(result === true, 'BROWSER_SET_VALUE_FAILED')
  }

  async function typeText(value) {
    await client.send('Input.insertText', { text: value }, sessionId)
  }

  async function selectFirst(selector) {
    const result = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!(element instanceof HTMLSelectElement) || element.options.length < 2) return false;
      const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
      descriptor.set.call(element, element.options[1].value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`)
    invariant(result === true, 'BROWSER_SELECT_FIRST_FAILED')
  }

  async function click(selector) {
    const result = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!(element instanceof HTMLElement) || element.matches(':disabled')) return false;
      element.click();
      return true;
    })()`)
    invariant(result === true, 'BROWSER_CLICK_FAILED')
  }

  async function clickTab(label) {
    await waitFor(
      'BROWSER_TAB_MISSING',
      `[...document.querySelectorAll('[role="tab"]')].some((item) => item.textContent?.trim().startsWith(${JSON.stringify(label)}))`,
    )
    const result = await evaluate(`(() => {
      const element = [...document.querySelectorAll('[role="tab"]')].find(
        (item) => item.textContent?.trim().startsWith(${JSON.stringify(label)}),
      );
      if (!(element instanceof HTMLElement)) return false;
      element.click();
      return true;
    })()`)
    invariant(result === true, 'BROWSER_TAB_CLICK_FAILED')
  }

  async function login(username, password, redirect, expectedPath = redirect) {
    await navigate(`/login?redirect=${encodeURIComponent(redirect)}`)
    await waitFor('BROWSER_LOGIN_FORM_MISSING', `document.querySelector('#username') && document.querySelector('#password')`)
    await setValue('#username', username)
    await setValue('#password', password)
    await click('form button[type="submit"]')
    await waitFor('BROWSER_LOGIN_REDIRECT_TIMEOUT', `location.pathname === ${JSON.stringify(expectedPath)}`)
  }

  async function switchUser(username, password, redirect) {
    await logout()
    await setValue('#username', username)
    await setValue('#password', password)
    await click('form button[type="submit"]')
    await waitFor('BROWSER_SWITCH_LOGIN_TIMEOUT', `location.pathname !== '/login'`)
    if ((await evaluate('location.pathname')) !== redirect) await navigate(redirect)
    await waitFor('BROWSER_SWITCH_REDIRECT_TIMEOUT', `location.pathname === ${JSON.stringify(redirect)}`)
  }

  async function logout() {
    const clicked = await evaluate(`(() => {
      const button = [...document.querySelectorAll('button')].find(
        (item) => item.textContent?.trim() === '退出登录',
      );
      if (!(button instanceof HTMLButtonElement) || button.disabled) return false;
      button.click();
      return true;
    })()`)
    invariant(clicked === true, 'BROWSER_LOGOUT_BUTTON_MISSING')
    await waitFor('BROWSER_LOGOUT_TIMEOUT', `location.pathname === '/login' && document.querySelector('#username')`)
  }

  async function fetchJson(route, options = {}) {
    return evaluate(`(async () => {
      const response = await fetch(${JSON.stringify(route)}, ${JSON.stringify(options)});
      const text = await response.text();
      let body = null;
      try { body = text ? JSON.parse(text) : null; } catch { body = text; }
      return { status: response.status, body };
    })()`)
  }

  return {
    accessibilityTree,
    bringToFront,
    click,
    clickTab,
    consoleProblems,
    evaluate,
    expectedNetworkProblems,
    fetchJson,
    login,
    logout,
    navigate,
    pressKey,
    reload,
    selectFirst,
    setValue,
    setPhase(value) {
      phase = value
    },
    switchUser,
    typeText,
    waitFor,
  }
}

function createDownloadTracker(client, downloadDirectory) {
  const downloads = new Map()
  fs.mkdirSync(downloadDirectory, { recursive: true })
  client.onEvent((message) => {
    if (message.method === 'Browser.downloadWillBegin') {
      downloads.set(message.params.guid, {
        progress: null,
        willBegin: message.params,
      })
    }
    if (message.method === 'Browser.downloadProgress') {
      const current = downloads.get(message.params.guid) ?? {
        progress: null,
        willBegin: null,
      }
      current.progress = message.params
      downloads.set(message.params.guid, current)
    }
  })

  async function waitForCompleted(timeoutMilliseconds = 30000) {
    const deadline = Date.now() + timeoutMilliseconds
    while (Date.now() < deadline) {
      for (const download of downloads.values()) {
        if (download.progress?.state === 'canceled') {
          throw new Error('BROWSER_REPORT_DOWNLOAD_CANCELED')
        }
        if (download.willBegin && download.progress?.state === 'completed') return download
      }
      await delay(100)
    }
    throw new Error('BROWSER_REPORT_NATIVE_DOWNLOAD_TIMEOUT')
  }

  async function waitForFile(timeoutMilliseconds = 10000) {
    const deadline = Date.now() + timeoutMilliseconds
    while (Date.now() < deadline) {
      const files = fs.readdirSync(downloadDirectory).filter((name) => !name.endsWith('.crdownload'))
      if (files.length === 1) return path.join(downloadDirectory, files[0])
      invariant(files.length <= 1, 'BROWSER_REPORT_DOWNLOAD_FILE_COUNT_INVALID')
      await delay(100)
    }
    throw new Error('BROWSER_REPORT_DOWNLOAD_FILE_MISSING')
  }

  return { waitForCompleted, waitForFile }
}

async function reportFlow(page, markers, downloadTracker, complete = true) {
  const reportId = markers.get('BROWSER_GATE_REPORT_ID')
  invariant(/^[0-9a-f-]{36}$/.test(reportId ?? ''), 'BROWSER_REPORT_ID_MISSING')
  const route = `/audit-reports/${reportId}`

  page.setPhase('report.finance-export')
  await page.login('financial.read.integration', PASSWORDS.finance, route)
  await page.waitFor(
    'BROWSER_REPORT_PAGE_MISSING',
    `document.querySelector('h1')?.textContent.includes('审核报告') && document.querySelector('iframe[title="正式审核报告 PDF 预览"]') && [...document.querySelectorAll('button')].some((item) => item.textContent?.includes('下载风险明细 XLSX'))`,
  )
  await delay(300)
  page.consoleProblems.clear()
  console.log('BROWSER_CONSOLE_BASELINE_AFTER_LOGIN=PASS')

  const before = await page.fetchJson('/__finaudit_test__/report-manifest')
  invariant(
    before.status === 200 && before.body?.report?.id === reportId && before.body?.report?.status === 'ready',
    'BROWSER_REPORT_MANIFEST_INVALID',
  )
  const clicked = await page.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find(
      (item) => item.textContent?.includes('下载风险明细 XLSX'),
    );
    if (!(button instanceof HTMLButtonElement) || button.disabled) return false;
    button.click();
    return true;
  })()`)
  invariant(clicked === true, 'BROWSER_REPORT_DOWNLOAD_BUTTON_INVALID')

  const download = await downloadTracker.waitForCompleted()
  const downloadedPath = await downloadTracker.waitForFile()
  const content = fs.readFileSync(downloadedPath)
  const after = await page.fetchJson('/__finaudit_test__/report-manifest')
  const report = after.body?.report
  invariant(after.status === 200 && report?.id === reportId, 'BROWSER_REPORT_MANIFEST_AFTER_DOWNLOAD_INVALID')
  invariant(download.willBegin.url.startsWith('blob:'), 'BROWSER_REPORT_DOWNLOAD_URL_NOT_BLOB')
  invariant(
    download.willBegin.suggestedFilename === `audit-report-${reportId}-v${report.report_version}-risks.xlsx`,
    'BROWSER_REPORT_DOWNLOAD_FILENAME_INVALID',
  )
  invariant(content.byteLength === report.xlsx_size_bytes, 'BROWSER_REPORT_DOWNLOAD_SIZE_INVALID')
  const sha256 = createHash('sha256').update(content).digest('hex')
  invariant(sha256 === report.xlsx_sha256, 'BROWSER_REPORT_DOWNLOAD_SHA256_INVALID')
  console.log('BROWSER_REPORT_NATIVE_DOWNLOAD=PASS')
  console.log(`BROWSER_REPORT_DOWNLOADED_FILENAME=${download.willBegin.suggestedFilename}`)
  console.log(`BROWSER_REPORT_DOWNLOADED_BYTES=${content.byteLength}`)
  console.log(`BROWSER_REPORT_DOWNLOADED_SHA256=${sha256}`)

  if (complete) {
    const completed = await page.fetchJson('/__finaudit_test__/report-complete', {
      method: 'POST',
      headers: { 'X-FinAudit-Browser-Gate': COMPLETE_TOKENS.Report },
    })
    invariant(completed.status === 200, 'BROWSER_REPORT_COMPLETION_REJECTED')
  }
  return report
}

async function accessibilityLoginKeyboardCheck(page) {
  page.setPhase('accessibility.edge-login-keyboard')
  await page.navigate('/login')
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_LOGIN_FORM_MISSING',
    `document.querySelector('#username') && document.querySelector('#password') && document.querySelector('#remember-me')`,
  )
  await page.evaluate(`(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  })()`)
  const observed = []
  for (let index = 0; index < 4; index += 1) {
    await page.pressKey('Tab')
    observed.push(await page.evaluate(`(() => {
      const element = document.activeElement;
      if (!(element instanceof HTMLElement)) return null;
      return {
        id: element.id,
        tag: element.tagName,
        type: element instanceof HTMLInputElement || element instanceof HTMLButtonElement ? element.type : '',
      };
    })()`))
  }
  invariant(
    JSON.stringify(observed) === JSON.stringify([
      { id: 'username', tag: 'INPUT', type: 'text' },
      { id: 'password', tag: 'INPUT', type: 'password' },
      { id: 'remember-me', tag: 'INPUT', type: 'checkbox' },
      { id: '', tag: 'BUTTON', type: 'submit' },
    ]),
    'BROWSER_ACCESSIBILITY_EDGE_LOGIN_TAB_ORDER_INVALID',
  )
  console.log('BROWSER_ACCESSIBILITY_EDGE_LOGIN_KEYBOARD=PASS')
}

async function inspectAccessibleRoute(page, route) {
  await page.navigate(route)
  await page.waitFor(
    `BROWSER_ACCESSIBILITY_ROUTE_RENDER_TIMEOUT_${route}`,
    `document.querySelector('main#main-content') && document.querySelectorAll('h1').length === 1`,
  )
  await delay(250)
  const summary = await page.evaluate(`(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const name = (element) => {
      const labelledBy = element.getAttribute('aria-labelledby');
      const labelledText = labelledBy
        ? labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.textContent?.trim() ?? '').join(' ').trim()
        : '';
      const labelText = 'labels' in element && element.labels
        ? [...element.labels].map((label) => label.textContent?.trim() ?? '').join(' ').trim()
        : '';
      return (
        element.getAttribute('aria-label')?.trim() ||
        labelledText ||
        labelText ||
        element.getAttribute('title')?.trim() ||
        element.getAttribute('alt')?.trim() ||
        element.textContent?.trim() ||
        ''
      );
    };
    const focusables = [...document.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),iframe,[tabindex]:not([tabindex="-1"])',
    )].filter((element) => element instanceof HTMLElement && visible(element));
    const ids = [...document.querySelectorAll('[id]')].map((element) => element.id);
    return {
      actualPath: location.pathname,
      focusableCount: focusables.length,
      heading: document.querySelector('h1')?.textContent?.trim() ?? '',
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      mainCount: document.querySelectorAll('main#main-content').length,
      duplicateIds: [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))],
      unnamedFocusables: focusables.filter((element) => name(element).length === 0).map((element) => element.outerHTML.slice(0, 160)),
    };
  })()`)
  invariant(
    summary.mainCount === 1 &&
      summary.heading.length > 0 &&
      summary.duplicateIds.length === 0 &&
      summary.unnamedFocusables.length === 0 &&
      summary.horizontalOverflow === false,
    `BROWSER_ACCESSIBILITY_ROUTE_STRUCTURE_INVALID_${route}`,
  )

  const axNodes = await page.accessibilityTree()
  invariant(
    axNodes.some((node) => node.role?.value === 'main') &&
      axNodes.some(
        (node) => node.role?.value === 'heading' && node.name?.value?.includes(summary.heading),
      ),
    `BROWSER_ACCESSIBILITY_AX_TREE_INVALID_${route}`,
  )

  await page.evaluate(`(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  })()`)
  await page.pressKey('Tab')
  const skipLink = await page.evaluate(`(() => {
    const element = document.activeElement;
    return element instanceof HTMLAnchorElement
      ? { className: element.className, text: element.textContent?.trim() ?? '' }
      : null;
  })()`)
  invariant(
    skipLink?.className.split(/\s+/).includes('skip-link') && skipLink.text === '跳到主内容',
    `BROWSER_ACCESSIBILITY_SKIP_LINK_FIRST_INVALID_${route}`,
  )
  await page.pressKey('Enter')
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_SKIP_LINK_TARGET_INVALID',
    `document.activeElement?.id === 'main-content' && location.hash === '#main-content'`,
  )

  const sampledTabStops = []
  let consecutiveSameElementTabs = 0
  let previousSignature = null
  for (let index = 0; index < 6; index += 1) {
    await page.pressKey('Tab')
    const focused = await page.evaluate(`(() => {
      const element = document.activeElement;
      if (!(element instanceof HTMLElement)) return null;
      const labelledBy = element.getAttribute('aria-labelledby');
      const labelledText = labelledBy
        ? labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.textContent?.trim() ?? '').join(' ').trim()
        : '';
      const labelText = 'labels' in element && element.labels
        ? [...element.labels].map((label) => label.textContent?.trim() ?? '').join(' ').trim()
        : '';
      return {
        domIndex: [...document.querySelectorAll('*')].indexOf(element),
        id: element.id,
        name: element.getAttribute('aria-label')?.trim() || labelledText || labelText || element.getAttribute('title')?.trim() || element.textContent?.trim() || '',
        tag: element.tagName,
      };
    })()`)
    if (focused === null || focused.tag === 'BODY') break
    invariant(focused.name.length > 0, `BROWSER_ACCESSIBILITY_FOCUS_NAME_MISSING_${route}`)
    const signature = `${focused.domIndex}:${focused.tag}:${focused.id}:${focused.name}`
    consecutiveSameElementTabs = signature === previousSignature ? consecutiveSameElementTabs + 1 : 0
    invariant(consecutiveSameElementTabs < 5, `BROWSER_ACCESSIBILITY_FOCUS_TRAP_${route}_${signature}`)
    sampledTabStops.push(`${signature}:internal-tab-${consecutiveSameElementTabs}`)
    previousSignature = signature
  }
  invariant(sampledTabStops.length > 0, `BROWSER_ACCESSIBILITY_ROUTE_NO_TAB_STOPS_${route}`)
  return {
    actual_path: summary.actualPath,
    heading: summary.heading,
    requested_route: route,
    sampled_tab_stops: sampledTabStops,
  }
}

async function accessibilityRouteMatrix(page, markers, report) {
  const fileId = markers.get('BROWSER_GATE_FILE_ID')
  const contractId = markers.get('BROWSER_GATE_CONTRACT_ID')
  const invoiceId = markers.get('BROWSER_GATE_INVOICE_ID')
  const supplierId = markers.get('BROWSER_GATE_SUPPLIER_ID')
  const knowledgeBaseId = markers.get('BROWSER_GATE_KNOWLEDGE_BASE_ID')
  invariant(
    [fileId, contractId, invoiceId, supplierId, knowledgeBaseId, report.audit_task_id, report.id].every(
      (value) => /^[0-9a-f-]{36}$/.test(value ?? ''),
    ),
    'BROWSER_ACCESSIBILITY_ROUTE_IDENTITIES_INVALID',
  )
  const financeRoutes = [
    '/dashboard',
    '/files',
    `/files/${fileId}`,
    '/contracts',
    `/contracts/${contractId}`,
    `/contracts/${contractId}/primary-invoices`,
    '/invoices',
    `/invoices/${invoiceId}`,
    `/invoices/${invoiceId}/contract-links`,
    '/suppliers',
    `/suppliers/${supplierId}`,
    '/contract-invoice-links',
    '/knowledge-bases',
    `/knowledge-bases/${knowledgeBaseId}`,
    '/qa',
    '/audit-tasks',
    `/audit-tasks/${report.audit_task_id}`,
    `/audit-reports/${report.id}`,
  ]
  const results = []
  for (const route of financeRoutes) {
    page.setPhase(`accessibility.edge-route.${route}`)
    results.push(await inspectAccessibleRoute(page, route))
  }

  await page.switchUser('admin.read.integration', PASSWORDS.admin, '/dashboard')
  for (const route of ['/users', '/operation-logs']) {
    page.setPhase(`accessibility.edge-route.${route}`)
    results.push(await inspectAccessibleRoute(page, route))
  }
  invariant(results.length === 20, 'BROWSER_ACCESSIBILITY_ROUTE_MATRIX_COUNT_INVALID')
  console.log(`BROWSER_ACCESSIBILITY_ROUTE_COUNT=${results.length}`)
  console.log('BROWSER_ACCESSIBILITY_ROUTE_MATRIX=PASS')
  return results
}

async function accessibilityNarratorFocusFlow(page, reportId, profilePath) {
  const route = `/audit-reports/${reportId}`
  const markerPath = process.env.FINAUDIT_NARRATOR_MARKER_PATH
  invariant(
    typeof markerPath === 'string' &&
      path.isAbsolute(markerPath) &&
      path.resolve(markerPath).startsWith(path.resolve(os.tmpdir()) + path.sep) &&
      path.basename(markerPath) === 'narrator-focus.json' &&
      !fs.existsSync(markerPath),
    'BROWSER_ACCESSIBILITY_NARRATOR_MARKER_PATH_INVALID',
  )
  const focusSequence = []
  page.setPhase('accessibility.edge-narrator')
  await page.bringToFront()
  await focusAccessibilityEdge(profilePath)
  const focusStartedUtc = new Date().toISOString()
  await page.navigate(`/login?redirect=${encodeURIComponent(route)}`)
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_NARRATOR_LOGIN_FORM_MISSING',
    `document.querySelector('#username') && document.querySelector('#password')`,
  )
  await page.evaluate(`(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  })()`)
  await page.pressKey('Tab')
  invariant(
    (await page.evaluate(`document.activeElement?.id`)) === 'username',
    'BROWSER_ACCESSIBILITY_NARRATOR_USERNAME_FOCUS_INVALID',
  )
  focusSequence.push('username')
  await page.setValue('#username', 'financial.read.integration')
  await delay(300)
  await page.pressKey('Tab')
  invariant(
    (await page.evaluate(`document.activeElement?.id`)) === 'password',
    'BROWSER_ACCESSIBILITY_NARRATOR_PASSWORD_FOCUS_INVALID',
  )
  focusSequence.push('password')
  await page.setValue('#password', PASSWORDS.finance)
  await delay(300)
  await page.pressKey('Tab')
  invariant(
    (await page.evaluate(`document.activeElement?.id`)) === 'remember-me',
    'BROWSER_ACCESSIBILITY_NARRATOR_REMEMBER_FOCUS_INVALID',
  )
  focusSequence.push('remember_me')
  await delay(300)
  await page.pressKey('Tab')
  invariant(
    (await page.evaluate(`document.activeElement?.matches('button[type="submit"]')`)) === true,
    'BROWSER_ACCESSIBILITY_NARRATOR_SUBMIT_FOCUS_INVALID',
  )
  invariant(
    (await page.evaluate(`document.querySelector('button[type="submit"]')?.disabled`)) === false,
    'BROWSER_ACCESSIBILITY_NARRATOR_SUBMIT_DISABLED',
  )
  focusSequence.push('login_button')
  await delay(300)
  await page.click('form button[type="submit"]')
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_NARRATOR_LOGIN_TIMEOUT',
    `location.pathname === ${JSON.stringify(route)}`,
  )
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_NARRATOR_REPORT_MISSING',
    `document.querySelector('h1')?.textContent.includes('审核报告') && document.querySelector('iframe[title="正式审核报告 PDF 预览"]')`,
  )
  focusSequence.push('report_page')
  await delay(800)
  await page.evaluate(`(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  })()`)
  await page.pressKey('Tab')
  invariant(
    (await page.evaluate(`document.activeElement?.classList.contains('skip-link')`)) === true,
    'BROWSER_ACCESSIBILITY_NARRATOR_SKIP_LINK_FOCUS_INVALID',
  )
  focusSequence.push('skip_link')
  await delay(500)
  await page.pressKey('Enter')
  await page.waitFor(
    'BROWSER_ACCESSIBILITY_NARRATOR_MAIN_FOCUS_INVALID',
    `document.activeElement?.id === 'main-content'`,
  )
  focusSequence.push('main_content')
  await delay(500)
  let downloadFocused = false
  for (let index = 0; index < 8; index += 1) {
    await page.pressKey('Tab')
    const focusedText = await page.evaluate(`document.activeElement?.textContent?.trim() ?? ''`)
    await delay(300)
    if (focusedText.includes('下载风险明细 XLSX')) {
      downloadFocused = true
      focusSequence.push('download_xlsx_button')
      break
    }
  }
  invariant(downloadFocused, 'BROWSER_ACCESSIBILITY_NARRATOR_DOWNLOAD_FOCUS_INVALID')
  await delay(1200)
  const marker = {
    schema_version: 'finaudit-narrator-focus-v1',
    focus_started_utc: focusStartedUtc,
    focus_completed_utc: new Date().toISOString(),
    focus_sequence: focusSequence,
    report_route: route,
  }
  const temporaryMarkerPath = `${markerPath}.tmp-${process.pid}`
  fs.writeFileSync(temporaryMarkerPath, `${JSON.stringify(marker)}\n`, { encoding: 'utf8', flag: 'wx' })
  fs.renameSync(temporaryMarkerPath, markerPath)
  console.log('BROWSER_ACCESSIBILITY_NARRATOR_FOCUS_SEQUENCE=PASS')
}

async function accessibilityFlow(page, markers, downloadTracker, profilePath) {
  await accessibilityLoginKeyboardCheck(page)
  const report = await reportFlow(page, markers, downloadTracker, false)
  const routes = await accessibilityRouteMatrix(page, markers, report)
  await page.logout()
  await accessibilityNarratorFocusFlow(
    page,
    markers.get('BROWSER_GATE_REPORT_ID'),
    profilePath,
  )
  invariant(
    page.expectedNetworkProblems.size === 5,
    `BROWSER_ACCESSIBILITY_EXPECTED_HTTP_BOUNDARY_INVALID_${[...page.expectedNetworkProblems].join(' | ')}`,
  )
  console.log('BROWSER_ACCESSIBILITY_EXPECTED_HTTP_ERRORS=5')
  invariant(page.consoleProblems.size === 0, `BROWSER_ACCESSIBILITY_CONSOLE_PROBLEMS_${[...page.consoleProblems].join(' | ')}`)
  const completed = await page.fetchJson('/__finaudit_test__/report-complete', {
    method: 'POST',
    headers: { 'X-FinAudit-Browser-Gate': COMPLETE_TOKENS.Accessibility },
  })
  invariant(completed.status === 200, 'BROWSER_ACCESSIBILITY_COMPLETION_REJECTED')
  return { routes }
}

async function documentCorrectionFlow(page, markers) {
  const fileId = markers.get('BROWSER_GATE_DOCUMENT_CORRECTION_FILE_ID')
  invariant(/^[0-9a-f-]{36}$/.test(fileId ?? ''), 'BROWSER_DOCUMENT_FILE_ID_MISSING')
  const route = `/files/${fileId}`

  page.setPhase('document.read-only')
  await page.login('browser.readonly.matrix', PASSWORDS.matrix, route, '/forbidden')
  await page.waitFor('BROWSER_DOCUMENT_READ_ONLY_NOT_DENIED', `location.pathname === '/forbidden'`)
  await delay(300)
  page.consoleProblems.clear()
  console.log('BROWSER_CONSOLE_BASELINE_AFTER_LOGIN=PASS')
  console.log('BROWSER_DOCUMENT_READ_ONLY_DENIED=PASS')

  page.setPhase('document.system-admin')
  await page.switchUser('admin.read.integration', PASSWORDS.admin, route)
  await page.waitFor('BROWSER_DOCUMENT_ADMIN_PROJECTION_MISSING', `document.querySelector('#document-correction-source')`)
  invariant(
    await page.evaluate(`!document.querySelector('.report-preview-frame') && !document.querySelector('img[alt$="原图预览"]')`),
    'BROWSER_DOCUMENT_ADMIN_SCOPE_INVALID',
  )
  console.log('BROWSER_DOCUMENT_SYSTEM_ADMIN_PROJECTION=PASS')

  page.setPhase('document.contract-admin')
  await page.switchUser('browser.contract.matrix', PASSWORDS.matrix, route)
  await page.waitFor('BROWSER_DOCUMENT_CORRECTION_PANEL_MISSING', `document.querySelector('#document-correction-source')`)
  await page.selectFirst('#document-correction-source')
  await page.setValue('#document-correction-reason', '   ')
  invariant(
    await page.evaluate(`document.querySelector('[data-testid="submit-document-correction"]')?.disabled === true`),
    'BROWSER_DOCUMENT_INVALID_REASON_NOT_BLOCKED',
  )
  console.log('BROWSER_DOCUMENT_INVALID_FORM_BLOCKED=PASS')

  await page.setValue('#document-correction-text', '浏览器纠错后的补充协议证据文本')
  await page.setValue('#document-correction-reason', '浏览器人工复核纠错')
  await page.click('[data-testid="submit-document-correction"]')
  await page.waitFor('BROWSER_DOCUMENT_CANDIDATE_TIMEOUT', `document.body.innerText.includes('候选快照已排队')`)

  const deadline = Date.now() + 45000
  let workerStatus = 'missing'
  while (Date.now() < deadline) {
    const candidateManifest = await page.fetchJson('/__finaudit_test__/document-correction-manifest')
    workerStatus = candidateManifest.body?.job?.status ?? 'missing'
    if (workerStatus === 'succeeded') break
    if (workerStatus === 'failed') throw new Error('BROWSER_DOCUMENT_WORKER_FAILED')
    await delay(300)
  }
  invariant(workerStatus === 'succeeded', `BROWSER_DOCUMENT_WORKER_TIMEOUT_${workerStatus}`)
  await page.click('[data-testid="activate-document-correction"]')
  const activationDeadline = Date.now() + 10000
  let activationStatus = 'missing'
  while (Date.now() < activationDeadline) {
    const activationManifest = await page.fetchJson('/__finaudit_test__/document-correction-manifest')
    activationStatus = activationManifest.body?.result?.status ?? 'missing'
    if (activationStatus === 'active') break
    await delay(200)
  }
  invariant(activationStatus === 'active', `BROWSER_DOCUMENT_ACTIVATION_TIMEOUT_${activationStatus}`)
  await page.reload()
  await page.waitFor('BROWSER_DOCUMENT_REFRESH_SOURCE_MISSING', `document.querySelector('#document-correction-source')`)
  await page.waitFor(
    'BROWSER_DOCUMENT_REFRESH_RECOVERY_FAILED',
    `[...document.querySelectorAll('#document-correction-source option')].some((item) => item.textContent.includes('浏览器纠错后的补充协议证据文本'))`,
  )
  console.log('BROWSER_DOCUMENT_REFRESH_RECOVERY=PASS')

  const manifest = await page.fetchJson('/__finaudit_test__/document-correction-manifest')
  invariant(manifest.status === 200 && manifest.body?.result?.status === 'active', 'BROWSER_DOCUMENT_DATABASE_TERMINAL_INVALID')
  console.log('BROWSER_DOCUMENT_DATABASE_TERMINAL=PASS')
  const completed = await page.fetchJson('/__finaudit_test__/document-correction-complete', {
    method: 'POST',
    headers: { 'X-FinAudit-Browser-Gate': COMPLETE_TOKENS.DocumentCorrection },
  })
  invariant(completed.status === 200, 'BROWSER_DOCUMENT_COMPLETION_REJECTED')
}

async function policyRevocationFlow(page, markers) {
  const knowledgeBaseId = markers.get('BROWSER_GATE_POLICY_REVOCATION_KB_ID')
  const policyId = markers.get('BROWSER_GATE_POLICY_REVOCATION_POLICY_ID')
  invariant(/^[0-9a-f-]{36}$/.test(knowledgeBaseId ?? '') && /^[0-9a-f-]{36}$/.test(policyId ?? ''), 'BROWSER_POLICY_SUBJECT_ID_MISSING')
  const route = `/knowledge-bases/${knowledgeBaseId}`
  const requestSelector = `[data-testid="request-policy-revocation-${policyId}"]`
  const revokeSelector = `[data-testid="revoke-policy-${policyId}"]`

  page.setPhase('policy.reader-before')
  await page.login('browser.contract.matrix', PASSWORDS.matrix, route)
  await page.waitFor('BROWSER_POLICY_READER_PAGE_MISSING', `document.querySelector('[role="tab"]')`)
  await delay(300)
  page.consoleProblems.clear()
  console.log('BROWSER_CONSOLE_BASELINE_AFTER_LOGIN=PASS')
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_READER_LIST_MISSING', `document.body.innerText.includes('REVOCABLE-BROWSER-001')`)
  invariant(
    await page.evaluate(`!document.querySelector(${JSON.stringify(requestSelector)}) && !document.body.innerText.includes('撤销待执行请求')`),
    'BROWSER_POLICY_READER_SCOPE_INVALID',
  )
  console.log('BROWSER_POLICY_UNAUTHORIZED_READER=PASS')

  page.setPhase('policy.audit-request')
  await page.switchUser('browser.audit.matrix', PASSWORDS.matrix, route)
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_AUDIT_ACTION_MISSING', `document.querySelector(${JSON.stringify(requestSelector)})`)
  await page.setValue('[aria-label="REVOCABLE-BROWSER-001 操作原因"]', '   ')
  invariant(await page.evaluate(`document.querySelector(${JSON.stringify(requestSelector)})?.disabled === true`), 'BROWSER_POLICY_INVALID_REQUEST_NOT_BLOCKED')
  await page.setValue('[aria-label="REVOCABLE-BROWSER-001 操作原因"]', '浏览器审计复核提交撤销确认')
  await page.click(requestSelector)
  await page.waitFor('BROWSER_POLICY_REQUEST_TIMEOUT', `document.body.innerText.includes('等待系统管理员独立执行')`)
  await page.reload()
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_REQUEST_REFRESH_FAILED', `document.body.innerText.includes('等待系统管理员执行')`)
  console.log('BROWSER_POLICY_REQUEST_REFRESH_RECOVERY=PASS')

  page.setPhase('policy.system-admin')
  await page.switchUser('admin.read.integration', PASSWORDS.admin, route)
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_ADMIN_PENDING_MISSING', `document.querySelector(${JSON.stringify(revokeSelector)})`)
  await page.setValue('[aria-label="REVOCABLE-BROWSER-001 撤销执行原因"]', '   ')
  invariant(await page.evaluate(`document.querySelector(${JSON.stringify(revokeSelector)})?.disabled === true`), 'BROWSER_POLICY_INVALID_EXECUTION_NOT_BLOCKED')
  await page.setValue('[aria-label="REVOCABLE-BROWSER-001 撤销执行原因"]', '浏览器系统管理员执行独立撤销')
  await page.click(revokeSelector)
  await page.waitFor('BROWSER_POLICY_EXECUTION_TIMEOUT', `document.body.innerText.includes('已撤销，新检索将立即排除该制度')`)
  await page.reload()
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_EXECUTION_REFRESH_FAILED', `document.body.innerText.includes('浏览器系统管理员执行独立撤销') && document.body.innerText.includes('当前没有待执行的制度撤销请求')`)
  console.log('BROWSER_POLICY_EXECUTION_REFRESH_RECOVERY=PASS')

  page.setPhase('policy.reader-after')
  await page.switchUser('browser.contract.matrix', PASSWORDS.matrix, route)
  await page.clickTab('制度文档')
  await page.waitFor('BROWSER_POLICY_READER_REFRESH_TIMEOUT', `document.querySelector('#policies-panel')`)
  invariant(!(await page.evaluate(`document.body.innerText.includes('REVOCABLE-BROWSER-001')`)), 'BROWSER_POLICY_REVOKED_VISIBLE_TO_READER')
  console.log('BROWSER_POLICY_REVOKED_READER_EXCLUSION=PASS')

  const manifest = await page.fetchJson('/__finaudit_test__/policy-revocation-manifest')
  invariant(manifest.status === 200 && manifest.body?.policy?.status === 'revoked' && manifest.body?.pending_count === 0, 'BROWSER_POLICY_DATABASE_TERMINAL_INVALID')
  console.log('BROWSER_POLICY_DATABASE_TERMINAL=PASS')
  const completed = await page.fetchJson('/__finaudit_test__/policy-revocation-complete', {
    method: 'POST',
    headers: { 'X-FinAudit-Browser-Gate': COMPLETE_TOKENS.PolicyRevocation },
  })
  invariant(completed.status === 200, 'BROWSER_POLICY_COMPLETION_REJECTED')
}

async function invoiceDuplicateFlow(page, markers) {
  const sourceId = markers.get('BROWSER_GATE_INVOICE_ID')
  const candidateId = markers.get('BROWSER_GATE_DUPLICATE_INVOICE_ID')
  invariant(
    /^[0-9a-f-]{36}$/.test(sourceId ?? '') && /^[0-9a-f-]{36}$/.test(candidateId ?? ''),
    'BROWSER_INVOICE_DUPLICATE_SUBJECT_ID_MISSING',
  )
  const route = `/invoices/${sourceId}`
  const compareSelector = `[data-testid="compare-invoice-duplicate-${candidateId}"]`

  page.setPhase('invoice-duplicate.finance-reader')
  await page.login('financial.read.integration', PASSWORDS.finance, route)
  await page.waitFor(
    'BROWSER_INVOICE_DUPLICATE_CANDIDATE_MISSING',
    `document.querySelector(${JSON.stringify(compareSelector)}) && document.body.innerText.includes(${JSON.stringify(candidateId)})`,
  )
  await delay(300)
  page.consoleProblems.clear()
  console.log('BROWSER_CONSOLE_BASELINE_AFTER_LOGIN=PASS')
  const mutationButtonsDisabled = await page.evaluate(`[
    'confirm-invoice',
    'reject-invoice',
    'check-invoice-duplicate',
    'confirm-invoice-duplicate',
    'approve-invoice-duplicate-exception',
    'replace-invoice-facts',
  ].every((testId) => {
    const button = document.querySelector('[data-testid="' + testId + '"]');
    return button === null || button.disabled === true;
  })`)
  invariant(mutationButtonsDisabled === true, 'BROWSER_INVOICE_DUPLICATE_WRITE_ENABLED')
  await page.click(compareSelector)
  await page.waitFor(
    'BROWSER_INVOICE_DUPLICATE_PAIR_MISSING',
    `document.body.innerText.includes('精确重复对比') && document.body.innerText.includes(${JSON.stringify(sourceId)}) && document.body.innerText.includes(${JSON.stringify(candidateId)})`,
  )
  console.log('BROWSER_INVOICE_DUPLICATE_READ_ONLY_PAIR=PASS')

  const manifest = await page.fetchJson('/__finaudit_test__/invoice-duplicate-manifest')
  invariant(
    manifest.status === 200 &&
      manifest.body?.source?.id === sourceId &&
      manifest.body?.candidate?.id === candidateId,
    'BROWSER_INVOICE_DUPLICATE_DATABASE_TERMINAL_INVALID',
  )
  console.log('BROWSER_INVOICE_DUPLICATE_DATABASE_TERMINAL=PASS')
  const completed = await page.fetchJson('/__finaudit_test__/invoice-duplicate-complete', {
    method: 'POST',
    headers: { 'X-FinAudit-Browser-Gate': COMPLETE_TOKENS.InvoiceDuplicate },
  })
  invariant(completed.status === 200, 'BROWSER_INVOICE_DUPLICATE_COMPLETION_REJECTED')
}

async function waitForExit(application, timeoutMilliseconds) {
  return Promise.race([
    application.exitPromise,
    delay(timeoutMilliseconds).then(() => {
      throw new Error('BROWSER_GATE_APPLICATION_EXIT_TIMEOUT')
    }),
  ])
}

async function stopBrowser(browser) {
  if (browser.child.exitCode === null) {
    if (process.platform === 'win32') {
      await new Promise((resolve) => {
        const killer = spawn('taskkill.exe', ['/PID', String(browser.child.pid), '/T', '/F'], {
          stdio: 'ignore',
          windowsHide: true,
        })
        killer.once('error', resolve)
        killer.once('exit', resolve)
      })
    } else {
      browser.child.kill()
    }
    await Promise.race([new Promise((resolve) => browser.child.once('exit', resolve)), delay(5000)])
  }
  const resolvedProfile = path.resolve(browser.profile)
  invariant(
    resolvedProfile.startsWith(path.resolve(os.tmpdir()) + path.sep) &&
      path.basename(resolvedProfile).startsWith('finaudit-browser-gate-'),
    'BROWSER_RUNNER_PROFILE_CLEANUP_SCOPE_INVALID',
  )
  fs.rmSync(resolvedProfile, { force: true, recursive: true })
}

async function main() {
  const { mode, port, python } = parseArguments()
  const application = startApplication(python, mode)
  let browser
  let client
  let completed = false
  try {
    await Promise.race([
      application.readyPromise,
      delay(60000).then(() => {
        throw new Error('BROWSER_GATE_APPLICATION_READY_TIMEOUT')
      }),
    ])
    browser = await startBrowser(mode)
    client = new CdpClient(browser.url)
    await client.open()
    let downloadTracker
    if (mode === 'Report' || mode === 'Accessibility') {
      const downloadDirectory = path.join(browser.profile, 'downloads')
      downloadTracker = createDownloadTracker(client, downloadDirectory)
      await client.send('Browser.setDownloadBehavior', {
        behavior: 'allow',
        downloadPath: downloadDirectory,
        eventsEnabled: true,
      })
    }
    const sessionId = await attachPage(client)
    const page = createPage(client, sessionId, `http://127.0.0.1:${port}`)
    if (mode === 'Accessibility') {
      await accessibilityFlow(page, application.markers, downloadTracker, browser.profile)
    } else if (mode === 'Report') await reportFlow(page, application.markers, downloadTracker)
    else if (mode === 'DocumentCorrection') await documentCorrectionFlow(page, application.markers)
    else if (mode === 'InvoiceDuplicate') await invoiceDuplicateFlow(page, application.markers)
    else await policyRevocationFlow(page, application.markers)
    invariant(page.consoleProblems.size === 0, `BROWSER_CONSOLE_PROBLEMS_${[...page.consoleProblems].join(' | ')}`)
    console.log('BROWSER_CONSOLE_WARNINGS=0')
    console.log('BROWSER_CONSOLE_ERRORS=0')
    const exit = await waitForExit(application, 60000)
    invariant(exit.code === 0 && exit.signal === null, 'BROWSER_GATE_APPLICATION_FAILED')
    completed = true
  } finally {
    client?.close()
    if (browser) {
      await stopBrowser(browser)
    }
    if (!completed && application.child.exitCode === null) {
      try {
        await fetch(`http://127.0.0.1:${port}/__finaudit_test__/shutdown`, {
          method: 'POST',
          headers: { 'X-FinAudit-Browser-Gate': 'STOP_DISPOSABLE_BROWSER_GATE_V1' },
        })
        await waitForExit(application, 15000)
      } catch {
        application.child.kill()
      }
    }
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error)
  console.error(`BROWSER_GATE_RUNNER_FAILED=${message}`)
  process.exitCode = 1
})
