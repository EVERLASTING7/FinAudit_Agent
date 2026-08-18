# CR-024：全局应用入口改为 HTTP

- 状态：APPROVED
- 批准人：BOSS（YHBX）
- 批准日期：2026-08-17
- 适用范围：所有环境的内置应用入口

## 决定

- 内置 Nginx 只提供 HTTP，入口为 `http://localhost:8443`；当前 Local MVP 继续只绑定 `127.0.0.1`。
- 本项目不再生成、要求或挂载 TLS 证书/私钥，也不再使用本地 TLS 浏览器中继。
- `AUTH_PUBLIC_ORIGIN` 与 CORS 默认使用 HTTP；production 配置允许 HTTP，不再因缺少 HTTPS 拒绝启动。
- Refresh Cookie 继续固定 `HttpOnly`、`SameSite=Strict`、Auth Path 和无 Domain；`Secure` 严格跟随配置后的公开 Origin，HTTP 为 false，若未来由外部设施终止 TLS 并显式配置 HTTPS 则为 true。
- Origin 精确校验、CSRF 防护、Token 会话、权限、日志脱敏和 loopback-only 当前暴露边界不变。

## 风险与发布边界

BOSS 明确要求该策略全局生效。HTTP 不提供传输机密性或服务器身份认证；在局域网或公网传输密码、Token、Cookie 和业务数据会遭受窃听或中间人攻击。

因此当前实现只允许作为 BOSS 本机 Local MVP 使用。任何局域网或公网发布都必须先形成新的显式安全决定，恢复 TLS 或在受信任反向代理终止 TLS，并重新运行 DAST、Cookie、Origin、HSTS/证书和发布验收；在此之前不得把 HTTP Profile 标记为 production-ready。

## 验证

- `http://localhost:8443` 返回 Frontend，`/health/dependencies` 为 `ok`。
- Docker 主机绑定仍只有 `127.0.0.1:8443`。
- Nginx 配置不含 `listen ... ssl`、证书或私钥引用，运行时 Secret 集不再生成 TLS 文件。
- HTTP 登录设置无 `Secure` 的 HttpOnly/SameSite=Strict Refresh Cookie，refresh/logout 可用；显式 HTTPS Origin 的单元兼容性仍设置 `Secure`。
- 文件上传、安全、恢复与浏览器门禁改用 HTTP 后重新通过。
