# CR-011-R6：BASE-004 启动证据边界治理 successor

> 状态：`GENERATED FOR REVIEW / NOT APPROVED`
>
> 日期：2026-08-10
>
> 基座：`CR-011-R5` approved exact contract；仅 successor `STARTUP-D-005` 的证据模型
>
> 目标：在不改变任何启动行为、Policy 合同、运行时依赖或非授权边界的前提下，把 R5 无法由当前非提升 Windows runner 完整证明的 OS-level native WinSock/NamedPipe 零尝试声明，收窄为 externally reviewed top-level pin owner、无 pin launcher/core、精确锁定 subject、Python-visible 零尝试和 closed allowlist 证据；未观测层必须明确记为 `NOT_CLAIMED`，不得写成 `0`

---

## 1. 不可变基座与 R6 必要性

### 1.1 R5 effective identity

本 CR 逐字绑定以下不可变基座：

| 对象 | raw / decision identity | 状态 |
|---|---|---|
| R3 exact contract | decision `26563/b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be` | `AI-D-009`～`AI-D-014` 保持原样 |
| R3-origin artifact manifest | raw `5128/f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c` | 15 个 leaf identity 保持原样 |
| R4 active governance | decision `27384/cb3a007edf138fe090008498241c7c04269c585306069da46eb21aef30777c10` | 既有 Gate B 与 persistent Gate C 边界保持原样 |
| R5 active contract | raw `53927/089cbb5c88659dc7076df191af6d4c84492aa30e081878c1bfc232596a8407a7` | `APPROVED / ACTIVE CONTRACT / GATE B PASS / GATE C BLOCKED` |
| R5 decision snapshot | `50926/fb6aa225dae67a6068e84935e4a77affe84b143de5de2908b555089f9334c5ae` | `STARTUP-D-001`～`STARTUP-D-006` 的当前基座 |
| Python exact runtime closure lock | raw `641/0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c` | 六项 exact hashed closure 保持原样 |

R6 不重写 R5，也不追认 R5 下游实现为已通过。R5 §2.5 原要求“整个被测启动进程”对 TCP、UDP、DNS、Unix domain/Windows named pipe 和其他本地 socket 的 attempt 精确为 `0`；该句同时包含行为禁令和 OS-level 完整观测声明。当前 Gate C 可以执行并验证前者的受信代码路径，却没有权限为后者产生覆盖 native WinSock、direct Windows named-pipe API 和任意短命 descendant 的完整 OS telemetry。

### 1.2 当前 Windows telemetry NO-GO 的机械事实

2026-08-10 的本地、无外网、临时 ETW 可行性探针得到以下结果；这些结果只说明为什么必须提升 evidence-boundary successor，不属于 R6 Gate C PASS 证据：

| 探针 | 结果 |
|---|---|
| 当前 token | 非管理员；`BUILTIN\Performance Log Users` enabled |
| ordinary manifest session | 可创建、查询、停止并清理 |
| `Microsoft-Windows-Winsock-AFD` | enable PASS |
| `Microsoft-Windows-Winsock-Sockets` | enable PASS |
| `Microsoft-Windows-Winsock-NameResolution` | enable PASS |
| `Microsoft-Windows-DNS-Client` | enable PASS |
| `Microsoft-Windows-Kernel-File` | `0x80070005 / Access is denied` |
| `Microsoft-Windows-Kernel-Process` | `0x80070005 / Access is denied` |
| native positive calibration | 同一受控子进程内 `ctypes` TCP socket/bind/listen、UDP socket 和 `GetAddrInfoW("localhost")` 均被目标 PID 的 Winsock/DNS events 捕获；`Buffers Lost=0`、`Total Events Lost=0` |
| Windows named-pipe calibration | `CreateNamedPipeW`、`WaitNamedPipeW`、`ConnectNamedPipe` 和 client open 均成功，但上述四个非提升 provider 中没有 pipe marker/event |
| provider inventory | 本机没有可替代 `Kernel-File` 的专用 local NamedPipe provider；`SMBClient` 不能证明本地 named-pipe API 完整性 |
| cleanup | 所有临时文件已删除、所有探针 session 已停止并复核为零；另确认 `logman create` 返回失败时仍可能半创建 session，因此未来 ETW helper 必须无条件按唯一名称停止并复核 absence |

由此可以机械得出：四个非提升 Winsock/DNS provider 足以校准已知 PID 的 native network event，但不能完成 local NamedPipe 观测；`Kernel-Process` 不可用也使当前普通 session 不能自动重建任意短命 descendant 集合。仅靠 Python monkeypatch、audit hook、source scan 或四个 Winsock/DNS provider，把 native Windows pipe 或 direct syscall attempt 写成 `0` 都是越证据推断。

### 1.3 application/runtime behavior、Policy implementation 与业务边界零增量

R6 不是“全部实现 delta 为零”。其 evidence-tooling delta 非零，并精确限于 top-level pin owner、无 pin launcher/core/probe、pre-run `expected_subject_allowlist`、child-owned post-run `observed_subject_ledger`、Python-visible guard/counter、evidence-core-only self-PID loaded-module enumeration、source/AST/import/ctypes/PE closed allowlist、anti-forgery 和 fail-closed runner/parser；这些工具只属于本地测试/证据路径，不得进入或改变应用 startup/runtime 产品路径。

R6 的 application/runtime behavior delta 与 Policy implementation delta 精确为零；以下对象全部保持 R5 原样：

- `AI-D-009`～`AI-D-014`、全部 Policy/Event 字段、Draft 2020-12 Schema、companion rule 顺序、registry、JCS/self-hash、approval pin 和 fixed vectors；
- `STARTUP-D-001`、`STARTUP-D-002`、`STARTUP-D-003`、`STARTUP-D-004`、`STARTUP-D-006`；
- `app.ai.artifacts.cr011_v1` 四项 data leaf、external synthetic Policy raw/policy hash identity、loader/path/drive/reparse/bounded-read 行为、Settings cross-binding、FastAPI/Worker bootstrap 顺序；
- CPython 3.10/Windows x86-64 platform gate、六项 exact hashed dependency closure、PyPI acquisition oracle 与 startup/acquisition 进程隔离；
- 57 张核心表、122 个 API path、UI-001～UI-014、86 个 P0 工作包和全部 Provider/DB/Redis/Broker/部署/production 非授权边界。

除上述封闭 evidence tooling 外，R6 不授权其他实现增量，也不授权新增 OS hook、driver、ETW elevation、firewall/audit-policy 变更、native shim、Provider 或业务网络。`NOT_CLAIMED` 只描述观测能力，不表示对应行为允许发生；应用行为、Policy implementation 和全部业务/production 非授权边界仍然有效。

---

## 2. STARTUP-D-005-R6：受信锁定 subject 的分层证据合同

### 2.1 规范禁令与证据声明必须分离

`STARTUP-D-005-R6` 只 successor R5 `STARTUP-D-005` 的证据完整性模型。应用启动的规范行为仍为：不得尝试 TCP、UDP、DNS、TLS、HTTP、Unix domain socket、Windows named pipe、其他本地 socket、Provider、数据库、Redis 或 Broker；不得通过 native API、direct syscall、subprocess、动态 import 或 fallback 绕过。

R6 Gate C 允许证明的范围只到：

1. 由 top-level pin owner 启动、从 process creation 起建立的无 pin launcher/core/application 精确 subject；
2. subject 内全部已锁定 Python source、import、`ctypes`/Win32 resolution、已加载 native image/PE 和 artifact identity；
3. Python-visible socket、DNS 和 local-socket attempt 精确为 `0`；
4. `socket.gethostname`/等价本机名读取恰好 `1` 次，并单列为 local hostname read，不计作 socket creation、DNS resolution 或 peer I/O；
5. closed allowlist、before/after identity、正向 guard selftest 和 anti-forgery 全部 PASS。

以下两项必须逐字输出为 `NOT_CLAIMED`，不得省略、推断或转换成数值：

```text
native_os_winsock_attempts=NOT_CLAIMED
windows_named_pipe_attempts=NOT_CLAIMED
```

任何 runner、报告或 tracking 若把上述任一项写成 `0`、`PASS`、`ZERO`、`NONE` 或等价肯定结论，R6 Gate C 必须失败关闭。

### 2.2 top-level pin owner、no-pin launcher/core 与 exact evidence subject

有效启动证据必须明确分离两个组件：

1. **top-level pin owner** 固定为 `scripts/verify-cr011-r6-gate-c.ps1`。它持有 expected Schema/raw identity 常量 pin，负责 pre-run platform/expected 验证、启动无 pin Python core、解析固定输出、执行 expected/observed diff 和 fail-closed cleanup。它完全排除于 expected/observed subject projection；其 raw identity 只能由独立 reviewer 从 repo 文件外部复算，expected、observed、core 和 application child 均不得批准或声明其 identity。
2. **无 pin launcher/core/probe** 固定以 `scripts/verify-cr011-r6-gate-c.py` 为 evidence core，并包含其固定 support/probe 与 application subject。它们进入 expected/observed exact-set，但不得持有 expected raw hash、Schema pin、expected 生成/更新能力或 top-level parser verdict。top-level 以精确 CPython 启动该脚本后，运行该脚本的 OS process 本身就是 observed application startup evidence child；evidence core 必须先安装 guard，再在同一 process 内调用固定 FastAPI/Worker bootstrap。它不得另建 application grandchild/subprocess，也不得从另一个 PID 推断本 child 的 imports/images。

无 pin Python core/application child 必须：

1. top-level 使用精确 CPython executable、implementation/version、Windows version/architecture 和 venv/site-packages root；先验证 identity，再创建唯一 observed child；
2. 从 process creation 起传入 closed environment allowlist，不继承 `.env`、`PYTHONPATH`、`PYTHONHOME`、`sitecustomize/usercustomize`、proxy/index、Provider、数据库、Redis、Broker、secret 或 production 环境变量；
3. 使用 isolated/no-site 等价启动方式，在加入已验证 application/site-packages path 和 import application code 之前安装 Python audit/attempt guard；
4. 只允许固定 FastAPI bootstrap/app-factory 与 Worker bootstrap 入口，不接受任意 module、callable、command、shell、`-c` payload 或工作目录搜索；
5. 为每个 child 记录 root/self PID、entrypoint、开始/结束时间、exit code 和精确 stdout/stderr grammar；root PID 必须等于 evidence core 的 `GetCurrentProcessId` 结果，unexpected child/subprocess、额外输出、重复 marker 或 parser ambiguity 一律失败；
6. 在启动前与退出后对 subject identity 做同一 closed-set 复核；运行中或 before/after 漂移即失败，不得重试到另一份代码或环境；

top-level pin owner 与无 pin core 都必须进入 Gate C evidence bundle，但只有无 pin core/probe/application subject 进入 expected/observed projection；top-level 的 raw identity、pin constants、参数 schema、environment builder、parser/diff 和 cleanup 路径由 reviewer 外部复算并单独裁定。

每次可接受的 Gate C evidence bundle 必须包含两个不同 phase、不同 owner 且单向依赖的制品：

1. **pre-run `expected_subject_allowlist`**：优先固定为 R6 Gate C 实现新增的 repo 文件 `scripts/cr011-r6-expected-subject-allowlist.json`。其 Schema、exact grammar 和 entries 必须在任何 application child 创建前，依据稳定 checkout、exact platform、审阅过的 project source/import graph、exact dependency metadata 与 PE analysis 生成；其中每个 expected loaded-module entry 必须带枚举型 `checkpoint_id`，值只能是 `AFTER_GUARD_BEFORE_APPLICATION_IMPORT` 或 `AFTER_STARTUP_BEFORE_OUTPUT`，并预先列出同一稳定环境下该 observed child 在对应 checkpoint 应实际加载的 native module exact set，以及 evidence core Toolhelp library/symbol/flag/PID/call-site closed set。不得把同次或任何先前的 observed/loaded runtime ledger 作为生成输入。独立实现必须在 pre-run 复算其 closed entries、raw bytes/SHA-256；top-level pin owner 以常量 pin Schema 与 allowlist raw identity 后才可启动无 pin Python core/application child。application run、无 pin core/probe 和 observed collector 均不得生成、补齐、更新或重写该 repo 文件。
2. **post-run `observed_subject_ledger`**：只能由已启动的 observed application startup evidence child 对自身真正 import/audit/load/enumerate 的范围产生，并逐 entry 标明 observed owner；每个 loaded-module entry 必须带与实际枚举 checkpoint 一致的同一 closed `checkpoint_id`。module entries 只能来自 §2.4 self-PID fixed-checkpoint enumeration。top-level 只能只读收集、验证和比较，不得枚举 module、发明 observed entry 或代替 child 补账。observed 不得写回 expected、改变 expected pin、声称 top-level identity 或成为下一次 expected 的自动输入。artifact owner 固定为 application child runtime，phase 固定为该次 run 的 observed phase。

无自引用 ownership DAG 固定为 `reviewed source/dependency/PE analysis -> fixed expected repo file -> externally reviewed top-level pin owner -> no-pin core/application child -> observed ledger -> exact-set diff`。expected 文件不得把自身 raw identity 列为 subject entry；其 raw identity 只由 top-level pin owner 持有。expected 必须包含无 pin Python core/probe/support identity，且必须排除 top-level pin owner；无 pin core 不得包含、生成或更新 expected raw pin。top-level 自身 identity 作为独立 Gate evidence 由 reviewer 外部复算，不得由 expected/observed 批准，也不得进入二者 diff。

expected 与 observed 的 subject 范围恰为：

- 无 pin Python core、startup probe/support 和 exact collected-test manifest；top-level pin owner 明确排除；
- FastAPI/Worker entrypoint、bootstrap、Settings、Policy loader/companion/JCS/strict JSON 及其 startup transitive project-source closure；
- 当前稳定环境中该启动入口应实际 import/load 的 Python module 文件、distribution metadata/version、CPython executable/DLL、`.pyd`/DLL/PE image 及其 canonical local path、base-address-independent identity、raw bytes/SHA-256；expected 只能由审阅过的 source + exact dependency/PE analysis 预先确定，observed child 才记录其自身 runtime 实际值；
- 六项 R5 exact runtime closure、四项 package resources、external synthetic Policy raw/policy identity；
- fixed environment field names和非 secret typed values；SecretStr 只绑定对象/slot 边界，不读取、hash 或回显 secret value。

两个制品必须各自使用严格 UTF-8、无 BOM、LF、strict JSON duplicate-key rejection 和 closed exact keys；按固定 repo Schema 规范 canonical local path、on-disk case、entry order。artifact envelope 必须分别记录 `artifact_phase/artifact_owner`：expected 为 `PRE_RUN_FROZEN/FIXED_REPO`，observed 为 `POST_RUN_OBSERVED/APPLICATION_STARTUP_EVIDENCE_CHILD_RUNTIME`；这两个 envelope 字段按各自 Schema 独立验证，预期不同，不进入 subject exact-set projection。每个 entry 另行记录可比较的 `subject_phase/subject_owner`、role、raw bytes、SHA-256、exact platform 与无 pin core/clean-launcher identity；loaded-module entry 还必须记录 `checkpoint_id`、canonical drive-qualified local path 与 on-disk case，并明确排除 module base address、handle 和其他 ASLR-dependent value。expected 声明预期值，observed 只记录对应 child 实际值，normalized projection 必须逐字段一致。top-level identity 既不是 entry，也不是 projection 字段。

expected freeze timestamp 必须早于任何 child creation；observed event timestamp 必须位于该次冻结 run window 内且单调有序。timestamp 不进入 stable identity projection，但缺失、逆序、越过 run window、expected 在 child creation 后产生/修改，或 before/after file timestamp/identity 漂移均失败。

Gate C 必须先分别验证并记录 expected/observed raw bytes 与 SHA-256，再对二者 stable identity projection 做双向 exact-set diff；loaded-module stable key 固定为 `(checkpoint_id, canonical_path)`，entry order 固定为上述 enum 顺序后接 canonical path UTF-8 byte order，projection 必须包含 `checkpoint_id`、canonical path/case/order、role、raw bytes/hash、`subject_phase/subject_owner`、platform 和无 pin core/launcher identity。missing/extra/mismatch 与 duplicate 均按该 composite key 裁定；同一路径在两个不同 checkpoint 各出现一条是合法且必需的两个 entries，不算 duplicate，同一 checkpoint/path 重复才失败。每个 checkpoint 的两次 snapshot ordinal 只用于证明该 checkpoint 内稳定性，必须留在 dynamic raw evidence，既不生成两份 stable entries，也不进入 stable projection。`missing=0`、`extra=0`、`mismatch=0` 且 duplicate/alias `0` 才可继续。expected 只覆盖 R6 受测 subject：无 pin core/probe/support、project source、CPython/venv closure，以及同一稳定 exact platform 下对应 observed child 在两个固定 checkpoint 应 import/load 的第三方/native images 和 checkpoint membership；不要求维护跨机器固定的全部 Windows system DLL 全局清单，且不得把 top-level pin owner 塞入 projection。

expected allowlist、observed ledger、二者 Schema、top-level pin 和各自 raw identities 只允许进入 R6 Gate C dynamic evidence，不得进入 R6 decision preimage、九份 Request 正文或 baseline manifest。独立 reviewer 必须从固定 repo expected、top-level/core 原文件、当前 checkout、exact platform 和 raw files 重算，不得相信 runner 汇总或 observed 自报。

### 2.3 Python-visible attempt oracle

guard 必须在 application/site-packages import 前生效，并同时覆盖 public `socket` API、底层 `_socket` 可调用面、async/network helper 可达面和 Python audit events。至少下列 attempt 一旦发生即先计数、立即失败且不得继续 startup：

- IPv4/IPv6 TCP、UDP、raw socket、socketpair、AF_UNIX/local socket 的 create/connect/bind/listen/accept/send/receive；
- `getaddrinfo`、`getnameinfo`、`gethostby*`、`getfqdn`、hostname-to-address helper 和任何显式 `localhost`、numeric loopback 或其他 peer resolution；
- Python 可见的 HTTP/TLS client、subprocess/network helper、Windows named-pipe helper 或 `_winapi` pipe construction；
- attempt 后捕获异常再继续、临时解除 guard、替换 counter、晚安装 guard 或在另一个 Python child 中尝试。

唯一例外是当前锁定 SQLAlchemy import closure 触发的本机名读取：

```text
python_visible_socket_attempts=0
python_visible_dns_attempts=0
python_visible_local_socket_attempts=0
local_hostname_reads=1
```

`local_hostname_reads` 只允许返回本机名，不允许正向/反向解析、peer lookup、socket object 或外部 I/O；`0`、`>1`、来自非锁定 call site 或 call stack 漂移均失败。若未来依赖消除该读取，必须提升 successor 或修订已批准 evidence contract，不得把 expected `1` 静默放宽为范围。

正向 guard selftest 必须在与 application child 隔离的专用 child 中分别触发 Python TCP、UDP、DNS、AF_UNIX/local socket 和额外 `gethostname`，并证明每项被相应 counter/固定错误捕获；selftest attempt 不得混入 application startup counters。guard selftest 自身不产生 Provider/业务网络，只使用 fail-before-I/O seam 或固定 monkeypatch target。

### 2.4 source、AST、import、ctypes 与 PE closed allowlist

动态 counter 不是唯一证据。Gate C 在 child 启动前必须对 §2.2 subject 执行 closed allowlist：

1. **source/AST**：拒绝未批准的 `socket/http/ssl/urllib/requests/subprocess/multiprocessing.connection/_winapi` 使用、动态 `eval/exec/compile/__import__`、可变 import target、网络/pipe literal、direct syscall wrapper 和绕过 guard 的别名；第三方 dependency 以 exact identity + actual import closure 约束，不因名称出现就机械误报；
2. **import**：audit/import ledger 必须与 expected module/file closed set 精确一致；application child 禁止 namespace path 扩展、zip/path hook 漂移、user site、current-working-directory import 和运行后新增 native extension；
3. **production loader ctypes/FFI**：application/runtime project-source 唯一例外仍是 `policy_loader` 对 `kernel32.GetDriveTypeW`、`kernel32.QueryDosDeviceW`、`kernel32.CreateFileW`、`kernel32.CloseHandle` 的既有固定解析；`CreateFileW` 仍受 R5 lexical/fixed-drive/non-reparse/regular-file gate，不能指向 device、UNC 或 pipe。R6 不给 `policy_loader` 或其他 application runtime 增加任何 module-enumeration symbol、branch 或 output；
4. **evidence core module-enumeration ctypes/FFI**：只在 Win64 `scripts/verify-cr011-r6-gate-c.py` evidence core、Python guard 已安装后，允许固定 `ctypes.WinDLL("kernel32", use_last_error=True)` 与 named-attribute static binding：`GetCurrentProcessId`、`CreateToolhelp32Snapshot`、`Module32FirstW`、`Module32NextW`、`CloseHandle`。ABI 必须在任何 Toolhelp call 前机械断言并冻结如下；任一 type、size、alignment、offset、argtypes 或 restype 偏差立即失败，不得尝试兼容其他 architecture：

   - `DWORD = ctypes.c_uint32`，size `4`；`BOOL = ctypes.c_int32`，size `4`；`HANDLE = ctypes.c_void_p`，pointer width/size `8`；`BYTE = ctypes.c_ubyte`；`LPBYTE = ctypes.POINTER(BYTE)`；`HMODULE = ctypes.c_void_p`；Win64 `ctypes.c_wchar` size 必须为 `2`；
   - `MODULEENTRY32W` 使用默认 Win64 native alignment、不得设置 `_pack_`，alignment `8`、`sizeof=1080`，field/array/offset 必须逐项为：

| field | exact ctypes type | Win64 offset |
|---|---|---:|
| `dwSize` | `DWORD` | 0 |
| `th32ModuleID` | `DWORD` | 4 |
| `th32ProcessID` | `DWORD` | 8 |
| `GlblcntUsage` | `DWORD` | 12 |
| `ProccntUsage` | `DWORD` | 16 |
| `modBaseAddr` | `LPBYTE` | 24 |
| `modBaseSize` | `DWORD` | 32 |
| `hModule` | `HMODULE` | 40 |
| `szModule` | `ctypes.c_wchar * 256` | 48 |
| `szExePath` | `ctypes.c_wchar * 260` | 560 |

   - `GetCurrentProcessId.argtypes=[] / restype=DWORD`；`CreateToolhelp32Snapshot.argtypes=[DWORD,DWORD] / restype=HANDLE`；`Module32FirstW.argtypes=[HANDLE,ctypes.POINTER(MODULEENTRY32W)] / restype=BOOL`；`Module32NextW` 使用相同 argtypes/restype；`CloseHandle.argtypes=[HANDLE] / restype=BOOL`；
   - snapshot flags 必须恰为 `TH32CS_SNAPMODULE=0x00000008 | TH32CS_SNAPMODULE32=0x00000010`，合成值逐 bit 等于 `0x00000018`；PID 必须逐次等于刚由 `GetCurrentProcessId` 取得且与 top-level 记录相同的 self PID；不得使用 process/thread/heap snapshot flag；
   - `INVALID_HANDLE_VALUE` 必须按 Win64 pointer-width all-ones `0xffffffffffffffff` 比较；每次 `Module32FirstW` 前用全新 zeroed struct 并设置 `dwSize=ctypes.sizeof(MODULEENTRY32W)=1080`。First 返回 false 一律失败；Next 返回 false 后必须立即、先于任何其他 Win32/ctypes call 读取 `ctypes.get_last_error()`，只有 `ERROR_NO_MORE_FILES=18` 是正常结束；Create/First/Close 失败同样必须立即读取 last error 并失败；
   - 每个成功取得的 snapshot handle 必须在 `finally` 中对同一 handle 调用 `CloseHandle` 恰好一次；close false、double-close、遗漏 finally、handle leak 或在 close 前覆盖 handle 均 fail closed。module path 只取 `MODULEENTRY32W.szExePath`，本 R6 不授权 `GetModuleFileNameW`；

5. **fixed checkpoints 与只读输出**：每个 FastAPI/Worker observed child 必须在 `AFTER_GUARD_BEFORE_APPLICATION_IMPORT` 与 `AFTER_STARTUP_BEFORE_OUTPUT` 两个固定 checkpoint 各连续枚举两次；每份 raw snapshot evidence 带 `snapshot_ordinal=1|2`，同一 checkpoint 两次 canonical set 必须相同，不得以 retry 掩盖 snapshot drift；ordinal 只供同 checkpoint 稳定性判断，不进入 stable projection。第二 checkpoint 后立即封闭 Python import audit 与 evidence-core ctypes load wrapper；只能据此声明 `post_seal_python_import_or_ctypes_load_events=0`，任一被该 seal 观测到的 Python import 或 ctypes load event 都失败。该 counter 不观测、不证明 native extension 内部 delay-load 或任意 native code 的 new-module 行为，这两类 native 结果明确 `NOT_CLAIMED`。child 对每个实际 loaded module 按对应 `checkpoint_id` 输出来自 `szExePath` 的 canonical drive-qualified local path/on-disk case、base-address-independent role、raw byte length 与 read-only streaming SHA-256；module base address、handle、load address 和其他 ASLR-dependent value 不得进入 ledger。路径必须是 fixed local physical drive 上既存 regular file，拒绝 relative、device、UNC、redirected/reparse traversal、case alias、shadow 或 before/read/after identity 漂移；
6. **FFI closed world**：project/evidence source 显式调用 `LoadLibrary*`、`GetProcAddress`、ordinal lookup、动态 library/symbol 名称，或调用 `OpenProcess`、其他 PID 枚举、process memory read/write、module injection、network/pipe FFI，一律失败。固定 `ctypes.WinDLL("kernel32", use_last_error=True)` 的 named-attribute binding 在 CPython/Windows 平台内部不可避免使用 loader/resolver（包括内部 `GetProcAddress`）不视为 project/evidence source 的额外显式调用，但只限上列静态 library 与 symbols；额外 library、named attribute、symbol 或 ordinal 一律失败；
7. **PE/native image**：两个 checkpoint 的实际 loaded image set、canonical path、raw bytes/hash、import DLL/symbol inventory 必须与 expected closed-set 精确匹配。允许 CPython/既有依赖因平台实现包含的 native import，只能按逐 image/symbol 明示例外并由 Python guard/locked call path 约束；该例外不得被描述成 OS-level interception；
8. **before/after**：source、wheel/package resource、external Policy、无 pin core/probe、module 和 native image identity 在 startup 前后必须不变；top-level raw/pin identity 另由外部 reviewer 在 run 前后复算。临时副本、shadow DLL、PATH search、同名不同 case 或 post-check replacement 均失败。

每个 observed child 的 closed counter block 必须逐字包含：

```text
module_enumeration_fixed_checkpoints=2
module_enumeration_snapshots_per_checkpoint=2
module_enumeration_other_pid_attempts=0
module_enumeration_unapproved_library_attempts=0
module_enumeration_unapproved_symbol_attempts=0
module_snapshot_drift=0
observed_loaded_module_missing=0
observed_loaded_module_extra=0
observed_loaded_module_duplicate=0
observed_loaded_module_path_mismatch=0
observed_loaded_module_hash_mismatch=0
toolhelp_abi_mismatch=0
toolhelp_invalid_handle=0
toolhelp_first_failures=0
toolhelp_next_unexpected_failures=0
toolhelp_close_failures=0
toolhelp_double_close=0
toolhelp_handle_leaks=0
toolhelp_late_get_last_error_reads=0
post_seal_python_import_or_ctypes_load_events=0
```

anti-forgery 至少覆盖：删除/重命名 required test、伪造 passed count、伪造 marker、重复 marker、unexpected import/image、`ctypes.WinDLL("ws2_32")`、named-pipe symbol、guard 晚安装/移除、counter reset、额外 hostname read、observed 自喂 expected、以先前 observed 自动生成 expected、child creation/run 后修改 expected、top-level 误纳 subject/projection、无 pin core 持有 expected/Schema pin、observed 声称 top-level identity、loaded-module `checkpoint_id` missing/unknown/wrong/order drift、同 checkpoint composite-key duplicate、跨 checkpoint 同路径被误判 duplicate、snapshot ordinal 被纳入 stable projection、expected/observed missing/extra/mismatch、case alias/hash/platform/owner/phase/core-launcher identity/timestamp 漂移、module enumeration 出现在 top-level/policy_loader/application runtime 或 guard 前、额外 FFI library/symbol/ordinal、显式 `LoadLibrary*`/`GetProcAddress`、`OpenProcess`/other PID/non-module snapshot flag、wrong argtypes/restype、DWORD/BOOL/HANDLE width 错误、`MODULEENTRY32W` field/array/alignment/size/offset 或 `dwSize` 错误、wrong flags/self PID/invalid-handle oracle、First failure、Next 非 `ERROR_NO_MORE_FILES=18` failure、late `get_last_error`、Close failure/double-close/leak、missing/extra/duplicate module、snapshot drift、post-seal Python import/ctypes load event、shadow/reparse/case/path/raw-bytes/hash mismatch、application child 继承 poison environment、cleanup failure。每个 forged case 必须 nonzero exit 且不得输出 Gate C PASS。

### 2.5 明确不声称的 native/hostile 范围

R6 证据建立在“受信 launcher + exact locked subject 未被恶意替换”的前提上，不是 OS sandbox、EDR、内核审计或任意代码执行防线。以下能力明确不在 R6 Gate C 的可证明范围：

- 任意 in-process DLL/native extension injection、debugger/hook、内存 patch、ROP、反射加载或已 compromise interpreter；
- 通过 `ws2_32`、`ntdll`、AFD device、named-pipe NT object 或 direct syscall 绕过 Python audit/guard 的 hostile native code；
- 第二 module checkpoint 后由 native extension 内部 delay-load 或任意 native code 直接产生的新 module；post-seal counter 只覆盖 Python import audit 与 evidence-core ctypes load wrapper，这类 native new-module 结果保持 `NOT_CLAIMED`；
- 任意同进程 Python 私有对象状态篡改，包括绕过模型验证直接改写 `__dict__`、private attribute 或 `SecretStr._secret_value`；
- compromised kernel/provider、未授权 driver、PID spoof/reuse 攻击或 Gate C 之外的其他进程；
- 对 native WinSock/NamedPipe attempts 的 OS-level 全量、无丢失、root+descendant 归属结论。

这些项是 `OUT_OF_EVIDENCE_SCOPE / NOT AUTHORIZED`，不是可接受行为。R5 明确禁止 loader、launcher、guard、manifest 或测试读取、probe、比较、序列化或 hash secret value；因此 R6 只能把 SecretStr 对象/slot identity 纳入 subject，不能为检测 `SecretStr._secret_value` 的恶意同进程篡改而触碰其值，也不得声称已经检测或排除该攻击。R6 的 subject 假设是 exact locked trusted code 按批准路径执行；closed allowlist 证明该 subject 没有未批准入口，不证明 hostile native 或 private-state mutation 在任意已 compromise 进程中不可能发生。

规范行为不因该 blind spot 放宽：包含 secret wrapper、Provider/transport 与 Broker/backend 配置在内的全部 Settings 仍必须先通过 R5 初始类型/required/cross-field safety 验证，再进入 Policy validation/cross-binding；证据工具不得读取 secret 值，Provider 与 Broker connection 仍不得创建或尝试。

### 2.6 未来强证据必须另行授权

若未来必须声称 `native_os_winsock_attempts=0` 或 `windows_named_pipe_attempts=0`，必须另行提升 successor 并显式授权独立、最小权限、一次性的 elevated ETW/helper 方案。至少要求：

1. 分离的 positive-calibration trace 与 application trace；不得把 selftest events 混入 target counters；
2. Winsock-AFD/Sockets/NameResolution/DNS-Client + Kernel-File + Kernel-Process（或经独立验证的等价 OS providers）；
3. native positive selftest 必须捕获 socket/connect/bind/listen/send、DNS resolver、`Create/Open/Connect/WaitNamedPipe` 的精确 provider/event/PID 字段；
4. root PID 与全部 descendants 的闭包、process start/stop correlation、PID reuse/time-window 防护；
5. `Buffers Lost=0`、`Total Events Lost=0`、provider dropped-events `0`、解析 unknown events `0`；
6. unique session name、create 返回失败也无条件 stop、stop/absence/temp cleanup 全部 fail-closed；
7. 提升 helper identity、权限边界、UAC/审计影响、回滚和独立 reviewer 批准。

R6 不授予上述权限，也不允许当前 runner探测或修改 firewall、audit policy、event channel、driver、系统服务或全局配置。

---

## 3. R6 三层 Gate

### 3.1 R6 Gate A：审批前静态可签署性

Gate A 必须在任何 R6 审批前只读完成：

1. 机械复算 R3、R4、R5 raw/decision identities、R3 manifest/15 leaves 和 R5 exact dependency lock；
2. 验证 §4.1 当前十一文件 pre identities 逐字匹配，`approval_pre_meta.py::_BASELINE_IDENTITY` 精确指向 current baseline manifest；
3. 确认 R6 恰好一个新决策 `STARTUP-D-005-R6`，只 successor evidence model；`STARTUP-D-001`～`004`、`006`、application/runtime behavior 和 Policy implementation delta 为零，evidence tooling delta 只限 §1.3 closed set；
4. 机械确认 §2.2 top-level pin owner 固定为 `scripts/verify-cr011-r6-gate-c.ps1`、独立外部复算且排除于 subject projection；无 pin core 固定为 `scripts/verify-cr011-r6-gate-c.py`、作为唯一 observed child 进入 expected/observed exact-set 且不持有 pin；pre-run expected 与 child-owned post-run observed 的 owner/phase/Schema/grammar/identity/DAG 分离，expected 不从 observed 派生且 child/run 后不可修改，observed 不得声称 top-level identity；
5. 机械验证 §2.4 production loader 四符号与 evidence-core-only self-PID Toolhelp 五符号严格分域；Win64 DWORD/BOOL/HANDLE、五 API argtypes/restype、`MODULEENTRY32W` fields/arrays/alignment/size/offset、`dwSize`、flags `0x18`、invalid handle、immediate last-error、First/Next/Close/cleanup oracle逐字匹配；loaded-module `checkpoint_id` composite key/order/projection 和 snapshot-ordinal 排除规则闭合；显式 `LoadLibrary*`/`GetProcAddress`、其他 PID/library/symbol/ordinal 和 runtime module enumeration 均被拒绝；扫描 native internal delay-load/new-module 与 WinSock/NamedPipe `NOT_CLAIMED` 不得被等同于 `0/PASS/ZERO/NONE`；
6. 验证九角色 approval schema、十一文件领域投影、无环 DAG 和 §7 非授权边界；
7. 严格 UTF-8/LF、无 BOM/NUL/替换字符，按 §8 双实现复算 R6 decision snapshot；
8. material-value scan 为零：不得出现真实 secret、Provider/业务 endpoint、CIDR、Profile、业务数据、production 放行值或新增网络许可。

Gate A 不运行 application/ETW，不安装依赖、不访问网络、不修改十一文件、不改变 runtime，也不等于批准。任一 identity、decision set、encoding、scope 或 evidence wording 失败都使候选不可签。

### 3.2 R6 Gate B：批准后的十一文件原子同步

只有九角色以同一 R6 decision snapshot 有效批准后，才允许按 §4 执行十一文件原子同步。同步只把 R5 unqualified zero-socket evidence wording 投影为 R6 分层合同；不得修改 Policy/Schema/loader/bootstrap、依赖、表/API/page/P0 数量、Provider/DB/部署边界或 R5 snapshot。

全部 post bytes 必须先在临时区生成、独立复核，再全有或全无替换。同步成功不等于 R6 Gate C、BASE-004、P0、AC 或 production PASS。

### 3.3 R6 Gate C：收窄合同下继续 R5 场景

Gate B PASS 后，R6 Gate C 可以继续执行 R5 已授权的本地离线 startup adoption，但必须重新运行并同时满足：

1. R5 §2.1～§2.4、§2.5 除被 R6 明确 successor 的 OS-level evidence claim 外的全部正负向、stage oracle、单次 hash、approval pin、cross-binding、脱敏和 local/test/prod fail-closed 场景；
2. §2.2 externally reviewed top-level pin owner、进入 projection 的无 pin core/application subject、pre-run expected allowlist、child-owned post-run observed ledger、双向 exact-set diff，§2.3 四个精确 counter，以及 §2.4 self-PID fixed-checkpoint loaded-module enumeration、closed counters/allowlist/anti-forgery；
3. FastAPI/Worker 正向启动先验证后构造/暴露，`prod` 在 app/Celery 创建和任何外部 I/O 前拒绝；
4. 聚焦 Backend 回归、R4 full Gate B、Ruff/format/mypy/pip consistency 和默认本地离线质量门禁；
5. 输出 native OS/NamedPipe 两个 `NOT_CLAIMED` marker；任何 unqualified `zero-socket startup evidence` 成功文案均拒绝；
6. 独立 reviewer 从固定 repo expected、top-level/core 原文件、当前 checkout、exact platform 与 raw files 外部复算 top-level raw identity、expected/observed identities、双向 diff、counter、call order、test collection 和 anti-forgery；逐 child 复核 Win64 ABI/layout、self PID、Toolhelp flags/symbols/error/cleanup、checkpoint-keyed entries、两次 snapshot、canonical module path/raw hash和 post-seal Python import/ctypes load counter；确认 snapshot ordinal 未进入 stable projection，native internal delay-load/new-module 未被冒充为零，top-level 未进入 projection、core 未持 pin、observed 未声称 top-level identity、expected 未由 observed 派生，且无 Provider/DB/Redis/Broker/真实环境/部署。

R5 先前因 native OS evidence 不可证明而产生的 blocked/partial run 不得被追认为 R6 PASS。R6 Gate C 需要在 R6 Gate B 后以稳定代码和全新净化 child 重跑。依赖 acquisition 如已由逐字匹配缓存满足，可以记录 request count `0`；不得重新扩大网络。

Gate C PASS 后仍按 R5 `STARTUP-D-006` 重新裁定正式 DoD。`BASE-004` 必须继续 `partial`，除非其全部 Request DoD 与全局 review/QA/remote evidence 独立满足；本 CR 明禁 commit/push/PR，故 R6 Gate C 本身不能把它升级为 implemented。

---

## 4. 十一文件 active-baseline 原子同步

### 4.1 精确目标与当前 pre identities

批准后的同步目标必须恰为：

1. `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md`
2. `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md`
3. `Request/FinAudit_Agent_数据库设计说明书_V1.0.md`
4. `Request/FinAudit_Agent_API接口设计说明书_V1.0.md`
5. `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md`
6. `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md`
7. `Request/FinAudit_Agent_测试与验收方案_V1.0.md`
8. `Request/FinAudit_Agent_部署与运维说明书_V1.0.md`
9. `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md`
10. `docs/baseline-manifest.md`
11. `backend/app/approval_pre_meta.py`

当前 pre-sync raw identity 固定如下：

| path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 129763 | `96ea16772efbdd23d72482a296fbf51befe562fca1bfd39d33e1e9d336538a11` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 91332 | `62274fe303c4291483c7287e1dfd93a9f80c7eb4a70df386736d0314dd057805` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 116243 | `7d30cba02cb8a66c13a797e685da0012d894beb9d1644254563519f6c6af24f8` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 328584 | `5412bbe64dcf9ed40c566ab51963a2b1d61644936aeb8e54f231998caf4652c8` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 83876 | `6df77a47fa0a48ec76c366b4a43a9fb4b444ceb993b0eb35a619144b34a4493a` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 52141 | `83741903459debffe952e532a0b564138110edbe734d7e303d2358eddc450b28` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 50860 | `b073429523b96bf2562df6543245a60e74e5ecb976b8e3adb6769e74f06fd4db` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 55131 | `3d559185005f9e8798ded422bb25dafa343ddd023637ec8e07330a8a0119e27b` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 107268 | `48e413d360eb82332a035d4fdbb604a218137f9339dce0706d734eeea9eb8dfa` |
| `docs/baseline-manifest.md` | 1661 | `aa1918af6d47eb5f67d68dd84a7389f0f252c2b2a296ca06ba15547e0eb30b34` |
| `backend/app/approval_pre_meta.py` | 22193 | `cf7d0f5dfe82ccb9c3ceebe914ce341be7c77a8c45f464f69933061aa7988cc6` |

`approval_pre_meta.py::_BASELINE_IDENTITY` 当前必须精确为 `1661/aa1918af6d47eb5f67d68dd84a7389f0f252c2b2a296ca06ba15547e0eb30b34`。R6 仍只允许将其 `byte_length` 与 `sha256` 两个 literal re-pin 到 post-sync manifest identity；不得修改其他 byte。

### 4.2 九份 Request 的唯一领域投影

九份 Request 只允许各增加一条 `CR-011-R6 / approved startup evidence-boundary successor` 修订记录和一处必要投影：

- 需求：运行禁令不变；Gate C 成功范围改为 trusted locked subject/Python-visible zero，native OS/NamedPipe `NOT_CLAIMED`；P0 与 BASE-004 状态不自动变化。
- 架构：记录固定 top-level pin owner 与无 pin launcher/core 的职责分离；top-level 持 pin、启动/解析/diff/cleanup 并排除于 subject projection，无 pin evidence core 作为唯一 observed application child 进入 expected/observed exact-set；child 仅在 guard 后以 self-PID Toolhelp closed FFI 只读枚举自身 module，固定 pre-run expected、child-owned post-run observed、Python guard 与 closed allowlist 不进入 `policy_loader`/application runtime，不增加 runtime client、hook、driver 或持久化。
- 数据库：零表/列/migration/Repository/AI-005 delta。
- API：零 route/status/body delta；evidence marker 不成为公开 API。
- 页面：零页面/路由 delta；前端不得把 `NOT_CLAIMED` 显示为 readiness。
- AI/RAG：R3 artifacts、Policy/Schema/companion/registry、loader/bootstrap 与 `AI-D-*` 零 delta。
- 测试：新增 R6 top-level 外部 identity 复算、top-level 排除/core 纳入 projection、expected/child-owned observed owner/phase/identity、checkpoint-keyed self-PID Toolhelp module set/path/raw hash、Win64 ABI/error/cleanup oracle、双向 exact-set diff、post-seal Python import/ctypes load counter、anti-forgery 与 native `NOT_CLAIMED` oracle；不允许 core 持 pin、observed 声称 top-level identity 或自批准 expected，不冒充 OS telemetry。
- 部署：不部署、不提升权限；未来 elevated ETW 必须另行 CR。
- 计划：BASE-004/P0/AC/Provider/DB/Redis/Broker/deploy/production 状态保持不升级。

Request 不得包含自身 post identity、R6 snapshot hash、动态 Gate C evidence 或实现文件 hash；不得顺带更新其他 gap、数量、候选 CR 或 acceptance 状态。

### 4.3 无环生成 DAG 与原子验收

生成顺序固定为：

```text
R3/R4/R5 identities + current 11 pre identities
                         |
              R6 sections 1-8 snapshot
                         |
               valid nine-role approval
                         v
             nine Request post bytes
                         v
          nine Request post identities
                         v
           baseline-manifest post bytes
                         v
          baseline-manifest post identity
                         v
 approval_pre_meta._BASELINE_IDENTITY two-literal re-pin
                         v
             R6 section 9 dynamic evidence
```

Request 不包含自身 post identity；baseline manifest 只记录九份 Request post identities且不记录自身 identity；`approval_pre_meta.py` 只消费已经生成的 manifest post identity。R6 文件不属于十一文件同步集合。所有 post identities 只允许进入 §9 或外部 tracking，不得进入 R6 decision preimage。

必须先在临时区生成并验证全部 post bytes，再原子替换十一文件。任一 pre identity、领域投影、post hash、manifest 条目、two-literal diff、UTF-8/LF、baseline verifier 或独立复核失败，回滚整个集合，不得保留部分同步。

---

## 5. 九角色审批与可复制记录

### 5.1 必需角色

R6 必须由以下九角色共同批准；同一人覆盖多个角色时可合并一条记录，但必须逐字列全：

| 必需角色 | 必须审批的范围 |
|---|---|
| 需求/产品 | BASE-004/P0 状态不升级、用户可见 `NOT_CLAIMED` 语义 |
| 架构 | trusted launcher/locked subject 边界、不是 OS sandbox |
| 数据/DBA | 零数据库/migration/Repository delta |
| 后端/API | FastAPI/Worker 行为零 delta、Python guard 与 evidence marker 非 API |
| 前端/UI | 零页面/路由 delta、不得误呈现 readiness |
| AI/RAG | R3/R5 Policy contract 与 `AI-D-*` 零 delta |
| 测试/质量 | 分层 counter、closed allowlist、anti-forgery、十一文件原子同步 |
| 运维/可靠性 | clean environment、exact identity、无提升权限/部署、future ETW boundary |
| 安全 | native blind spot 明示、hostile injection out-of-evidence、规范禁令仍有效 |

### 5.2 可复制 approval template

以下记录只能在 R6 Gate A PASS 且 decision snapshot 已由独立实现复算后填写；任何占位、缺失字段或不同 snapshot 都不构成批准：

```text
姓名=YHBX
角色=需求/产品、架构、数据/DBA、后端/API、前端/UI、AI/RAG、测试/质量、运维/可靠性、安全
decision=APPROVED
selected_option=AI-D-009～AI-D-014_R3_EXACT_WITH_R4_R5_BASE_AND_R6_STARTUP_EVIDENCE_BOUNDARY
selected_decisions=[STARTUP-D-005-R6]
preserved_decisions=[STARTUP-D-001,STARTUP-D-002,STARTUP-D-003,STARTUP-D-004,STARTUP-D-006]
superseded_decisions=[STARTUP-D-005_EVIDENCE_MODEL_ONLY]
rejected_decisions=[]
cr_revision=CR-011-R6
base_revision=CR-011-R5
base_raw_bytes=53927
base_raw_sha256=089cbb5c88659dc7076df191af6d4c84492aa30e081878c1bfc232596a8407a7
base_decision_preimage_bytes=50926
base_decision_snapshot_sha256=fb6aa225dae67a6068e84935e4a77affe84b143de5de2908b555089f9334c5ae
r3_decision_preimage_bytes=26563
r3_decision_snapshot_sha256=b03ca205d74a6abfb6ec1fbe1606ee327600d622bed392e8eccb5591b331a0be
artifact_manifest_raw_bytes=5128
artifact_manifest_sha256=f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c
dependency_lock_path=scripts/requirements-cr011-gate-b.txt
dependency_lock_raw_bytes=641
dependency_lock_sha256=0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c
decision_snapshot_sha256=<R6_GATE_A_OUTPUT>
environment_scope=contract_offline_startup_trusted_locked_subject
policy_version=1
baseline_manifest_pre_raw_bytes=1661
baseline_manifest_pre_raw_sha256=aa1918af6d47eb5f67d68dd84a7389f0f252c2b2a296ca06ba15547e0eb30b34
approval_pre_meta_pre_raw_bytes=22193
approval_pre_meta_pre_raw_sha256=cf7d0f5dfe82ccb9c3ceebe914ce341be7c77a8c45f464f69933061aa7988cc6
approval_pre_meta_repin_scope=_BASELINE_IDENTITY_BYTE_LENGTH_AND_SHA256_ONLY
scope=CR-011-R6_BASE004_STARTUP_EVIDENCE_BOUNDARY_ONLY
startup_behavior_scope=NETWORK_AND_NAMED_PIPE_STILL_FORBIDDEN
startup_evidence_model=TRUSTED_CLEAN_LAUNCHER_EXACT_LOCKED_SUBJECT_PYTHON_VISIBLE_ZERO
expected_subject_allowlist_path=scripts/cr011-r6-expected-subject-allowlist.json
expected_subject_allowlist_owner=FIXED_REPO_PRE_RUN_INDEPENDENTLY_RECALCULATED
expected_subject_allowlist_phase=PRE_RUN_FROZEN
expected_subject_allowlist_from_observed=FORBIDDEN
expected_subject_allowlist_mutation_after_child_creation=FORBIDDEN
subject_identity_schema_path=scripts/cr011-r6-subject-identity.schema.json
subject_identity_schema_owner=FIXED_REPO_INDEPENDENTLY_RECALCULATED
top_level_expected_pin_owner_path=scripts/verify-cr011-r6-gate-c.ps1
top_level_expected_pin_owner_role=PIN_START_PARSE_DIFF_CLEANUP
top_level_expected_pin_owner_subject_projection=EXCLUDED
top_level_expected_pin_owner_raw_identity_review=EXTERNAL_INDEPENDENT_RECALC_ONLY
expected_subject_allowlist_raw_pin_owner=TOP_LEVEL_EXPECTED_PIN_OWNER
no_pin_launcher_core_path=scripts/verify-cr011-r6-gate-c.py
no_pin_launcher_core_expected_observed_projection=INCLUDED
no_pin_launcher_core_expected_schema_pin=FORBIDDEN
observed_application_child_process=NO_PIN_EVIDENCE_CORE_SAME_PROCESS_AS_FIXED_STARTUP_BOOTSTRAP
observed_subject_ledger_owner=APPLICATION_STARTUP_EVIDENCE_CHILD_RUNTIME_ONLY
observed_subject_ledger_phase=POST_RUN_OBSERVED
observed_subject_ledger_top_level_identity_claim=FORBIDDEN
module_enumerator_owner=NO_PIN_APPLICATION_CHILD_EVIDENCE_CORE_ONLY_AFTER_GUARD
module_enumerator_library=kernel32
module_enumerator_symbols=[GetCurrentProcessId,CreateToolhelp32Snapshot,Module32FirstW,Module32NextW,CloseHandle]
module_enumerator_resolution=CTYPES_WINDLL_FIXED_NAMED_ATTRIBUTE_ONLY
module_enumerator_snapshot_flags=TH32CS_SNAPMODULE_PLUS_TH32CS_SNAPMODULE32
module_enumerator_pid=SELF_ONLY
module_enumerator_checkpoints=[AFTER_GUARD_BEFORE_APPLICATION_IMPORT,AFTER_STARTUP_BEFORE_OUTPUT]
module_enumerator_snapshots_per_checkpoint=2
loaded_module_checkpoint_id_enum=[AFTER_GUARD_BEFORE_APPLICATION_IMPORT,AFTER_STARTUP_BEFORE_OUTPUT]
loaded_module_stable_key=[checkpoint_id,canonical_path]
loaded_module_stable_order=CHECKPOINT_ENUM_THEN_CANONICAL_PATH_UTF8_BYTES
loaded_module_cross_checkpoint_same_path=REQUIRED_DISTINCT_ENTRIES_NOT_DUPLICATE
module_snapshot_ordinal=RAW_STABILITY_EVIDENCE_ONLY_EXCLUDED_FROM_STABLE_PROJECTION
module_path_source=MODULEENTRY32W_SZEXEPATH
module_identity_projection=CANONICAL_LOCAL_PATH_ON_DISK_CASE_RAW_BYTES_SHA256_BASE_ADDRESS_EXCLUDED
module_enumerator_project_explicit_loadlibrary_getprocaddress=FORBIDDEN
module_enumerator_platform_internal_fixed_named_resolution=ALLOWED_ONLY_AS_CTYPES_IMPLEMENTATION_DETAIL
toolhelp_abi_platform=WIN64_POINTER_WIDTH_8_WCHAR_WIDTH_2_ONLY
toolhelp_scalar_types=DWORD_C_UINT32_SIZE4|BOOL_C_INT32_SIZE4|HANDLE_C_VOID_P_SIZE8
toolhelp_moduleentry32w_layout=DEFAULT_ALIGNMENT8_SIZE1080_OFFSETS_0_4_8_12_16_24_32_40_48_560_ARRAYS_256_260
toolhelp_api_signatures=GetCurrentProcessId_VOID_TO_DWORD|CreateToolhelp32Snapshot_DWORD_DWORD_TO_HANDLE|Module32FirstW_HANDLE_PTR_MODULEENTRY32W_TO_BOOL|Module32NextW_HANDLE_PTR_MODULEENTRY32W_TO_BOOL|CloseHandle_HANDLE_TO_BOOL
toolhelp_dwsize_before_first=1080
module_enumerator_snapshot_flags_exact_hex=0x00000018
toolhelp_invalid_handle_value_win64=0xffffffffffffffff
toolhelp_last_error_read=IMMEDIATE_AFTER_FAILED_CREATE_FIRST_NEXT_CLOSE
toolhelp_next_normal_end_error=ERROR_NO_MORE_FILES_18_ONLY
toolhelp_close_oracle=EXACTLY_ONCE_IN_FINALLY_NO_DOUBLE_CLOSE_OR_LEAK
module_enumeration_other_pid_attempts_required=0
module_enumeration_unapproved_library_attempts_required=0
module_enumeration_unapproved_symbol_attempts_required=0
module_snapshot_drift_required=0
observed_loaded_module_missing_extra_duplicate_path_hash_mismatch_required=0
toolhelp_abi_invalid_handle_first_next_close_double_close_leak_late_error_failures_required=0
post_seal_python_import_or_ctypes_load_events_required=0
post_seal_native_extension_internal_delay_load=NOT_CLAIMED
post_seal_arbitrary_native_new_module=NOT_CLAIMED
subject_identity_exact_set_diff_required=0
python_visible_socket_attempts_required=0
python_visible_dns_attempts_required=0
python_visible_local_socket_attempts_required=0
local_hostname_reads_required=1
native_os_winsock_attempts=NOT_CLAIMED
windows_named_pipe_attempts=NOT_CLAIMED
hostile_native_injection=OUT_OF_EVIDENCE_SCOPE_NOT_AUTHORIZED
same_process_private_python_state_mutation=OUT_OF_EVIDENCE_SCOPE_NOT_AUTHORIZED
secret_value_read_probe_compare_serialize_hash=FORBIDDEN
allowed_dependencies=R5_EXACT_PYTHON_RUNTIME_CLOSURE_UNCHANGED
allowed_actions=VERIFY_R3_R4_R5_AND_CURRENT_11_IDENTITIES|SYNC_EXACT_NINE_REQUEST_PLUS_BASELINE_MANIFEST|REPIN_APPROVAL_PRE_META_BASELINE_IDENTITY_ONLY|RUN_R5_GATE_C_SCENARIOS_UNDER_R6_EVIDENCE_MODEL|BUILD_AND_FREEZE_FIXED_PRE_RUN_EXPECTED_SUBJECT_ALLOWLIST|PIN_EXPECTED_SCHEMA_AND_RAW_IDENTITY_IN_TOP_LEVEL_OWNER|EXTERNALLY_RECALCULATE_TOP_LEVEL_PIN_OWNER_IDENTITY|VERIFY_NO_PIN_CORE_IN_EXPECTED_OBSERVED_SET|COLLECT_CHILD_OWNED_POST_RUN_OBSERVED_SUBJECT_LEDGER|ENUMERATE_SELF_PID_LOADED_MODULES_AT_FIXED_CHECKPOINTS_READ_ONLY|FREEZE_AND_VERIFY_WIN64_TOOLHELP_CTYPES_ABI_ERROR_CLEANUP|RESOLVE_FIXED_KERNEL32_TOOLHELP_SYMBOLS_BY_CTYPES_NAMED_ATTRIBUTE|VERIFY_CHECKPOINT_KEYED_MODULE_ENTRIES_AND_EXCLUDE_SNAPSHOT_ORDINAL|VERIFY_CANONICAL_MODULE_PATH_RAW_BYTES_HASH_BASE_INDEPENDENT|COUNT_POST_SEAL_PYTHON_IMPORT_OR_CTYPES_LOAD_EVENTS|VERIFY_EXPECTED_OBSERVED_EXACT_SET_DIFF_ZERO|RUN_PYTHON_VISIBLE_ATTEMPT_GUARDS|RUN_SOURCE_AST_IMPORT_CTYPES_PE_CLOSED_ALLOWLIST|RUN_ANTI_FORGERY|SYNC_TRACKING_AFTER_PASS
forbidden_scope=OBSERVED_LEDGER_AS_EXPECTED_INPUT|PRIOR_OBSERVED_AUTOGENERATES_EXPECTED|EXPECTED_MUTATION_AFTER_CHILD_CREATION|TOP_LEVEL_PIN_OWNER_IN_SUBJECT_PROJECTION|NO_PIN_CORE_HOLDS_EXPECTED_OR_SCHEMA_PIN|OBSERVED_CLAIMS_TOP_LEVEL_IDENTITY|LOADED_MODULE_CHECKPOINT_ID_MISSING_UNKNOWN_OR_WRONG|SNAPSHOT_ORDINAL_IN_STABLE_PROJECTION|CROSS_CHECKPOINT_SAME_PATH_TREATED_AS_DUPLICATE|MODULE_ENUMERATION_OUTSIDE_EVIDENCE_CORE|MODULE_ENUMERATION_BEFORE_GUARD|MODULE_ENUMERATION_IN_POLICY_LOADER_OR_APPLICATION_RUNTIME|MODULE_ENUMERATION_OTHER_PID|NON_MODULE_TOOLHELP_SNAPSHOT_FLAG|WRONG_TOOLHELP_ARGTYPES_OR_RESTYPE|WRONG_DWORD_BOOL_HANDLE_WIDTH|WRONG_MODULEENTRY32W_LAYOUT_SIZE_ALIGNMENT_OFFSET_ARRAY_OR_DWSIZE|WRONG_INVALID_HANDLE_OR_LAST_ERROR_OR_FIRST_NEXT_OR_CLOSE_ORACLE|TOOLHELP_DOUBLE_CLOSE_OR_HANDLE_LEAK|OPENPROCESS|PROCESS_MEMORY_READ_OR_WRITE|PROJECT_OR_EVIDENCE_SOURCE_EXPLICIT_LOADLIBRARY_CALL|PROJECT_OR_EVIDENCE_SOURCE_EXPLICIT_GETPROCADDRESS_CALL|DYNAMIC_FFI_LIBRARY_OR_SYMBOL_OR_ORDINAL|GETMODULEFILENAMEW|EVIDENCE_SOURCE_EXPLICIT_NATIVE_MODULE_LOAD_OR_INJECTION|MODULE_PATH_DEVICE_UNC_REDIRECTED_REPARSE_OR_SHADOW|CLAIM_POST_SEAL_NATIVE_EXTENSION_DELAY_LOAD_ZERO|CLAIM_POST_SEAL_ARBITRARY_NATIVE_NEW_MODULE_ZERO|CLAIM_NATIVE_OS_WINSOCK_ZERO|CLAIM_WINDOWS_NAMED_PIPE_ZERO|CLAIM_PRIVATE_PYTHON_STATE_MUTATION_DETECTED|SECRET_VALUE_READ_OR_PROBE_OR_COMPARE_OR_SERIALIZE_OR_HASH|ELEVATED_ETW|KERNEL_FILE_PROVIDER|KERNEL_PROCESS_PROVIDER|OS_HOOK|DRIVER|FIREWALL_CHANGE|AUDIT_POLICY_CHANGE|STARTUP_TCP|STARTUP_UDP|STARTUP_DNS|STARTUP_TLS|STARTUP_HTTP|STARTUP_SOCKET|WINDOWS_NAMED_PIPE_USE|PROVIDER|BUSINESS_NETWORK|DATABASE|REDIS|BROKER|CELERY_CONNECTION|REAL_ENV|SECRET_VALUES|REAL_DATA|DOCKER|DEPLOYMENT|CANARY|PRODUCTION_RELEASE|GLOBAL_INSTALL|COMMIT|PUSH|PR
authorized_scope=evidence_boundary_successor_only|exact_eleven_file_atomic_sync|r5_gate_c_continuation_under_trusted_locked_subject|top_level_pin_owner_external_identity_review_and_projection_exclusion|no_pin_core_expected_observed_projection|child_owned_observed_ledger|evidence_core_only_readonly_self_pid_toolhelp_module_enumeration|win64_toolhelp_ctypes_abi_error_cleanup_oracle|checkpoint_keyed_module_projection|post_seal_python_import_or_ctypes_load_event_zero_only|pre_run_expected_post_run_observed_exact_set_attestation|python_visible_zero_attempt_evidence|native_os_named_pipe_and_post_seal_native_new_module_not_claimed
日期=<YYYY-MM-DD>
证据链接=<本 Codex task 的批准消息>
备注=只批准 STARTUP-D-005 证据模型收窄及其十一文件原子同步；启动行为禁令、R5 其他决策和全部非授权边界不变；native OS WinSock 与 Windows named-pipe attempts 必须写 NOT_CLAIMED，绝不得冒充 0。
```

有效 `APPROVED` 必须恰好选择 `STARTUP-D-005-R6`，preserved/superseded 集合与顺序逐字匹配，九角色绑定同一 snapshot、R5 base 和十一文件 pre state。任何角色缺失/拒绝、把 `NOT_CLAIMED` 改成零、放宽启动行为、授权 elevation/ETW/Provider/DB/部署/production 或修改 R5 其他决策时，整体保持 `NOT APPROVED`。

---

## 6. 失败、回滚与证据用语

### 6.1 失败关闭

- Gate A 失败：候选不可签，不同步十一文件。
- Gate B 失败：回滚全部十一文件，不进入 R6 Gate C。
- expected 未在 child 前固定/pin、由 observed 派生或在 child/run 后被修改：pre-run 即失败；若 child 尚未创建则禁止创建，若在 post-run 发现则不得输出 PASS。
- top-level pin owner 被纳入 expected/observed subject projection、无 pin core 持有 expected/Schema pin，或 observed 声称 top-level identity：职责边界失效，不得创建 child 或输出 PASS。
- observed grammar/identity/timestamp 失败或 expected/observed 双向 exact-set diff 非零：不得输出 PASS。
- module enumeration 不在 observed child evidence core/guard 后执行，Win64 ABI/layout/argtypes/restype/dwSize/library/symbol/flag/PID/checkpoint/error/cleanup oracle 不匹配，显式调用 `LoadLibrary*`/`GetProcAddress`，或出现 `OpenProcess`/other PID/process-memory/module-injection：立即失败关闭。
- 任一 loaded-module `checkpoint_id` 缺失/非法/错序、composite key missing/extra/mismatch/duplicate、连续 snapshot 漂移、snapshot ordinal 进入 stable projection、post-seal Python import/ctypes load event，或 canonical local path/on-disk case/reparse/raw bytes/hash 不匹配：observed evidence 无效，不得输出 PASS。同一路径跨两个合法 checkpoint 各一条不得误判 duplicate。
- native extension 内部 delay-load 或任意 native new-module 不在 post-seal Python/ctypes oracle 覆盖内；任何报告将其写成 `0/PASS/ZERO/NONE` 而非 `NOT_CLAIMED` 时，证据无效。
- subject identity/clean environment/guard/allowlist/anti-forgery 任一失败：application child 不得输出 PASS；`BASE-004` 继续 `partial`。
- Python-visible 任一 socket/DNS/local-socket attempt 非零或 hostname read 不等于 `1`：立即失败关闭。
- native OS/NamedPipe marker 缺失、被写成数值或被推断为零：证据无效。
- cleanup 失败、unexpected child/import/image/output、test collection 漂移：证据无效，不得用重试掩盖首个失败。

R6 不要求回滚已经批准的 R3/R4/R5 artifacts 或已通过的 R5 Gate B；失败只阻止 R6 sync/acceptance 和未通过的 Gate C evidence。

### 6.2 唯一允许的成功表述

R6 Gate C 的成功表述必须包含证据边界：

`CR-011-R6 local offline application-startup Policy adoption PASS within trusted clean-launcher and exact locked-subject boundary; Python-visible socket/DNS/local-socket attempts 0; local hostname reads 1; native OS WinSock attempts NOT_CLAIMED; Windows named-pipe attempts NOT_CLAIMED.`

禁止使用无限定的 `zero-socket startup evidence`，也禁止表述为 OS-level zero network、native isolated、sandboxed、Provider available、AI runtime complete、durable、business-ready、Compose-ready、production-ready、AC passed 或 P0 complete。

---

## 7. 非授权边界与状态不升级

R6 不授权且不得改变以下状态：

- Provider/业务网络、真实 Chat/Embedding、费用/性能、SendPermit/AdoptPermit；
- PostgreSQL、migration、Repository、durable Sink、Outbox、Redis、Broker、Celery connection、Worker 消费或恢复；
- 真实 `.env`、secret value、真实 endpoint/CIDR/Profile/model/Tokenizer/pricing/capacity/业务数据；
- Node Ajv runtime promotion、其他平台 closure、全局安装或依赖升级；
- OS telemetry elevation、Kernel-File/Kernel-Process、driver/hook、系统审计/防火墙/服务配置；
- Docker/Compose runtime、部署、canary、production migration/release；
- commit、push、PR、remote write。

即使 R6 Gate C PASS，`BASE-004` 仍按 R5 `STARTUP-D-006` 和全局 DoD 独立裁定；当前必须保持 `partial`。`AI-001`、AI-005、BASE-005/006、TEST-001、P0 matrix、AC-015/016、部署、production 和 R4 persistent Gate C 不得自动升级。现有 P0 `2 implemented / 30 partial / 54 planned`、gap `47/20/67`、DB `13/57` 只可在独立事实变化后更新，R6 本身不改变这些计数。

---

## 8. R6 decision snapshot 算法与生命周期

1. 严格 UTF-8 读取本文件；拒绝 BOM、非法序列、替换字符、NUL 或其他编码。
2. 将 CRLF 与孤立 CR 规范化为 LF，不做 Unicode normalization。
3. marker 必须是整行精确 `## 9. 当前状态`，全文件恰好一次；不得用普通 substring search 命中正文反引号中的相同文本。
4. decision preimage 取 marker 行首之前全部内容；删除末尾所有 LF，再追加恰好一个 LF。
5. 对无 BOM UTF-8 bytes 计算 SHA-256，小写 64 位 hex；不裁剪空格、不改制表符、不重排 Markdown。
6. snapshot record 必须同时绑定 R3/R4/R5 identities、dependency lock、§2 单一 successor decision、§4.1 十一文件 pre identities、§5 approval schema 和 §7 非授权边界。
7. 第 1～8 节不得包含 R6 自身 snapshot hash、Request post identity、manifest post identity、re-pin post identity，或 Gate C expected/observed/Schema/top-level-pin-owner 的动态 raw identity；top-level raw identity 只由独立 reviewer 外部复算且不进入 subject projection，这些动态值只进入 §9 或外部 tracking，避免自引用。
8. 首条有效 approval、Gate B sync authorization 或下游消费事实产生前，第 1～8 节可修订；每次修订必须废弃旧 unsigned hash并全量复审。
9. 任一有效 approval 或下游消费事实产生后，第 1～8 节任何 byte 变化必须提升至少 `CR-011-R7` 并重置九角色审批。
10. 第 9 节动态状态更新不改变 decision snapshot；不得把动态 evidence 反向解释为规范条款。
11. snapshot 只建立可签署对象，不等于批准；有效九角色批准前不得同步十一文件，Gate B PASS 前不得执行 R6 Gate C。

---

## 9. 当前状态

本节位于 decision snapshot 之外，只记录动态生命周期与证据；不得覆盖第 1～8 节。

| 项目 | 状态 |
|---|---|
| CR revision | `CR-011-R6` |
| lifecycle | `APPROVED / ACTIVE CONTRACT / GATE A PASS / GATE B PASS / GATE C AUTHORIZED / BLOCKED BEFORE RUN / NOT RUN` |
| R5 active base | `BOUND；raw 53927/089cbb5c88659dc7076df191af6d4c84492aa30e081878c1bfc232596a8407a7；decision 50926/fb6aa225dae67a6068e84935e4a77affe84b143de5de2908b555089f9334c5ae；GATE C BLOCKED` |
| R6 semantic delta | `STARTUP-D-005 EVIDENCE MODEL ONLY；APPLICATION/RUNTIME BEHAVIOR AND POLICY IMPLEMENTATION DELTAS ZERO；EVIDENCE TOOLING DELTA NONZERO AND CLOSED TO TOP-LEVEL PIN OWNER/NO-PIN CORE/FIXED PRE-RUN EXPECTED/CHILD-OWNED POST-RUN OBSERVED/CHECKPOINT-KEYED MODULE PROJECTION/WIN64 TOOLHELP ABI-ERROR-CLEANUP/POST-SEAL PYTHON-CTYPES ORACLE/GUARD/ALLOWLIST/ANTI-FORGERY/RUNNER` |
| Gate B eleven pre identities | `11/11 MATCHED BEFORE ATOMIC SYNC；2026-08-10` |
| Windows OS telemetry feasibility | `NO-GO FOR COMPLETE NON-ELEVATED NATIVE WIN32/NAMED-PIPE CLAIM；TEMP SESSIONS/FILES CLEANED` |
| R6 Gate A self-review | `PASS AFTER REOPEN_R6_FIX_5；POWERSHELL EXPLICIT SCRIPTBLOCK + INDEPENDENT PYTHON -I -S FULL RECALC；R3 RECOVERED RAW/CANONICAL、R4/R5 SNAPSHOTS、R5 LIVE RAW、15/15 LEAVES、LOCK、11/11 PRE IDENTITIES、ENCODING、CHECKPOINT-ID COMPOSITE KEY/ORDER/PROJECTION、SNAPSHOT ORDINAL EXCLUSION、POST-SEAL PYTHON-CTYPES ZERO/NATIVE NEW-MODULE NOT_CLAIMED、WIN64 TOOLHELP ABI/LAYOUT/ERROR/CLEANUP、ANTI-FORGERY ALL MATCH；NO NETWORK` |
| independent Gate A review | `PASS；TWO INDEPENDENT READ-ONLY REVIEWS；NO HIGH/MEDIUM BLOCKER；IDENTITIES/SCHEMA/CHECKPOINT PROJECTION/WIN64 TOOLHELP ABI/ERROR/CLEANUP/OWNERSHIP DAG/NON-AUTHORIZED BOUNDARIES MATCH` |
| R6 decision preimage / snapshot | `60493/113568b8afe8d8d2c02508285cef340422e93eae39d17cac53c46bd44fd03815；FROZEN FOR NINE-ROLE APPROVAL` |
| approval evidence | `VALID；104/104 FIELDS；NINE REQUIRED ROLES 9/9；DECISION SNAPSHOT MATCH；本 Codex task attachment e7fc59b5-4803-44d9-98d7-454cec36cda7/pasted-text.txt` |
| required approvals | `9/9；APPROVED` |
| R6 Gate B eleven-file sync | `PASS；ATOMIC POST SET 11/11；REQUEST REVERSE 9/9；MANIFEST REVERSE 1/1；PRE-META TWO-LITERAL REVERSE 1/1；UTF-8/LF/NO-BOM PASS` |
| Gate B repository verification | `PASS；verify-baseline EXIT 0；verify-test-assets EXIT 0；approval_pre_meta unit 21/21 EXIT 0；approval_pre_meta CLI EXIT 0` |
| R6 Gate C trusted locked-subject startup evidence | `AUTHORIZED / BLOCKED BEFORE RUN / NOT RUN；EXPECTED_ALLOWLIST_NOT_STATICALLY_MATERIALIZED；STATIC SOURCE/METADATA/PE ANALYSIS CANNOT DETERMINE EXACT CHECKPOINT MEMBERSHIP；OBSERVED-DERIVED EXPECTED FORBIDDEN` |
| native OS WinSock / Windows named-pipe attempts | `NOT_CLAIMED` |
| BASE-004 / P0 / AC / Provider / DB / Redis / Broker / deploy / production | `UNCHANGED；NOT UPGRADED` |
| commit / push / PR | `NOT AUTHORIZED / NOT RUN` |

### 9.1 Gate B post identities

| path | raw bytes | raw SHA-256 |
|---|---:|---|
| `Request/FinAudit_Agent_项目需求规格说明书_V1.3_核查优化版.md` | 130357 | `b0f7b4422f3bd32d8fb0b3ace4417a63da3a48b9b931c3fbd48239399eb3c511` |
| `Request/FinAudit_Agent_系统架构设计说明书_V1.0.md` | 92246 | `061f4a2fdce8e813abdc904d7657cd70bfee46ff46e804725d4eb462e9fa2a57` |
| `Request/FinAudit_Agent_数据库设计说明书_V1.0.md` | 116615 | `8f4878fe396910cc6176ddc044b4e23a1d81aa68035e2896a254bbcc171e29df` |
| `Request/FinAudit_Agent_API接口设计说明书_V1.0.md` | 328953 | `4659754f5939f51316fa41ddc94b4a98fb57933df3f04f7092aef97e3ad2c2db` |
| `Request/FinAudit_Agent_页面与交互设计说明书_V1.0.md` | 84259 | `0b9c5bfb4f5de94758aa54366ef82b7a1665487717bb9f57580f8809143b596b` |
| `Request/FinAudit_Agent_AI与RAG及Prompt详细设计说明书_V1.0.md` | 52541 | `494f98ea9ccb39d1621e257d8473ee1848dc5bc96ea7a636a26c510c75d7fe4a` |
| `Request/FinAudit_Agent_测试与验收方案_V1.0.md` | 51649 | `43631352a945ce56cabaeafee4d6090def7c9ca0256ecd5a135bfc2b9f52fa7d` |
| `Request/FinAudit_Agent_部署与运维说明书_V1.0.md` | 55466 | `78023778b650260b59232ab1e77a040b512bd12b0ee8a0f7dae29228b241d481` |
| `Request/FinAudit_Agent_项目开发任务分解与实施计划_V1.0.md` | 107675 | `52a07e78f5776196f2a6fc53d873b478c3f6e3d1dc1bb7a252076fa48c365d7a` |
| `docs/baseline-manifest.md` | 1675 | `9733e78cdecfbcd7b8842e6c624c773a75c2401d995108ac70cce6c9cdc1aa11` |
| `backend/app/approval_pre_meta.py` | 22193 | `f5ec3483e005902c4cea94ca428ffbaf71c6a3624d4ef0c77c81a7212e4fa881` |
