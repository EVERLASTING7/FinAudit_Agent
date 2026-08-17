# FinAudit Agent 部署与运维说明书 V1.0

## 文档信息

| 项目 | 内容 |
|---|---|
| 项目名称 | FinAudit Agent——企业财务文档智能审核与风险分析平台 |
| 文档名称 | 部署与运维说明书 |
| 文档版本 | V1.0 |
| 编制日期 | 2026-08-05 |
| 需求基线 | 《FinAudit Agent 项目需求规格说明书 V1.3》 |
| 架构基线 | 《FinAudit Agent 系统架构设计说明书 V1.0》 |
| 数据库基线 | 《FinAudit Agent 数据库设计说明书 V1.0》 |
| API 基线 | 《FinAudit Agent API 接口设计说明书 V1.0》 |
| 页面基线 | 《FinAudit Agent 页面与交互设计说明书 V1.0》 |
| 测试基线 | 《FinAudit Agent 测试与验收方案 V1.0》 |
| 适用范围 | P0 Docker Compose 部署、配置、启动、健康检查、日志、备份恢复、故障处理；P1 可观测性仅预留 |
| 目标读者 | 运维工程师、后端工程师、AI 工程师、DBA、安全工程师、测试工程师、项目负责人 |
| 核心原则 | Nginx 单一入口、数据端口不外露、业务事实持久化、派生数据可重建、配置不入库不入 Git、健康可检测、故障可降级、恢复可演练 |

## 修订记录

| 版本 | 日期 | 说明 | 状态 |
|---|---|---|---|
| V1.0 | 2026-08-05 | 根据六份设计基线形成 P0 部署与运维详细说明 | 当前版本 |
| CR-001-R2 / CR-002-R4 | 2026-08-07 | 同步 57 表迁移/bootstrap、扫描 fail-closed、数据库分块配置，以及 AI Policy、预算、出站安全和分层放行合同 | 已批准 contract；Provider 网络与 production 未放行 |
| CR-012-R3 | 2026-08-09 | 同步 `20260807_006` 三表迁移、锁定降级和失败恢复边界 | 已批准 contract；不构成 production migration 放行 |
| CR-004-R2 | 2026-08-09 | approved contract scope：同步 queue/task 路由、publish retry、数据库时钟/Lease、Outbox dead-letter 与 `20260807_007` 回退边界 | 已批准 contract；Broker/网络、部署和 production 未授权 |
| CR-011-R4 | 2026-08-09 | approved contract scope：同步 Policy/机器制品缺失或漂移 fail-closed、零 socket Gate B 与环境非授权边界 | 已批准 contract；`AI_PROVIDER_CALLS_ENABLED=false`，真实 endpoint/CIDR/secret、网络、部署和 production 未授权 |
| CR-011-R5 | 2026-08-10 | approved contract-offline startup scope：同步本地只读 Policy/package resource 的 pre-socket adoption 边界 | 已批准 contract；calls disabled，production 固定拒绝，真实 endpoint/CIDR/secret、部署和 production 未授权 |
| CR-011-R6 | 2026-08-10 | approved startup evidence-boundary successor：同步本地分层 evidence 边界 | 已批准 contract；不部署、不提升权限，未来 elevated ETW 必须另行 CR |
| CR-003-R3 | 2026-08-11 | approved privileged-auth current-baseline successor：同步 008 的本地/专用可丢弃合成 PostgreSQL 16 Gate 边界 | 已批准 contract；Gate B 不连库，Gate C 固定 lock timeout/非空 downgrade/catalog 恢复；部署与 production 未授权 |

---

## 已批准 CR-004-R2 可靠性运维边界

- 七个逻辑队列固定为 `document/extraction/knowledge/evaluation/audit/report/maintenance`；Celery task 名由 `app.workers.tasks.<logical_queue>.execute_job` 唯一生成，物理 queue/routing key 只由已验证 Settings 映射。Worker 启动配置必须证明实际消费队列，callable 不得读取不存在的 delivery queue 字段。
- Dispatcher 只发布 JSON/UTF-8 Celery protocol v2，显式 `retry=False`，全局 `task_publish_retry=False`；Job task 禁止 Celery 自重试。Broker 消息只是 wake-up，Worker 必须回查 PostgreSQL Job/Outbox/Registry identity 后才可 claim。
- Job/Step/Outbox 转换只使用每事务一次的 PostgreSQL `clock_timestamp()`；`database_now >= lease_expires_at` 后旧 Worker 不得写，recovery 仅在再加 15 秒 grace 后允许。Outbox failed 到期与 processing reaper 都采用数据库时钟等值边界。
- 第八次可恢复发送失败或第八次 processing lease 超时直接 dead-letter，写 `DELIVERY_ATTEMPTS_EXHAUSTED`，不得产生第九次。Broker confirm/timeout 等未知结果保守为 `JOB_DISPATCH_OUTCOME_UNKNOWN`；日志、表和响应不得保存底层自由文本、连接信息或原始异常。
- `20260807_007` 只允许本地或专用可丢弃合成 PostgreSQL 16 演练。downgrade 前需停止生产者并排空可处理事件；数据库事务设置 `lock_timeout='5s'`，按 Job→Step→Outbox 加 `ACCESS EXCLUSIVE` 锁，`55P03`/`55000` 失败关闭，通过后无 `CASCADE` 地删除三表与四函数。
- 当前不授权生产 Registry/Handler、Redis/Broker socket、真实数据、部署、canary、production migration 或 production 回退；上述跨系统步骤只是后续 Gate，不能因空表测试通过而执行。

---

## 已批准 CR-011-R4 contract/offline 运维投影

- `AI_PROVIDER_CALLS_ENABLED=false` 保持强制值；Policy、Schema、companion、registry、manifest 任一缺失、额外、identity 漂移或组合校验失败时启动 fail closed。
- Gate B 只读取获批机器制品和合成 Policy/Event/Resolver 输入，不读取真实 `.env`、secret 或业务正文；不得打开数值 loopback、hostname/DNS、Unix domain 或其他本地/远程 socket，也不得 sleep。
- 本轮不写真实 endpoint、CIDR、Profile、Tokenizer、pricing、quota、capacity、Token 或 API Key，不启动 Provider/vLLM、Redis/Broker、数据库、Docker/Compose 或任何本地服务。
- fixed-test、canary、部署、production migration 和 production 放行继续使用独立环境审批；contract/offline PASS 不构成环境就绪证明。

## 已批准 CR-011-R5 本地启动运维投影

- `AI_PROVIDER_CALLS_ENABLED=false` 保持强制值；仅允许从 fixed local physical drive 的只读 Policy 绝对路径和固定 package resources 完成 pre-socket 校验，production 环境固定拒绝。
- startup 阶段必须 zero-socket/zero-DNS；不得写入真实 endpoint、CIDR、secret、Profile 或业务数据，不启动 Provider、数据库、Redis/Broker、Docker/Compose 或本地服务。
- 本投影不授权部署、canary、production migration 或 production 放行。

## 已批准 CR-011-R6 startup evidence-boundary 运维投影

- 不部署、不提升权限；未来 elevated ETW 必须另行 CR。

## 已批准 CR-003-R3 特权授权 current-baseline 运维投影

本节精确绑定 R1 24270/cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045、R2 35977/7a69b8555d422a7c2bee9d74da7030b8170692c934d83c12dd722c15c85c8363 与 R3 29321/35b1cdd758128afa485f91e34c5ef0dcfd95c4a648906e488099f68ff792e68c effective contract；R2 仍为 0/9 且未同步；与本文件中尚未同步的旧说明冲突时，以本节及 CR-003-R3 exact effective contract 为准。

- 008 Gate C 仅可使用本地或专用可丢弃的合成 PostgreSQL 16，并固定 lock timeout、非空 downgrade 失败与 catalog 恢复检查。
- Gate B 不连库；真实环境、真实数据、网络扩张、部署、canary 与 production 均不授权。

---

# 1. 文档目的与范围

## 1.1 目的

本文档明确 FinAudit Agent P0 的：

1. Docker Compose 文件组织和服务职责。
2. edge、app、data 网络和端口暴露策略。
3. `.env` 配置和密钥管理。
4. PostgreSQL 初始化、迁移、种子和恢复。
5. MinIO Bucket、对象生命周期和安全访问。
6. Redis、Celery 队列、锁和任务恢复。
7. Qdrant Collection、快照、一致性和重建。
8. vLLM/OpenAI 兼容模型服务配置和降级。
9. Nginx HTTPS、SPA、API、上传限制、限流和安全头。
10. 健康检查、日志、Trace、最小指标、备份恢复和故障排查。
11. local、test、demo/staging 和 production 的配置差异。

## 1.2 P0 服务范围

P0 必需服务：

```text
frontend
backend
worker
postgresql
redis
minio
qdrant
nginx
```

可选 P0 Profile：

```text
vllm
```

P1 服务，不作为 P0 启动和验收前置条件：

```text
neo4j
langfuse
prometheus
grafana
reranker
otel-collector
```

## 1.3 部署结论

- 前后端分离。
- FastAPI Backend 只处理同步短事务和任务创建。
- Celery Worker 处理 OCR、解析、Markdown、分块、Embedding、索引、评测、审核和报告等长任务。
- PostgreSQL 为业务事实唯一来源。
- MinIO 保存原文件和制品。
- Redis 支持 Celery Broker、锁、限流和短期缓存，不作为永久事实来源。
- Qdrant 保存企业制度 Chunk 向量，是可重建派生存储。
- 外部只暴露 Nginx HTTP/HTTPS。
- 模型服务不得访问业务数据库。

---

# 2. 目录结构

```text
infra/
├── compose/
│   ├── docker-compose.yml
│   ├── docker-compose.local.yml
│   ├── docker-compose.test.yml
│   ├── docker-compose.demo.yml
│   └── profiles/
│       ├── vllm.yml
│       └── observability-p1.yml
├── nginx/
│   ├── nginx.conf
│   ├── conf.d/
│   │   └── finaudit.conf
│   ├── snippets/
│   │   ├── security-headers.conf
│   │   ├── proxy-common.conf
│   │   └── rate-limit.conf
│   └── certs/
├── postgres/
│   ├── init/
│   ├── backup/
│   └── restore/
├── minio/
│   ├── init-buckets.sh
│   ├── lifecycle/
│   └── policies/
├── qdrant/
│   ├── config.yaml
│   ├── snapshots/
│   └── rebuild/
├── redis/
│   └── redis.conf
├── scripts/
│   ├── bootstrap.sh
│   ├── migrate.sh
│   ├── health-check.sh
│   ├── backup-all.sh
│   ├── restore-all.sh
│   ├── rebuild-qdrant.sh
│   ├── rotate-logs.sh
│   └── smoke-test.sh
├── env/
│   └── .env.example
└── docs/
    ├── deployment-checklist.md
    ├── backup-restore-runbook.md
    └── incident-runbook.md
```

建议项目根目录：

```text
frontend/
backend/
infra/
docs/
scripts/
README.md
CHANGELOG.md
```

---

# 3. Docker Compose 架构

## 3.1 部署图

```mermaid
flowchart TB
    USER[用户浏览器]

    subgraph HOST[Docker Compose 主机]
        subgraph EDGE[edge_net]
            NGINX[Nginx]
            FRONTEND[Frontend]
            BACKEND_EDGE[Backend]
        end

        subgraph APP[app_net]
            BACKEND[Backend]
            WORKER[Celery Worker]
        end

        subgraph DATA[data_net]
            PG[(PostgreSQL)]
            REDIS[(Redis)]
            MINIO[(MinIO)]
            QDRANT[(Qdrant)]
        end

        subgraph OPTIONAL[可选 ai profile]
            VLLM[vLLM]
        end
    end

    USER --> NGINX
    NGINX --> FRONTEND
    NGINX --> BACKEND_EDGE
    BACKEND --> PG
    BACKEND --> REDIS
    BACKEND --> MINIO
    BACKEND --> QDRANT
    WORKER --> PG
    WORKER --> REDIS
    WORKER --> MINIO
    WORKER --> QDRANT
    BACKEND -.-> VLLM
    WORKER -.-> VLLM
```

## 3.2 服务职责

| 服务 | 职责 | 对外端口 |
|---|---|---|
| nginx | HTTPS、反代、限流、安全头、SPA 回退 | 80/443 |
| frontend | Vue 静态资源 | 不直接对外 |
| backend | `/api/v1`、健康、同步业务、任务创建 | 不直接对外 |
| worker | 异步任务 | 无 |
| postgresql | 业务事实和版本 | 不对外 |
| redis | Celery Broker、锁、限流、缓存 | 不对外 |
| minio | 原文件和制品 | 管理口受控，业务口不公网暴露 |
| qdrant | 制度向量 | 不对外 |
| vllm | OpenAI 兼容推理 | 仅 Backend/Worker 可访问 |

## 3.3 Compose 示例骨架

以下仅为结构示例，镜像版本、资源限制和密钥由实际环境确认：

```yaml
services:
  postgresql:
    image: postgres:${POSTGRES_IMAGE_TAG}
    env_file: .env
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [data_net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  redis:
    image: redis:${REDIS_IMAGE_TAG}
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - redis_data:/data
      - ./redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    networks: [data_net]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
    restart: unless-stopped

  minio:
    image: minio/minio:${MINIO_IMAGE_TAG}
    command: server /data --console-address ":9001"
    env_file: .env
    volumes:
      - minio_data:/data
    networks: [data_net]
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:${QDRANT_IMAGE_TAG}
    volumes:
      - qdrant_data:/qdrant/storage
    networks: [data_net]
    restart: unless-stopped

  backend:
    build: ../../backend
    env_file: .env
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    depends_on:
      postgresql:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [edge_net, app_net, data_net]
    restart: unless-stopped

  worker:
    build: ../../backend
    env_file: .env
    command: ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=INFO"]
    depends_on:
      postgresql:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [app_net, data_net]
    restart: unless-stopped

  frontend:
    build: ../../frontend
    networks: [edge_net]
    restart: unless-stopped

  nginx:
    image: nginx:${NGINX_IMAGE_TAG}
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    depends_on: [frontend, backend]
    networks: [edge_net]
    restart: unless-stopped

networks:
  edge_net:
  app_net:
    internal: true
  data_net:
    internal: true

volumes:
  postgres_data:
  redis_data:
  minio_data:
  qdrant_data:
```

实际 Compose 必须通过测试环境验证，不能将示例中的占位版本直接视为已确认版本。

---

# 4. 网络与端口安全

## 4.1 网络

| 网络 | 服务 |
|---|---|
| `edge_net` | nginx、frontend、backend |
| `app_net` | backend、worker |
| `data_net` | backend、worker、postgresql、redis、minio、qdrant |

## 4.2 端口规则

- PostgreSQL 不映射公网端口。
- Redis 不映射公网端口。
- Qdrant 不映射公网端口。
- MinIO API 不直接向公网提供；管理控制台仅在受控网络开放。
- vLLM 仅在 app/data 受控网络可达。
- `/metrics` 仅内网或受控采集账号访问。
- 外部访问统一进入 Nginx。

## 4.3 防火墙

- 仅允许 80/443 或指定演示端口。
- SSH 只允许管理来源 IP，优先使用密钥认证。
- 禁止将数据库、Redis、Qdrant、MinIO 管理端口暴露到 `0.0.0.0`。
- 生产环境禁用不必要的 Docker Remote API。

---

# 5. `.env` 配置

## 5.1 配置原则

- 仓库只提交 `.env.example`。
- `.env`、证书私钥、备份密钥和模型 API Key 不提交 Git。
- Backend 和 Worker 使用同一配置 Schema，但按服务校验所需项。
- 启动时缺少必需配置必须明确失败。
- 日志不得打印配置值中的密钥。

## 5.2 `.env.example` 建议

```dotenv
# General
APP_NAME=FinAudit Agent
APP_ENV=local
APP_VERSION=0.1.0
LOG_LEVEL=INFO
TIMEZONE=UTC
SECRET_KEY=CHANGE_ME
JWT_ACCESS_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=7

# HTTP
HTTP_PORT=80
HTTPS_PORT=443
API_PREFIX=/api/v1
CORS_ALLOWED_ORIGINS=http://localhost
MAX_UPLOAD_SIZE_MB=50
MAX_BATCH_FILE_COUNT=20

# PostgreSQL
POSTGRES_IMAGE_TAG=16
POSTGRES_HOST=postgresql
POSTGRES_PORT=5432
POSTGRES_DB=finaudit
POSTGRES_USER=finaudit
POSTGRES_PASSWORD=CHANGE_ME
DATABASE_URL=postgresql+psycopg://finaudit:CHANGE_ME@postgresql:5432/finaudit
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Redis / Celery
REDIS_IMAGE_TAG=7
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=CHANGE_ME
REDIS_URL=redis://:CHANGE_ME@redis:6379/0
CELERY_BROKER_URL=redis://:CHANGE_ME@redis:6379/0
CELERY_RESULT_BACKEND=redis://:CHANGE_ME@redis:6379/1
CELERY_TASK_TIME_LIMIT_SECONDS=1800
CELERY_TASK_SOFT_TIME_LIMIT_SECONDS=1700

# MinIO
MINIO_IMAGE_TAG=REPLACE_WITH_PINNED_VERSION
MINIO_ENDPOINT=http://minio:9000
MINIO_ROOT_USER=CHANGE_ME
MINIO_ROOT_PASSWORD=CHANGE_ME
MINIO_ACCESS_KEY=CHANGE_ME
MINIO_SECRET_KEY=CHANGE_ME
MINIO_SECURE=false
MINIO_BUCKET_QUARANTINE=quarantine
MINIO_BUCKET_ORIGINALS=originals
MINIO_BUCKET_ASSETS=assets
MINIO_BUCKET_PREVIEWS=previews
MINIO_BUCKET_REPORTS=reports
MINIO_BUCKET_EXPORTS=exports
MINIO_BUCKET_TEMP=temp
SIGNED_URL_EXPIRE_SECONDS=300

# Qdrant
QDRANT_IMAGE_TAG=REPLACE_WITH_PINNED_VERSION
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=CHANGE_ME_OPTIONAL
QDRANT_COLLECTION=REPLACE_AFTER_EMBEDDING_PROFILE_APPROVAL
QDRANT_VECTOR_SIZE=REPLACE_APPROVED_DIMENSION
QDRANT_DISTANCE=REPLACE_APPROVED_DISTANCE_METRIC

# AI contract gate: network remains disabled until environment approval
AI_POLICY_VERSION=1
AI_PROVIDER_CALLS_ENABLED=false
AI_PROVIDER_POLICY_SCHEMA_VERSION=1
AI_POLICY_FILE=/app/config/ai-policy-v1.json

# LLM / vLLM Profile candidates; these placeholders are not approved environment values
LLM_BASE_URL=REPLACE_APPROVED_VERSION_ROOT
LLM_API_KEY=CHANGE_ME
LLM_EXTRACTION_MODEL=REPLACE_MODEL_NAME
LLM_GENERATION_MODEL=REPLACE_MODEL_NAME
LLM_FALLBACK_MODEL=REPLACE_DISTINCT_FALLBACK_MODEL
LLM_CONNECT_TIMEOUT_SECONDS=5
LLM_MAX_ATTEMPTS_PER_GENERATION=3
LLM_MAX_SAME_TARGET_ATTEMPTS=2
AI_MAX_PROVIDER_ATTEMPTS_PER_OPERATION=6
AI_MAX_MODEL_REPAIRS=2
LLM_REPORT_DRAFT_USE_FALLBACK=false

# Per-operation hard deadlines
AI_CONTRACT_EXTRACTION_DEADLINE_SECONDS=120
AI_INVOICE_EXTRACTION_DEADLINE_SECONDS=60
AI_RISK_EXPLANATION_DEADLINE_SECONDS=60
AI_RAG_ANSWER_DEADLINE_SECONDS=90
AI_REPORT_DRAFT_DEADLINE_SECONDS=90
AI_EMBEDDING_DEADLINE_SECONDS=30

# Retry and breaker
AI_RETRY_BACKOFF_BASE_SECONDS=1
AI_RETRY_BACKOFF_MULTIPLIER=2
AI_RETRY_BACKOFF_MAX_SECONDS=30
AI_RETRY_JITTER_RATIO=0.2
AI_BREAKER_FAILURES=5
AI_BREAKER_WINDOW_SECONDS=60
AI_BREAKER_OPEN_SECONDS=30
AI_BREAKER_HALF_OPEN_PROBES=1

# Per-target rate-limit pools: concurrency/RPM/TPM/burst
AI_RAG_LIMITS=2/12/100000/2
AI_ASYNC_GENERATION_LIMITS=4/30/250000/4
AI_EMBEDDING_LIMITS=2/30/500000/2

# Outbound byte limits
AI_MAX_REQUEST_BYTES=4194304
AI_MAX_RESPONSE_HEADER_BYTES=65536
AI_MAX_CHAT_DECOMPRESSED_BYTES=2097152
AI_MAX_EMBEDDING_DECOMPRESSED_BYTES=4194304

# Embedding
EMBEDDING_BASE_URL=REPLACE_ENDPOINT
EMBEDDING_API_KEY=CHANGE_ME
EMBEDDING_MODEL=REPLACE_MODEL_NAME
EMBEDDING_VECTOR_SIZE=REPLACE_APPROVED_DIMENSION
EMBEDDING_BATCH_SIZE=REPLACE_APPROVED_BATCH_SIZE

# OCR
OCR_PROVIDER=local
OCR_BASE_URL=
OCR_API_KEY=
OCR_REQUEST_TIMEOUT_SECONDS=120
OCR_MAX_RETRIES=1

# Nginx
NGINX_IMAGE_TAG=REPLACE_WITH_PINNED_VERSION
NGINX_CLIENT_MAX_BODY_SIZE=50m
NGINX_RATE_LIMIT_API=20r/s

# RAG retrieval candidates - must be validated by fixed datasets
RAG_TOP_K=5
RAG_SCORE_THRESHOLD=
RAG_MAX_CONTEXT_CHUNKS=5

# Metrics
METRICS_ENABLED=true
METRICS_INTERNAL_TOKEN=CHANGE_ME

# Feature flags
ENABLE_LOCAL_VLLM=false
ENABLE_NEO4J=false
ENABLE_LANGFUSE=false
ENABLE_PROMETHEUS_STACK=false
```

`ai-policy-v1.json` 是上述环境变量解析后的规范化、不可变配置，字段名固定为：

- 顶层：`policy_version/policy_hash/provider_calls_enabled/profiles/operations/retry/breaker/rate_limits/outbound_limits`；`policy_hash` 使用 RFC 8785 JCS + SHA-256，secret 只保存 slot 标识。
- 每个 Profile：`profile_type/base_url/model_id/allowed_response_model_ids/auth_scheme/secret_slot/context_window_tokens/tokenizer_id/tokenizer_hash/embedding_dimension/pricing_version/billing_mode/input_price_micro_usd_per_million/output_price_micro_usd_per_million/redis_unavailable_mode`；环境未签署的值不得以示例替代。
- 每个 operation：`connect_timeout_seconds/deadline_seconds/max_attempts/max_same_target_attempts/max_provider_attempts_per_business_operation/max_model_repairs/max_input_tokens_per_request/max_output_tokens_per_request/max_total_tokens/max_cost_micro_usd/report_use_fallback`。

`policy_version=1` 的六类 deadline、尝试与预算必须与 AI 详细设计第 3.3 节精确一致。旧 `LLM_REQUEST_TIMEOUT_SECONDS/LLM_MAX_RETRIES/LLM_MAX_CONCURRENCY/EMBEDDING_REQUEST_TIMEOUT_SECONDS` 只能被识别为 legacy 配置，禁止静默换算；启用真实调用时仅提供旧字段必须启动失败，并且错误不得回显原值。数据库分块配置由 KB-004 发布，禁止以任何 `CHUNK_*` 环境变量充当组织默认值。

## 5.3 密钥管理

生产建议：

- 使用 Docker Secret、Kubernetes Secret（未来）或云密钥服务。
- 密钥轮换后重启相关服务并使旧 Token 失效。
- 不在命令行历史中直接传入密钥。
- 备份文件加密，密钥与备份分开保存。

---

# 6. 服务启动顺序

## 6.1 推荐顺序

```text
PostgreSQL、Redis、MinIO、Qdrant
→ PostgreSQL 扩展、57 表迁移与五角色种子
→ 按需运行一次性离线 bootstrap 并完成首管理员强制换密
→ MinIO Bucket 和策略初始化
→ 在已签署 Embedding Profile 后检查 Qdrant Collection/维度；当前 contract 阶段只做离线配置校验
→ Backend
→ Worker
→ Frontend
→ Nginx
→ AUD-003 发布规则、KB-004 发布首个组织分块配置
→ 离线 AI Mock；不得执行 vLLM/外部 Provider 网络探针
→ 冒烟测试
```

Compose 的 `depends_on` 不能替代应用层重试和健康检查。Backend、Worker 必须能处理依赖暂时不可用。

## 6.2 首次启动

```bash
cp infra/env/.env.example .env
# 编辑 .env，替换全部 CHANGE_ME 和模型配置

docker compose config

docker compose up -d postgresql redis minio qdrant
./infra/scripts/health-check.sh data
./infra/scripts/migrate.sh
./infra/minio/init-buckets.sh

docker compose up -d backend worker frontend nginx
./infra/scripts/health-check.sh all
./infra/scripts/smoke-test.sh
```

命令为建议流程，脚本名称需在实现阶段落地。

## 6.3 日常启动

```bash
docker compose up -d
./infra/scripts/health-check.sh all
```

## 6.4 停止

```bash
docker compose stop
```

禁止在未确认备份和数据用途时执行：

```bash
docker compose down -v
```

该命令会删除命名卷，生产环境应通过权限和操作规程限制。

---

# 7. PostgreSQL 初始化与迁移

## 7.1 版本和扩展

建议 PostgreSQL 16.x，并启用：

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;
```

## 7.2 初始化流程

1. 创建数据库和最小权限应用账号。
2. 安装扩展。
3. 执行 Alembic 基线迁移，创建 57 张核心表并幂等写入五个固定角色；迁移不得创建组织、管理员、默认密码、真实规则行或组织分块配置行。
4. 使用一次性离线 bootstrap CLI，在 advisory lock 和单事务内创建首组织、首管理员、首个 `system_admin` 分配及审计。凭据只从 TTY/stdin/受限 FD/Secret Manager 注入，不得进入 argv、环境回显、日志或文档；禁止匿名初始化 HTTP。
5. 首管理员以临时密码登录时只获取 5 分钟一次性 `password:change` Token，完成强制换密并重新登录。
6. 由 `AUD-003` 发布 15 条真实 P0 规则；由 `KB-004` 创建并发布首个组织级 `markdown_ast_structural/700/1200/50/100` 分块配置。
7. 验证关键条件唯一索引、状态/不可变触发器、bootstrap 并发/重跑和角色/规则/配置所有权。

完全相同的 bootstrap 身份与输入哈希重跑为 no-op；已初始化后使用不同参数或发现半初始化/角色哈希不一致时 fail closed，不自动修复。

## 7.3 迁移原则

- 迁移文件提交 Git 并经过评审。
- 迁移前备份。
- 开发/test 自动迁移；production 使用显式发布步骤。
- 不在应用启动过程中无条件自动执行破坏性迁移。
- 字段删除和类型收缩采用“扩展—迁移—切换—清理”策略。
- 影响不可变版本、状态枚举或 API 的迁移必须关联变更请求。

## 7.4 升级流程

```text
备份
→ 检查当前 Alembic Revision
→ 停止写入或进入维护模式（按迁移影响）
→ 执行升级
→ 数据校验
→ 启动 Backend/Worker
→ 健康检查
→ 核心 API 和 E2E 冒烟
```

## 7.5 回滚

- 只有经过验证的可逆迁移才允许自动 downgrade。
- 数据变换型迁移优先采用前向修复，不盲目回滚。
- 回滚必须同时考虑应用镜像、Schema、Prompt 和队列中旧任务的兼容性。

## 7.6 `20260807_006` 三表升级、降级与恢复

- CR-012-R3 只授权空表 DDL 与离线/专用合成 PostgreSQL 16 验证；不授权 production migration、真实历史数据清洗、自动合并或供应商业务运行时。进入 production 仍需独立变更窗口、备份、数据只读报告和 production 审批。
- Upgrade 必须先确认 `SHOW server_encoding` 精确为 `UTF8`，不得静默改写非规范或重复数据；`contracts`、`invoices`、`suppliers` 与四个循环外键必须在同一 revision、同一事务内全部成功或全部回滚。
- 执行任何真实环境 downgrade 前，先进入维护模式，停止 Backend 新写入，排空 Worker 写任务，并确认没有活跃业务写事务；这些步骤不替代独立 production 放行。
- Downgrade 在同一事务先执行 `SET LOCAL lock_timeout = '5s'`，再按固定顺序以 `ACCESS EXCLUSIVE` 锁定 `contracts`、`invoices`、`suppliers`。任一锁超时立即完整失败，不得继续检查或删除对象。
- 取得全部锁后，任一表非空必须以 SQLSTATE `55000` 原子拒绝，保留三表、数据、四个循环外键和 Alembic revision；三表全部为空时，先删除四个循环外键，再按依赖安全顺序删除三表。全程禁止 `CASCADE`。
- 遇到锁超时、`55000`、未知提交结果或任何 DDL 异常时保持维护模式，不盲目重试；重新查询权威 Alembic revision、三表、四个循环外键和行数，确认事务结果。对象仍完整时解除阻塞锁或清理方案获批后重试；出现非预期半状态时停止发布，保留证据并采用经评审的前向修复/恢复，不得手工删除剩余对象。
- 只有 revision、表/FK 完整性、空表条件、应用兼容性和 Backend/Worker 健康检查全部通过后才能退出维护模式。合同级测试通过不等于 production 已放行。

---

# 8. MinIO 设计与初始化

## 8.1 Bucket

| Bucket | 内容 | 备份级别 |
|---|---|---|
| `quarantine` | 未完成安全扫描的上传文件 | 短期/按策略 |
| `originals` | 已通过校验的原始文件 | 必须备份 |
| `assets` | 图片、签字、印章、复杂表格资源 | 必须备份 |
| `previews` | 页面预览和缩略图 | 可重建，按需备份 |
| `reports` | PDF 审核报告 | 必须备份或可按版本重建并核验 |
| `exports` | Excel 和评测导出 | 按保留策略 |
| `temp` | 临时文件 | 可清理 |

## 8.2 初始化

- 创建 Bucket。
- 禁止匿名读写。
- Backend/Worker 使用最小权限访问账号。
- Console 管理账号与应用账号分离。
- 配置对象版本或保留策略时评估存储成本。
- 配置 temp、quarantine 和过期导出的生命周期。

## 8.3 对象键

对象键不可由用户文件名直接组成，建议：

```text
{organization_id}/{resource_type}/{yyyy}/{mm}/{uuid}/{artifact_name}
```

数据库保存：Bucket、对象键、SHA-256、大小、MIME、状态和业务关系。

## 8.4 下载

- API 先执行身份和资源权限校验。
- 返回短时签名 URL 或受控流式下载。
- 默认有效期建议 300 秒，最终值配置化。
- 不向前端暴露永久对象键和 Secret。
- read_only 在 P0 无下载权限。

## 8.5 一致性

定期检查：

- 数据库引用对象是否存在。
- 对象大小和 SHA-256 是否一致。
- 孤儿对象和无对象数据库记录。
- 报告和导出的过期清理。

---

# 9. Redis 与 Celery

## 9.1 Redis 用途

- Celery Broker。
- 分布式锁。
- API 限流。
- 幂等和短期缓存辅助。
- Celery Result Backend（如采用）。

Redis 不保存最终合同、发票、风险、审核状态或报告事实。

## 9.2 队列

建议逻辑队列：

```text
document
extraction
knowledge
evaluation
audit
report
maintenance
```

| 队列 | 任务 |
|---|---|
| document | 安全扫描、解析、OCR、Markdown、预览 |
| extraction | 合同/发票字段提取 |
| knowledge | 分块、Embedding、索引、一致性 |
| evaluation | 固定数据集检索评测 |
| audit | 快照、规则、制度检索、风险解释 |
| report | PDF、Excel 生成 |
| maintenance | 补偿、一致性、清理和重建 |

## 9.3 Worker

- Backend 与 Worker 使用同一业务代码镜像。
- 可按队列拆 Worker 或使用单 Worker 监听多个队列。
- GPU/OCR/Embedding 密集任务与普通规则任务建议使用不同并发配置。
- 任务必须幂等。
- Job 最终状态写 PostgreSQL `async_jobs`。
- 使用 Transactional Outbox 保证业务事务和任务发布一致。

## 9.4 超时与重试

- 配置软超时和硬超时。
- 只对明确可恢复错误重试。
- 使用指数退避和抖动。
- 达到上限进入 failed 或 dead-letter，保留错误码和 Trace ID。
- Worker 中断后任务必须可恢复或明确失败。

## 9.5 监控

- 队列积压。
- 最老任务等待时间。
- 成功、失败、重试和取消。
- Worker 在线数和心跳。
- 任务耗时。
- Dead-letter 数量。

---

# 10. Qdrant 配置与重建

## 10.1 Collection 策略

按“环境 + Embedding 模型/维度”建 Collection：

```text
finaudit_policy_chunks_dev_e1024_v1
finaudit_policy_chunks_test_e1024_v1
finaudit_policy_chunks_prod_e1024_v1
```

名称中的 `e1024` 仅为数据库设计中的示例。最终维度必须与 Embedding 模型一致。

## 10.2 Vector 配置

| 项 | 设计 |
|---|---|
| size | 由 Embedding 模型决定 |
| distance | 优先 Cosine，经固定评测验证 |
| on_disk | 生产建议启用 |
| HNSW | 初始受控默认；变化须回归 |
| quantization | P0 默认关闭 |
| point ID | `document_index_items.qdrant_point_id` |

## 10.3 索引版本

- 一个知识库在 PostgreSQL 中只有一个活动索引版本。
- 同一 Collection 用 `index_version_id` 区分候选和历史索引成员。
- 激活前执行成员数、Point ID、内容哈希、Payload 和向量维度一致性检查。
- 未通过固定评测不得激活。
- 新索引失败时旧活动索引继续服务。

## 10.4 快照

Qdrant 可定期 snapshot，但其数据仍应能从 PostgreSQL 的活动索引成员和活动 Chunk 重建。

## 10.5 重建流程

```text
确认 PostgreSQL 和 MinIO 已恢复
→ 找到目标知识库索引版本
→ 读取 index member manifest
→ 读取 Chunk 正文并校验哈希
→ 使用记录的 Embedding 模型重新生成向量
→ upsert 稳定 point ID
→ 执行数量/ID/版本/哈希一致性
→ 运行 RET-001/正式评测集
→ 恢复活动检索
```

不得从 Redis 恢复业务事实。

---

# 11. vLLM 与模型服务

## 11.1 部署模式

两种模式：

1. Compose `vllm` Profile，本地主机具备 NVIDIA GPU。
2. 外部 OpenAI 兼容模型服务，Backend/Worker 通过内网或 HTTPS 访问。

业务代码只访问 AI Gateway，不依赖具体部署方式。

## 11.2 示例 Profile

```yaml
services:
  vllm:
    image: vllm/vllm-openai:${VLLM_IMAGE_TAG}
    profiles: ["ai"]
    command:
      - --model
      - ${VLLM_MODEL_PATH_OR_ID}
      - --served-model-name
      - ${LLM_GENERATION_MODEL}
      - --max-model-len
      - ${VLLM_MAX_MODEL_LEN}
      - --api-key
      - ${LLM_API_KEY}
    environment:
      NVIDIA_VISIBLE_DEVICES: all
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    networks: [app_net]
```

镜像、模型、最大长度、量化和 GPU 参数必须通过实际硬件验证。

## 11.3 配置

- `AI_POLICY_VERSION=1`
- `AI_PROVIDER_CALLS_ENABLED=false`（当前强制值）
- `AI_POLICY_FILE`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_EXTRACTION_MODEL`
- `LLM_GENERATION_MODEL`
- `LLM_FALLBACK_MODEL`
- `LLM_CONNECT_TIMEOUT_SECONDS`
- `LLM_MAX_ATTEMPTS_PER_GENERATION=3`
- `LLM_MAX_SAME_TARGET_ATTEMPTS=2`
- `AI_MAX_PROVIDER_ATTEMPTS_PER_OPERATION=6`
- `AI_MAX_MODEL_REPAIRS=2`
- `LLM_REPORT_DRAFT_USE_FALLBACK=false`

Profile 固定非流式 Chat Completions/Embeddings 包络和 Bearer 认证；内部 vLLM 同样必须启用 `--api-key`。启用真实调用时，前四类 LLM 的 fallback 必须非空且与主目标不同，报告是否使用它只由严格布尔开关决定。具体 endpoint、model、允许响应模型、context window、Tokenizer、维度、价格和 IP/CIDR 属于目标环境待签值。

## 11.4 分层验证与放行

1. `environment_scope='contract'`（当前）：只允许不打开 socket 的离线 Mock/MockTransport，校验配置、严格 HTTP 包络、错误、预算、重试顺序和脱敏；`AI_PROVIDER_CALLS_ENABLED=false`。
2. `fixed_test_provider` 五方另行签署完整值后：才允许隔离环境的 `/v1/models`、真实 Chat/Embedding、主动超时和 Trace 验证。模型列表只证明探针可达，不能替代真实生成。
3. 固定测试通过且 `production` 值另行签署后：才允许最小 canary。测试签署不得替代生产签署。

任何阶段的检查都不得记录或返回 API Key；本次批准不包含第 2、3 层，运维脚本必须跳过其网络步骤并报告 `PENDING`，不得把 calls-disabled 当作 Provider 可用。

## 11.5 降级

模型不可用：

- 字段提取进入人工确认，不写伪字段。
- 规则执行继续。
- 风险解释为空或标记降级。
- 报告使用确定性模板并声明 AI 降级。
- RAG 返回模型不可用，不伪装成知识库无答案。

---

# 12. Nginx

## 12.1 路由

| 路径 | 上游 |
|---|---|
| `/` | frontend |
| `/api/v1/` | backend |
| `/health` | backend |
| `/health/dependencies` | backend，生产建议受限 |
| `/metrics` | backend，仅内网或认证采集 |

## 12.2 SPA 回退

前端深层路由应回退到 `index.html`，但 `/api`、`/health`、`/metrics` 不参与回退。

## 12.3 上传

- `client_max_body_size` 与后端 50MB 上限一致或略高以允许协议开销。
- 请求体超限返回明确状态。
- 长上传设置合理的读取超时。
- 后端仍必须再次校验大小和文件头。

## 12.4 HTTPS

- 生产仅 HTTPS。
- HTTP 重定向 HTTPS。
- 使用受信证书或受控内部 CA。
- 配置 TLS 协议和密码套件。
- 证书到期前更新并演练。

## 12.5 安全头

至少评估：

- HSTS。
- Content-Security-Policy。
- X-Content-Type-Options。
- Referrer-Policy。
- Permissions-Policy。
- Frame 限制。

CSP 必须与前端资源、文件预览和下载方式联调，不得直接复制导致功能不可用的模板。

## 12.6 限流

- 登录接口单独限流。
- 一般 API 限流。
- RAG/AI 接口设置更严格并发。
- 上传接口按用户和来源限制。
- 429 返回可理解错误和 Trace ID。

## 12.7 代理头

传递：

- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `X-Request-ID`
- `traceparent`

只信任受控代理链，避免客户端伪造来源 IP。

---

# 13. 健康检查

## 13.1 服务检查

| 服务 | 检查方式 |
|---|---|
| frontend | 静态页面响应 |
| backend | `/health` |
| dependencies | `/health/dependencies` |
| worker | Celery Ping/心跳 |
| PostgreSQL | `pg_isready` |
| Redis | `redis-cli ping` |
| MinIO | 健康接口 |
| Qdrant | readiness |
| 安全扫描 Adapter | 生产必须执行真实探针；未配置/不可用使依赖健康失败，文件保持 fail closed |
| vLLM/外部 Provider | 仅在对应 `fixed_test_provider` 或 `production` Profile 获批后执行受控探针；当前 contract 阶段为 disabled，不发网络 |

## 13.2 `/health`

仅判断 Backend 进程和基本事件循环可用，返回最少信息：

```json
{
  "status": "ok",
  "service": "backend",
  "version": "0.1.0"
}
```

可允许匿名探针，但不得包含依赖地址和版本细节。

## 13.3 `/health/dependencies`

按权限或内网访问，返回脱敏状态：

```json
{
  "status": "degraded",
  "dependencies": {
    "postgresql": "ok",
    "redis": "ok",
    "minio": "ok",
    "qdrant": "unavailable",
    "worker": "ok",
    "llm": "optional_unavailable"
  },
  "trace_id": "..."
}
```

- 必需依赖失败可返回 503。
- 模型为可降级依赖时可返回 degraded，具体状态由运行策略决定。
- 不返回凭据、对象路径和堆栈。

## 13.4 健康与业务可用性

进程健康不等于业务健康。发布后还需执行：

- 登录。
- 文件上传。
- Job 创建和查询。
- PostgreSQL 读写。
- MinIO 对象写读。
- Qdrant 检索。
- 当前 contract 阶段执行离线模型包络/结构化 Mock；真实模型结构化输出只在对应环境审批后执行，并单独记录证据。
- 最小规则执行。

---

# 14. 日志与 Trace

## 14.1 输出

P0：

- Backend、Worker、Nginx 输出 stdout/stderr。
- Docker 日志驱动配置大小和文件数轮转。
- 关键业务操作写 `operation_logs`。
- AI-001 只产生脱敏 `AiCallEventV1`；AI-005 经 durable reserve/complete、Outbox 和顺序幂等投影写 `ai_call_logs`。其他模块不得直接写入。
- Job 状态写 `async_jobs`，每次尝试和阶段历史追加写 `async_job_steps`。

stdout、`operation_logs` 和 AI 审计投影是三个不同职责。Docker 日志轮转不能替代数据库审计保留；`TBD-OPS-007/TBD-007` 获批前禁止到期清理 `outbox_events/ai_call_logs`。

## 14.2 JSON 字段

```json
{
  "timestamp": "2026-08-05T06:00:00Z",
  "level": "INFO",
  "service": "worker",
  "environment": "demo",
  "trace_id": "...",
  "request_id": "...",
  "job_id": "...",
  "module": "knowledge.index",
  "event": "index_consistency_check_completed",
  "resource_type": "document_index_version",
  "resource_id": "...",
  "duration_ms": 1200,
  "status": "approved",
  "error_code": null
}
```

## 14.3 Trace 传播

```text
Browser/Nginx
→ Backend
→ PostgreSQL/MinIO/Redis/Qdrant
→ Celery Header
→ Worker
→ OCR/Embedding/LLM
→ 报告
```

关键 Span：

- http.request
- auth.validate
- permission.check
- file.upload
- document.parse
- ocr.page
- field.extract
- markdown.convert
- chunk.build
- embedding.batch
- qdrant.upsert
- retrieval.query
- llm.generate
- citation.validate
- rule.execute
- audit.snapshot
- report.render

## 14.4 脱敏

禁止日志：

- 密码、Token、API Key、JWT 密钥。
- MinIO Secret、数据库密码。
- 完整系统 Prompt。
- 未授权完整财务正文。
- 原始文件二进制。

税号、统一社会信用代码和人员信息按环境和角色脱敏。

## 14.5 日志轮转

Compose 建议配置：

```yaml
logging:
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
```

数值为初始示例，生产需根据磁盘、日志量和保留要求确认。

---

# 15. P0 最小指标

`/metrics` 仅内网采集，暴露低基数指标：

- HTTP 请求数、延迟和错误率。
- Celery 队列积压。
- Job 成功、失败、重试和取消。
- OCR、解析、Markdown 成功率。
- Embedding/LLM 调用耗时、错误和降级。
- Qdrant 检索耗时。
- 索引一致性失败。
- 审核执行和报告生成结果。

禁止标签：

- user_id。
- 文件名。
- 税号。
- 问题正文。
- Chunk 正文。
- Prompt 正文。

Prometheus、Grafana 和自动告警完整栈属于 P1。

---

# 16. 备份策略

## 16.1 数据分类

| 数据 | 是否事实源 | 备份/恢复策略 |
|---|---:|---|
| PostgreSQL | 是 | 必须定期备份和恢复演练 |
| MinIO originals/assets | 是/证据制品 | 必须备份并校验哈希 |
| MinIO reports/exports | 重要制品 | 按保留要求备份或可重建验证 |
| Qdrant | 否，可重建 | Snapshot + PostgreSQL 重建 |
| Redis | 否 | 持久化提高恢复速度，不作为事实恢复来源 |
| 应用镜像和配置 | 版本事实 | 镜像仓库、Git Tag、配置备份 |
| Prompt 和 Schema | 版本事实 | Git 和发布制品 |

## 16.2 PostgreSQL

建议：

- 每日全量备份或按环境需求。
- 生产可增加 WAL/PITR。
- 备份加密。
- 保存校验和、时间、Revision 和应用版本。
- 定期在隔离环境恢复。

示例：

```bash
pg_dump --format=custom --file=/backup/finaudit_$(date +%F_%H%M).dump "$DATABASE_URL"
```

示例命令需要由脚本避免在进程列表暴露密码。

## 16.3 MinIO

- 对 originals、assets、reports 配置备份。
- 保存对象版本、大小、ETag/SHA-256 清单。
- 备份后抽样校验数据库记录。
- temp 和过期 exports 可按生命周期清理。

## 16.4 Qdrant

- 活动 Collection 定期 snapshot。
- Snapshot 不是唯一恢复方式。
- 恢复后必须按 PostgreSQL 成员执行一致性检查。

## 16.5 RPO/RTO

当前基线未给出统一生产 RPO/RTO 数值。每个部署环境必须记录：

- 目标 RPO。
- 目标 RTO。
- 备份频率。
- 保留周期。
- 恢复责任人。
- 最近一次演练日期和结果。

不得在未演练情况下宣称已达到某 RPO/RTO。

---

# 17. 恢复流程

## 17.1 全量恢复顺序

```text
准备干净主机/卷
→ 恢复应用镜像、配置和证书
→ 恢复 PostgreSQL
→ 验证 Alembic Revision 和核心表
→ 恢复 MinIO
→ 校验文件数量、大小和哈希
→ 启动 Redis
→ 启动 Backend/Worker
→ 重建或恢复 Qdrant
→ 一致性检查
→ 固定检索评测
→ 完整审核冒烟
→ 开放 Nginx 流量
```

## 17.2 PostgreSQL 恢复验证

- 企业主体、用户和角色。
- 文件和对象键。
- 解析、Markdown、分块和索引版本。
- 合同、发票、补充协议和关联。
- 审核快照、风险和报告。
- 操作日志和 AI 调用摘要。
- Alembic Revision。

## 17.3 MinIO 恢复验证

- originals/assets/reports 对象存在。
- 抽样 SHA-256 与 PostgreSQL 一致。
- 签名 URL 仍由当前权限生成。
- 不存在公开 Bucket。

## 17.4 Qdrant 恢复验证

- Collection 维度和距离正确。
- Point 数与 PostgreSQL 成员一致。
- ID、索引版本、内容哈希和 Payload 一致。
- RET-001 和正式固定数据集通过。
- 旧活动索引在重建期间的服务策略明确。

---

# 18. 发布与升级

## 18.1 发布制品

- Backend 镜像。
- Frontend 镜像。
- 数据库迁移版本。
- Compose 文件。
- Nginx 配置。
- Prompt、Schema 和规则版本。
- `.env.example`。
- 发布说明和回滚说明。

## 18.2 发布步骤

```text
确认变更已批准
→ 测试与安全门禁通过
→ 生成镜像与校验摘要
→ 备份 PostgreSQL/MinIO
→ 拉取新镜像
→ 执行数据库迁移
→ 启动数据和应用服务
→ 健康检查
→ API/AI/RAG/审核冒烟
→ 观察错误和队列
→ 发布完成记录
```

## 18.3 回滚

回滚前判断：

- 数据库迁移是否兼容旧应用。
- 新任务消息是否能被旧 Worker 识别。
- Prompt/Schema 是否兼容。
- 新生成索引和报告是否需要保留。

若数据库已发生不可逆变更，采用前向修复，不盲目回滚镜像。

## 18.4 零/低停机

P0 Compose 可接受受控维护窗口。未来需要低停机时：

- Backend 多副本。
- Worker 分批重启。
- 兼容性迁移。
- Nginx 上游切换。
- 数据库连接排空。

Kubernetes 和滚动发布属于 P2/未来扩展。

---

# 19. 日常运维

## 19.1 每日检查

- 容器状态和重启次数。
- `/health`、依赖健康。
- 队列积压和失败 Job。
- PostgreSQL 磁盘、连接和慢查询。
- MinIO 容量和失败对象。
- Qdrant 一致性和检索错误。
- 模型服务错误、超时和降级。
- 备份是否成功。
- 日志磁盘使用。

## 19.2 每周检查

- 失败任务分类。
- 解析/OCR/Markdown 成功率。
- 索引构建和评测结果。
- 安全扫描和异常登录。
- 审计日志完整性。
- 备份抽样校验。
- 容器镜像和依赖漏洞。

## 19.3 定期检查

- 全量恢复演练。
- Qdrant 丢失重建演练。
- 模型不可用降级演练。
- Redis 清空恢复验证。
- 证书轮换。
- 密钥轮换。
- 数据保留和清理。

---

# 20. 故障排查

## 20.1 服务无法启动

检查顺序：

1. `docker compose config`。
2. 必需环境变量是否存在。
3. 端口和磁盘。
4. 数据服务健康。
5. Alembic Revision。
6. Backend/Worker 日志中的脱敏错误码。
7. 镜像架构和依赖。

## 20.2 Backend 503

- `/health` 是否正常。
- `/health/dependencies` 哪个依赖失败。
- PostgreSQL 连接池。
- Redis、MinIO、Qdrant DNS 和网络。
- Nginx 上游配置。
- 不向用户展示内部堆栈。

## 20.3 Worker 不消费

- Redis Broker。
- Worker 心跳。
- 队列路由。
- 任务是否写入 `async_jobs` 和 Outbox。
- Outbox 发布器。
- Dead-letter。
- 任务版本和代码兼容。

## 20.4 文件上传失败

- Nginx 和 Backend 大小限制是否一致。
- MIME/文件头校验。
- quarantine Bucket 权限。
- MinIO 容量和网络。
- 安全扫描状态。
- 重复哈希冲突。

## 20.5 解析/OCR 失败

- 文件损坏/加密。
- OCR Adapter 连通性。
- 超时和重试。
- 图片旋转、清晰度和置信度。
- 是否进入 `manual_review_required`。
- 不得伪造成功解析版本。

## 20.6 Markdown/分块失败

- 活动解析版本。
- 来源映射阻断问题。
- Markdown 质量结果。
- 制度是否有活动 Markdown。
- 空块、超长块和来源缺失。
- 旧活动 Markdown/Chunk 是否仍可用。

## 20.7 Qdrant 不一致

- PostgreSQL index member manifest。
- Collection 名、维度、距离。
- Point 数和稳定 ID。
- Payload 版本和哈希。
- 重新 upsert 或全量重建。
- 未通过一致性前不得激活索引。

## 20.8 RAG 无答案异常

区分：

- 真正没有有效证据。
- 权限过滤导致无候选。
- 基准日期不匹配。
- 制度 revoked。
- Qdrant/Embedding 故障。
- 引用校验失败。
- 相似度阈值配置。

系统故障不得返回业务“无答案”。

## 20.9 模型不可用

- 先确认 `AI_PROVIDER_CALLS_ENABLED` 与环境审批状态；当前 contract/offline 阶段只检查禁用状态和 Mock 故障注入，不调用 `/v1/models`。
- 目标环境获批后才检查 `/v1/models`，且该探针不能替代真实 Chat/Embedding 证据。
- API Key 和模型名。
- GPU、显存和进程。
- 上下文长度。
- 并发和队列。
- 熔断状态。
- 备用模型。

验证规则结果是否保留、任务是否进入降级、报告是否有降级声明。

## 20.10 报告失败

- 执行版本是否 completed。
- 模板和字体（不得随制品公开字体文件）。
- MinIO reports 权限。
- AI 草稿失败时确定性模板。
- 报告 Job 状态和重试。
- 旧报告版本不覆盖。

---

# 21. 事件响应

## 21.1 事件等级

| 等级 | 示例 |
|---|---|
| P0 紧急 | 数据泄露、业务事实损坏、权限绕过、不可恢复数据丢失 |
| P1 严重 | 核心服务不可用、审核结果错误、大量任务失败 |
| P2 主要 | 部分功能降级、有替代路径 |
| P3 一般 | 单用户、非核心问题 |

## 21.2 处理流程

```text
发现
→ 建立事件编号
→ 限制影响
→ 保存证据和 Trace
→ 评估数据/权限/AI影响
→ 恢复服务
→ 验证一致性
→ 根因分析
→ 整改和回归
→ 关闭
```

## 21.3 安全事件

- 立即撤销相关 Token 和密钥。
- 隔离受影响服务。
- 保留不可篡改审计日志。
- 检查下载、查询、Prompt 和模型日志。
- 不在普通沟通渠道发送完整敏感数据。

---

# 22. 环境差异

## 22.1 配置矩阵

| 项目 | local | test | demo/staging | production |
|---|---|---|---|---|
| Debug | 可开启 | 关闭 | 关闭 | 关闭 |
| 数据 | 合成 | 固定脱敏 | 固定演示/验收 | 正式 |
| HTTPS | 可选 | 建议 | 必须 | 必须 |
| AI Provider | 当前均 calls-disabled；可做离线 Mock | 仅 `fixed_test_provider` 获批后使用固定测试服务 | 仅对应环境值获批后使用候选演示模型 | 仅 `production` 五方签署后 canary 正式模型/集群 |
| 密钥 | 本地临时 | 测试密钥 | 独立演示密钥 | Secret 管理 |
| 端口 | 可映射数据端口用于调试 | 仅受控 | 仅 Nginx | 仅 Nginx |
| 日志 | DEBUG/INFO | INFO | INFO | INFO/WARN |
| 备份 | 可选 | 测试恢复 | 必须 | 必须 |
| Qdrant | local Collection | test Collection | demo Collection | prod Collection |
| 数据清理 | 开发者控制 | 自动重置 | 受控 | 生命周期策略 |
| 指标 | 可关闭 | 开启 | 开启 | 开启 |

## 22.2 Demo 环境

求职演示环境建议：

- 只使用模拟和脱敏数据。
- 对外开放 Nginx 单一端口。
- 关闭注册和管理员创建入口。
- 不随迁移或镜像提供默认组织、账号或密码；演示账号只能由受控离线 bootstrap/fixture 在合成环境显式创建并强制换密。
- 限制上传大小、请求频率和模型 Token。
- 定期重置数据。
- 不展示内部日志、模型 API Key 和管理控制台。
- 保留完整 Trace 和演示流程。

## 22.3 生产环境

- 独立主机或受控集群。
- HTTPS 和安全头。
- 数据端口不外露。
- 备份、恢复和密钥轮换。
- 系统管理员与财务复核或审计复核角色不得长期组合；break-glass 只能按已批准的双人限时流程生效。
- 受控变更和发布窗口。
- 正式 RPO/RTO 和保留策略。

---

# 23. 数据保留与清理

## 23.1 不可直接清理

- 业务事实。
- 已被审核快照引用的文件和版本。
- 操作审计日志。
- `outbox_events`、`ai_call_logs` 和关联 late-completion 证据（`TBD-OPS-007/TBD-007` 获批前绝对禁止物理/到期清理）。
- 人工修改、审批和风险复核记录。
- 已发布报告及其版本关系。

## 23.2 可按策略清理

- temp 对象。
- 过期签名 URL（本身不存储）。
- 过期导出文件。
- 失败任务的临时制品。
- 已确认可重建且不被活动版本使用的派生缓存。

## 23.3 清理要求

- 先检查数据库引用。
- 记录操作人、原因、时间和 Trace ID。
- 不通过前台执行物理删除业务审计数据。
- 生产清理脚本先 dry-run。

---

# 24. 安全检查清单

- [ ] `.env` 和证书私钥不在 Git。
- [ ] PostgreSQL、Redis、Qdrant 不映射公网端口。
- [ ] MinIO 管理口受限。
- [ ] vLLM 不对公网开放，内部也使用 Bearer；Provider 调用开关默认关闭。
- [ ] Nginx 使用 HTTPS、限流和安全头。
- [ ] 文件先进入 quarantine。
- [ ] 应用账号使用最小权限。
- [ ] 签名 URL 短时有效。
- [ ] 日志和指标无密钥、Token 和完整敏感正文。
- [ ] 备份加密并限制访问。
- [ ] 不存在镜像/迁移内置的默认组织、账号或密码；bootstrap 凭据未进入 argv、日志、环境回显或文档。
- [ ] 生产安全扫描器已配置并进入依赖健康；只有 `clean` 文件可解析，其余五态 fail closed。
- [ ] Provider 固定 URL、TLS/主机名、`trust_env=false`、禁代理/重定向、DNS/IP/peer、Header allowlist 和解压后字节上限均通过离线/获批环境测试。
- [ ] 生产禁用 Debug 和自动文档的非授权访问（按策略）。
- [ ] `/metrics` 和依赖健康接口受限。
- [ ] 镜像和依赖完成漏洞扫描。

---

# 25. AC-016 部署验收

## 25.1 前置

- 从 `.env.example` 创建环境配置。
- 使用固定版本镜像。
- 准备模拟合同、发票和制度数据。
- 准备 RET-001。
- 当前只执行 contract/offline 范围：`AI_PROVIDER_CALLS_ENABLED=false`，所有 AI 传输使用不打开 socket 的 Mock；fixed-test/production 验收另行放行。

## 25.2 步骤

1. 在空主机执行 Compose 启动。
2. 初始化 PostgreSQL、MinIO 和 Qdrant。
3. 验证所有必需服务健康。
4. 执行登录和权限冒烟。
5. 执行文件上传、解析、Markdown、分块和索引。
6. 执行 RET-001。
7. 执行合同发票审核和报告。
8. 重启全部容器。
9. 验证 PostgreSQL、MinIO 和评测数据保持。
10. 删除/隔离 Qdrant 数据并执行重建。
11. 在 calls-disabled/离线 Mock 下验证模型不可用、审计事件失败和确定性业务降级；不得启动或探测真实 Provider。
12. 扫描 Git 和日志中的密钥。

## 25.3 通过条件

- 所有 P0 必需服务健康。
- 完整审核和知识库链路成功。
- 重启不丢失业务事实和文件。
- Qdrant 可从 PostgreSQL/Chunk 重建并通过一致性。
- 模型不可用时规则结果保留。
- 外部只暴露 Nginx。
- Git 无真实密钥。
- 本节当前通过只证明 Compose 与离线降级路径；不证明 fixed-test Provider、真实生成或 production 放行。

---

# 26. 运维脚本要求

| 脚本 | 功能 | 安全要求 |
|---|---|---|
| `bootstrap.sh` | 首次初始化 | 幂等，不打印密钥 |
| `migrate.sh` | 数据库升级 | 记录 Revision，失败退出 |
| `health-check.sh` | 汇总健康 | 输出脱敏 |
| `backup-all.sh` | PG/MinIO/Qdrant 快照 | 加密、校验和 |
| `restore-all.sh` | 恢复 | 二次确认，环境校验 |
| `rebuild-qdrant.sh` | 派生向量重建 | 指定索引版本，运行一致性 |
| `smoke-test.sh` | 发布后冒烟 | 使用专用测试账号 |
| `cleanup-temp.sh` | 临时文件清理 | dry-run、引用检查 |

所有脚本必须使用 `set -euo pipefail` 或同等错误处理，敏感变量不得通过 `echo` 输出。

---

# 27. 待确认事项

| 编号 | 待确认 | 影响 |
|---|---|---|
| TBD-OPS-001 | 目标主机 CPU、内存、磁盘和 GPU | 资源限制和并发 |
| TBD-OPS-002 | 固定镜像版本清单 | 可复现部署和漏洞管理 |
| TBD-OPS-003 | vLLM 模型、量化、最大上下文和显存 | AI Profile |
| TBD-OPS-004 | Embedding 模型和维度 | Qdrant Collection |
| TBD-OPS-005 | production 域名、证书和访问来源 | Nginx/防火墙 |
| TBD-OPS-006 | RPO、RTO、备份频率和保留期 | 备份恢复 |
| TBD-OPS-007 | 正式日志保留和审计保留 | 存储容量与合规 |
| TBD-OPS-008 | 生产恶意文件扫描器的具体产品/Adapter 实现 | 扫描必需且 fail closed 已冻结；只保留产品选型 |
| TBD-OPS-009 | Demo 环境公开方式和账号策略 | 求职演示安全 |
| TBD-OPS-010 | P1 可观测性上线时间 | Langfuse/Prometheus/Grafana |

---

# 28. 部署前检查

- [ ] 所有镜像版本已固定。
- [ ] `.env` 已替换全部占位值。
- [ ] 配置文件通过 Schema 校验。
- [ ] 数据服务端口未公网暴露。
- [ ] 57 表迁移、五角色种子、离线 bootstrap、强制换密以及规则/分块配置独立发布顺序已验证。
- [ ] MinIO Bucket、策略和生命周期已初始化。
- [ ] Qdrant Collection 与 Embedding 维度一致。
- [ ] 当前 contract/offline 门禁通过且 `AI_PROVIDER_CALLS_ENABLED=false`；未执行 Provider 网络调用。
- [ ] `fixed_test_provider` 审批与真实 Chat/Embedding/主动超时/Trace 证据（当前 `PENDING`，不得以模型列表或离线 Mock 替代）。
- [ ] `production` Profile/Policy 审批与最小 canary 证据（当前 `PENDING`）。
- [ ] Nginx 配置、证书、上传限制和安全头通过。
- [ ] Backend/Worker 健康和 Trace 传播通过。
- [ ] 备份完成且可读取。
- [ ] 核心 API、RAG、审核和报告冒烟通过。
- [ ] 日志和指标敏感信息扫描通过。
- [ ] AC-016 完成。

---

# 29. 结论

FinAudit Agent P0 使用 Docker Compose 交付，Nginx 是对外唯一入口，Backend 和 Worker 分离同步与异步职责，PostgreSQL 与 MinIO 构成必须恢复的业务事实和证据基础，Qdrant、Markdown、Chunk 和 Embedding 为可追溯、可重建的派生数据，Redis 不承担永久事实。

部署成功不能只以容器启动为标准。必须通过依赖健康、完整审核流程、Markdown/分块/索引、固定检索评测、模型降级、数据重启保持和 Qdrant 重建验证。所有环境必须使用独立密钥和数据，生产与公开演示环境不得暴露数据服务、管理控制台和敏感日志。
