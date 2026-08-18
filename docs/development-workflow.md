# 开发工作流

## 本地初始化

在仓库根目录运行：

```powershell
.\scripts\setup-git-governance.ps1
```

脚本会在缺少 `.git` 时以 `main` 初始化空仓库，并幂等设置本地 `commit.template=.gitmessage` 与 `core.hooksPath=.githooks`。对已有历史的仓库不会切换分支、创建提交、标签或 remote。

## 分支模型

- `main`：已验证、可发布的稳定基线。
- `develop`：下一个发布版本的集成分支。
- `feature/<task-id>-<slug>`：单个开发计划任务，例如 `feature/base-002-backend-scaffold`。
- `release/<version>`：发布候选稳定化。
- `hotfix/<issue>`：生产阻断缺陷修复。

截至 2026-08-18，`origin` 已配置为 `https://github.com/EVERLASTING7/FinAudit_Agent.git`，且 `release/local-mvp-0.1.0` 已使用普通 push 发布。远程当前只有该发布分支并将其作为默认分支；实际核验结果为 `protected=false`、仓库 Rulesets 为 0，`main`/`develop` 尚不存在。因此远程治理仍为 `partial`。后续建立稳定分支后，至少为稳定默认分支和 `develop` 启用：禁止 Force Push、必须通过 PR、至少一次独立 Review、必须通过相关测试和静态检查。

以下离线命令只在内存中验证上述项目工作流投影的固定 synthetic fixture 与封闭负例：

```powershell
.\scripts\test-verify-remote-branch-protection-fixture.ps1
```

底层验证器只接受固定 `--stdin` 有界字节流，不读取 fixture 路径。成功必须仍逐字输出 `BRANCH_PROTECTION_EVIDENCE_SCOPE=SYNTHETIC_OFFLINE_ONLY`、`BASELINE_TASK_STATUS=PARTIAL` 与 `REMOTE_BRANCH_PROTECTION=NOT_RUN`。它不读取 GitHub/GitLab、不冻结 provider/repository/check context，也不构成 Request-exact、远程配置、分支保护演练或 `BASE-001` 完成证据。

本地分支和 Git 配置门禁：

```powershell
.\scripts\verify-git-governance.ps1 -BranchName 'feature/base-001-governance'
.\scripts\verify-baseline.ps1
```

分支名必须同时符合上述项目模型与 `git check-ref-format --branch`。Baseline 校验会把 `RootPath`、仓库根和 `.git` 绑定为同一目标，拒绝 `GIT_DIR`、`GIT_WORK_TREE`、`GIT_CONFIG_*` 等进程级重定向；remote 只接受无凭据的 HTTPS、`ssh://git@...` 或严格 `git@host:path` 形式，并同时检查原始配置记录与 Git 解析后的 fetch/push URL。控制字符、百分号编码、remote-helper、本地/UNC 路径、明文协议、多值歧义和不安全 `insteadOf/pushInsteadOf` 重写均失败关闭。该检查只读取本地 Git 配置，不 fetch/push、不访问托管平台；`BASELINE_LOCAL_VERIFY=PASS` 不能表示远程分支保护已配置或 `BASE-001` 已完成。

## 提交

使用 Conventional Commits：

```text
feat(api): add file upload validation
fix(audit): preserve execution snapshot on retry
docs(base): record baseline conflict
test(auth): cover refresh token replay
```

最小格式为 `type(scope): summary`，scope 可省略，破坏性变化可在冒号前使用 `!`。Commit hook 同时允许 Git 自动生成的 merge、revert、fixup、squash 和 amend 主题，不实现额外的自定义语法解析。每次提交只包含一个可解释范围；提交前运行与任务对应的最小检查，并在提交模板的 `Verification` 中记录实际命令。

## 版本标签

稳定版本标签使用 `vMAJOR.MINOR.PATCH`，例如 `v0.1.0`。创建标签前执行校验；校验器只检查名称，不创建标签，也不修改历史：

```powershell
.\scripts\verify-git-governance.ps1 -VersionTag 'v0.1.0'
```

## Pull Request 检查

1. 关联开发计划任务 ID、需求条目和 AC。
2. 说明用户可感知变化、兼容性和回滚方式。
3. API、表、状态机或页面契约变化已同步设计或附批准 CR。
4. 没有真实密钥、生产数据、敏感正文或不必要日志。
5. 提供实际测试命令、退出码和关键证据。
6. P1/P2 没有被无意带入 P0。
