# 内部 Metrics 运行手册

## 适用范围

当前实现只提供受保护的 Backend Prometheus 文本端点，不包含 Prometheus/Grafana 部署、告警、SLO、保留期或 production 网络放行。

## 配置

- `METRICS_ENABLED=true` 时注册精确路径 `/metrics`；为 `false` 时端点不存在。
- `METRICS_INTERNAL_TOKEN` 必须由运行时 Secret 注入，不得写入仓库、URL、query 参数或用户 JWT。
- Nginx 只代理精确 `location = /metrics`，不会把该路径回退到 SPA。

本地受管 Compose 会在运行目录创建 metrics token 文件并只读挂载。仓库 `.env.example` 中的 `CHANGE_ME` 只是不可运行占位符。

## 采集检查

在已由受信任环境把 token 注入当前 PowerShell 进程后执行：

```powershell
$headers = @{ Authorization = "Bearer $env:METRICS_INTERNAL_TOKEN" }
Invoke-WebRequest `
  -Uri 'http://127.0.0.1:8443/metrics' `
  -Headers $headers `
  -UseBasicParsing
```

不得把真实 token 直接写进命令文本、脚本、截图或测试证据。401 表示缺少/拒绝独立凭据；404 表示 metrics 未启用或未注册。成功响应必须带 `Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。

`scripts/verify-local-stack.ps1 -SecurityBaseline` 会在可丢弃的本地安全栈中使用运行时受管凭据执行 401/200 双路径检查，并验证固定低基数指标、响应头和 1 MiB 响应上限；脚本只输出 PASS 标记，不输出凭据或指标正文。该门禁证明本地采集入口可用，不等于已有长期采集器、通知通道或 SLO。

对现有受管栈做非破坏性巡检时，使用 `scripts/verify-local-stack.ps1 -ProjectName finaudit-local -OperationsReadiness`；它还会同步核对长期容器的日志轮转和 restart policy。

## 指标边界

当前允许：

- build/version 信息；
- 进程 uptime；
- in-flight HTTP 请求；
- 按固定 method、request group、status class 聚合的请求计数；
- 固定桶 HTTP duration histogram。

禁止把原始路径参数、组织、用户、Trace、业务 ID、文件名、税号、Prompt、正文、模型响应或错误文本放入标签。

## Production 停止边界

在确定下列事实前，不得把 `/metrics` 暴露给公网或宣称监控完成：

- 采集器网络和服务身份；
- Secret Manager、轮换和最小权限；
- scrape interval、超时、容量和保留期；
- 告警规则、责任人、通知通道和处置 runbook；
- SLI/SLO 定义及误报/漏报验证；
- 指标与日志脱敏复核。

以上仍为 `DEP-006 partial / production NOT_RUN`。
