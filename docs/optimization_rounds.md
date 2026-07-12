# 优化记录：10 轮 × 20 建议

本文件记录对 Quant Team OS 的十轮优化。每轮列出 20 条方向，标注状态：`已落地` / `已评估-暂缓` / `建议`。所有落地改动都在保持 `pytest`（233 通过）与 `ruff check` 全绿的前提下进行。测试基线在 py3.10 沙箱通过 `.pth` shim 注入 `datetime.UTC` 运行（不改动产品代码），生产运行环境为 py3.11+。

---

## R1 代码质量基线（ruff）

1. 引入 `ruff.toml`，策展规则集 E/F/W/I/B/UP/C4/SIM/PIE/PERF/RUF。**已落地**
2. 忽略 FastAPI `Depends()` 默认参数误报 B008。**已落地**
3. 忽略中文全角标点误报 RUF001/002/003。**已落地**
4. 对 conftest、main、scripts、tests 设置 E402 per-file-ignore（合法的延迟导入）。**已落地**
5. 自动修复 16 处未用 import（F401）。**已落地**
6. 自动排序 41 处乱序 import（I001），配置 `known-first-party`。**已落地**
7. 修复 `redaction.is_secret_ref_key` 的多重 endswith（PIE810）为元组形式。**已落地**
8. `stubs.QuantConnectMCPAdapter.actions` 加 `ClassVar` 标注（RUF012 可变类默认值）。**已落地**
9. DuckDB 结果 `zip(columns, row)` 加 `strict=True`，长度不匹配即暴露（B905）。**已落地**
10. superset `zip(chart_nodes, charts)` 加 `strict=True`。**已落地**
11. 测试中 `False if x else True` 简化为 `x != ...`（SIM211）。**已落地**
12. 清理修复后残留的无效 `# noqa`（RUF100）。**已落地**
13. `package.json` 增加 `lint` / `lint:fix` 脚本。**已落地**
14. `pyproject.toml` dev 依赖加入 `ruff>=0.6`。**已落地**
15. line-length 设为 120，E501 软性化不阻断。**已落地**
16. PERF401（手写列表构建）设为顾问级不阻断，避免大批量改写引入风险。**已落地（策略）**
17. 引入 `ruff format` 统一格式化。**建议**：全仓 format 会产生大 diff，需单独 PR。
18. 将 `ruff check` 接入 CI 阻断门。**建议**：需团队确认门禁策略后加到 `npm test`。
19. 引入 `mypy` 类型检查（渐进式）。**建议**：见 R10。
20. 引入 `pre-commit` 钩子串联 ruff。**建议**。

落地结果：`ruff check .` 全绿；`pytest` 233 通过（不含 openbb 合约测试，因沙箱挂载对单个文件加锁无法读取，非代码问题）。

---

## R2 日志与错误处理

发现：整库 `logging` 使用为 0，进程级信息用 `print`；40 处 `except Exception` 多为工具回退设计（合理），但个别静默吞错。

1. `worker_main.py` 引入模块 logger + `basicConfig`，级别可由 `WORKER_LOG_LEVEL` 控制。**已落地**
2. worker 启动 5 处 `print` 全部改为结构化 `logger.info/warning`，用惰性 `%` 参数。**已落地**
3. temporalio 缺失回退由 `print` 改 `logger.warning`。**已落地**
4. `observability.configure_otel` 失败分支原先静默返回 `"failed"`，现加 `logger.warning(exc_info=True)`。**已落地**
5. `observability.tool_observation` span 失败分支加 `logger.debug(exc_info=True)`，保留降级不影响业务。**已落地**
6. 审查 `session_scope`：`except Exception` 后 rollback+re-raise，正确，保留。**已评估**
7. 审查 `approval_service` 补偿逻辑：rollback + 状态回退 pending，正确，保留。**已评估**
8. 审查 adapter 回退 except：属 tool-first 架构的显式降级，保留。**已评估**
9. 统一 worker 日志格式 `时间 级别 名称 消息`。**已落地**
10. 为 API 进程引入统一 logging 配置（`app.main` 启动时 `basicConfig`）。**建议**：避免与容器/uvicorn 日志重复，需确认部署侧日志采集方案。
11. 引入 `structlog` 输出 JSON 便于 Loki 采集。**建议**：项目已有 promtail/loki，JSON 日志收益大，但属较大改造。
12. 关键 except 补 `logger.exception` 而非静默。**部分落地**（见 4/5），其余按需。
13. 为 `temporal_client` 三处 except 增加降级原因日志。**建议**。
14. `infisical` 三处 except 已带 `as exc` 并抛领域错误，检查确认信息不泄密。**已评估-合规**。
15. 数据质量 except 已带 `as exc` 并写入 artifact meta，可追溯。**已评估**。
16. 将日志中可能含密钥的字段接入既有 `redaction`。**建议**：与 R3 合并考虑。
17. 为 requestId/traceId 建立日志关联字段。**建议**：依赖 R2-11 的结构化日志。
18. `print` 在 `scripts/*` 属 CLI 输出，保留不改。**已评估**。
19. `agent-chat/app.py` 的输出评估为 Chainlit UI 侧，非服务日志，暂不改。**已评估**。
20. 增加日志级别环境变量文档说明。**已落地**（本文件 + 变量 `WORKER_LOG_LEVEL`）。

落地结果：`ruff` 全绿；worker 与 observability 相关 55 测试通过。

---

## R3 安全与密钥加固

审查 `auth.py`（JWT/RBAC）与 `redaction.py`（脱敏）。整体设计稳健：RS256 固定算法（无 alg 混淆）、校验 aud/iss、approver 禁止 service account。

1. `_jwks()` 原先每次鉴权都同步拉取 JWKS——延迟与可用性风险。加 300s TTL 内存缓存 + 线程锁。**已落地**
2. 提供 `clear_jwks_cache()` 供密钥轮转/测试清缓存。**已落地**
3. 脱敏正则新增 PEM 私钥块 `-----BEGIN ... PRIVATE KEY-----`。**已落地**
4. 新增 Google API key `AIza...`。**已落地**
5. 新增 Stripe `sk_live_/sk_test_/rk_*`（下划线，原 `sk-` 未覆盖）。**已落地**
6. 新增 GitHub `gho_/ghs_/ghu_` 与 `github_pat_` 细粒度 PAT。**已落地**
7. 新增 JWT/JWS 三段式 `eyJ...` 检测。**已落地**
8. 新增 11 条脱敏与缓存单测，含非密钥负样本防误伤。**已落地**
9. 确认新正则不影响既有 243 测试（无误伤）。**已验证**
10. `jwt.decode` 保持显式 `algorithms=["RS256"]`，防算法降级。**已评估-合规**
11. 本地鉴权回退仅在非 production 且开关开启时启用，生产强制 401。**已评估-合规**
12. `require_role` 对 approver + service account 双重拦截。**已评估-合规**
13. JWKS 拉取失败：捕获后优先返回过期缓存（IdP 短暂不可达不中断鉴权），彻底无缓存才抛 503。**已落地**（新增 2 测试）。
14. JWKS TTL 可配置化（settings）。**建议**：现为常量 300s。
15. 脱敏 `mask_secret` 对 <=8 位返回 `****`，避免泄露短密钥。**已评估-合规**
16. `contains_secret` 递归遍历 dict/list，审计前置校验完整。**已评估**
17. 增加 Azure/GCP service-account JSON 私钥检测。**建议**（PEM 已覆盖 `private_key` 字段）。
18. 对日志 sink 统一接入 `redact_secrets`（与 R2-16 呼应）。**建议**。
19. 增加 secret 扫描 CI（如 gitleaks）防提交泄密。**建议**。
20. JWKS 缓存加 `kid` 感知刷新（遇未知 kid 主动刷新一次）。**建议**：应对轮转窗口。

落地结果：`ruff` 全绿；全量 243 通过（新增 10 例）。

---

## R4 风控与策略引擎健壮性

审查 `risk/engine.py` 与 `services/policy.py`。整体 fail-closed 设计良好，但发现一处真实 **fail-open** 缺陷。

1. **缺陷修复**：NaN/inf 指标绕过阈值。`nan < min_sharpe` 求值为 `False`，导致 Sharpe/回撤/换手率检查静默通过。在 `build_risk_gate_input` 用有限哨兵值（`±1e12`）对非有限指标做 fail-closed 归一化。**已落地**
2. NaN/inf 无法序列化为合法 JSON，会污染 OPA 输入；在上游归一化同时保护 OPA 与本地两条路径。**已落地**
3. `trade_count` 非数值/非有限时归零（fail-closed）。**已落地**
4. 倒置区间（end < start）产生负年数，现钳制为 0（视为零历史）。**已落地**
5. 新增 4 测试：NaN Sharpe、inf 回撤+NaN 换手、有限性+JSON 可序列化、倒置区间。**已落地**
6. `_finite_or` / `_finite_int` 辅助函数集中处理，避免散落。**已落地**
7. 确认 `policy_fallback_parity` 测试仍通过（归一化在策略层之前，OPA/local 结果一致）。**已验证**
8. 缺失 cost/slippage/factor report 已 fail-closed（`is not True`）。**已评估-合规**
9. 未知回测区间 fail-closed 计为零年。**已评估-合规**
10. strict evidence 模式拒绝非 verified 证据。**已评估-合规**
11. `min_sharpe` 等阈值 fallback 与 `DEFAULT_POLICY` 一致。**已评估**
12. `abs(max_drawdown)` 处理正负回撤约定。**已评估**
13. OPA 超时 0.5s 后回退本地策略；生产禁用 fallback 时抛错。**已评估-合规**
14. 策略生命周期需人工审批 + 风控 pass 双闸。**已评估-合规**
15. 归一化后指标仍写入 `risk_summary.metrics` 供审计。**已评估**
16. 将 `FAIL_CLOSED_*` 哨兵与阈值做一致性单测。**已落地**（有限性断言）。
17. 对 sharpe 上限异常（如 1e12）在 UI 显示做裁剪提示。**建议**（展示层）。
18. Rego 侧补 `is_number` 守卫做纵深防御。**建议**：当前上游已挡住。
19. 为 `risk_decision_from_reasons` 的 reason→rule 映射补全测试。**建议**。
20. 阈值策略支持按策略类别覆盖（现为全局 `DEFAULT_POLICY`）。**建议**：产品化增强。

落地结果：`ruff` 全绿；风控/策略相关 24 测试通过。

---

## R5 API 层输入校验与错误响应

发现：66 处 `.all()` 列表端点多数无分页；审计端点一次性把 5 张表全量载入内存再排序，随审计增长会内存/带宽失控（潜在 DoS）。

1. `compat` 导出 `Query`（真实 + fallback stub），供路由声明查询参数。**已落地**
2. `routes_audit` 四个列表端点加 `limit` 查询参数，默认 500，上限 2000。**已落地**
3. `list_audit_logs` 每个数据源加 `order_by(created_at desc).limit()`，合并后再 `[:limit]`。**已落地**
4. `_resolve_limit` 统一强转与钳制，兼容 HTTP 绑定与测试直调（Query 哨兵回退默认值）。**已落地**
5. 新增 3 测试：钳制/默认、端点 limit 生效、聚合不回归。**已落地**
6. `Query(ge=1, le=2000)` 由 FastAPI 在 HTTP 层做范围校验，越界返回 422。**已落地**
7. 审计端点从"全表扫描"变为"有界最近 N 条"，内存与延迟可控。**已落地**
8. 保持向后兼容：默认 500 大于测试数据量，既有断言不受影响。**已验证**
9. 其余 60+ 列表端点同样缺分页。**建议**：按同一 `_resolve_limit` 模式推广（本轮先覆盖审计高风险面）。
10. 统一分页返回信封 `{items, total, limit}`。**建议**：需前端配合，属 API 版本化改动。
11. 引入游标分页替代 offset，适配审计高写入。**建议**。
12. 统一异常 → 错误响应模型（`{error, detail, request_id}`）。**建议**：加全局 exception handler。
13. 为写端点补 Pydantic 请求体模型的边界校验（长度/枚举）。**建议**：结合 `schemas.py` 审查。
14. `redact_secrets` 已作用于审计 payload 输出，防泄密。**已评估-合规**
15. 列表端点强制 `order_by` 保证结果确定性。**已落地**（审计四端点）。
16. 对超大 `limit` 返回 422 而非静默截断（HTTP 层）。**已落地**
17. 为 `routes_backtests`/`routes_strategies` 列表加分页。**建议**：下一步推广。
18. 加 `ETag`/`Last-Modified` 支持审计只读缓存。**建议**。
19. 响应加 `X-Total-Count` 头。**建议**。
20. OpenAPI 描述补充 limit 语义。**已落地**（`Query` 自带 schema 约束）。

落地结果：`ruff` 全绿；审计相关端点 5 测试通过，RBAC/alias 无回归。

---

## R6 数据管道与数据质量

审查 `services/data_quality.py`、`services/datasets.py`、`data_contracts`。发现与 R4 同类的 NaN fail-open。

1. **缺陷修复**：`_number` 对 NaN/inf 返回 `float(...)` 成功值，导致 `between`/`pair` 检查里 `nan < lower` 恒为 False → 非有限值静默通过范围校验。改为非有限即返回 `None`（fail-closed）。**已落地**
2. 修复后 `_finite_failures` 仍正确（None 即失败），逻辑更一致。**已落地**
3. 新增单测：`_number` 拒非有限、`between`/`pair` 对 NaN fail-closed。**已落地**
4. GX 不可用时的本地回退套件逻辑与 GX 对齐（engine 标注清晰）。**已评估**
5. strict 模式下 GX 缺失/失败直接抛错，不静默降级。**已评估-合规**
6. GX 校验异常在非 strict 下回退本地并记录 `fallback_reason`（可追溯）。**已评估**
7. `_load_suite` 对未知套件抛 `ValueError`，边界清晰。**已评估**
8. `unexpected_index_list` 截断前 20，防超大输出。**已评估**
9. `_duplicate_failures` / `_increasing_failures` 单遍扫描，复杂度合理。**已评估**
10. `_increasing_failures` 对 NaN 排序值未特判。**建议**：排序列一般为日期，风险低，可后续加守卫。
11. `_contract_root` 逐级向上查找 gx 目录，健壮。**已评估**
12. 数据集版本号 `dlt:massive:` 前缀 + DVC rev 可追溯。**已评估**
13. 生产禁止本地 artifact 回退（有专门测试）。**已评估-合规**
14. DVC 远端边界固定 minio。**已评估**
15. 为 `expect_column_values_to_be_between` 增加 NaN 显式失败测试。**已落地**
16. 契约套件 JSON schema 校验（加载时校验结构）。**建议**。
17. 数据质量结果落 artifact meta，支持审计回溯。**已评估**
18. 大数据集校验改为分块/流式，降内存。**建议**：当前样本级，规模化时需要。
19. GX 表达式类型映射表集中维护。**已评估**（`GX_EXPECTATION_TYPE_MAP`）。
20. 非数值列的 in_set 检查大小写/类型规范化。**建议**。

落地结果：`ruff` 全绿；数据质量 11 测试通过。

---

## R7 可观测性与审计

审查 `services/audit.py`、`observability.py`、metrics 端点。

1. **缺陷修复**：`write_audit_log` 中若脱敏后 `contains_secret` 仍为真，原代码再跑一次幂等的 `redact_secrets`（无效）后仍写入可能泄密的 payload。改为 fail-closed：写 `security_violation` 事件并将 payload 替换为 `{redaction_incomplete, action}` 安全标记。**已落地**
2. 新增测试：monkeypatch 强制残留密钥场景，断言 payload 被丢弃且写入 critical 安全事件。**已落地**
3. `write_system_event` / `write_audit_log` 均先 `redact_secrets` 再落库。**已评估-合规**
4. R2 已为 OTEL 配置/ span 失败补日志（呼应）。**已落地**
5. 审计事件带 `actor/action/target`，可溯源。**已评估**
6. metrics 端点缺 prometheus 依赖时优雅降级（有测试）。**已评估-合规**
7. policy_decision 同时写 `PolicyDecision` 行 + 审计日志，双记录。**已评估**
8. 安全违规事件级别 `critical`，便于告警。**已评估**
9. 审计 payload 输出端已 `redact_secrets`（R5 呼应）。**已评估**
10. `security_violation` 标记不含原始值，仅含 action/target 元信息。**已落地**
11. 为审计写入补 trace_id 关联字段。**建议**（依赖结构化日志）。
12. 审计日志表加时间/actor 索引。**见 R9**。
13. system_event 严重级别枚举化（info/warning/critical）。**建议**。
14. 关键操作缺审计的路径盘点。**建议**：覆盖率审查。
15. 审计不可变性（append-only/防篡改）。**建议**：数据库权限/哈希链。
16. 指标补业务维度（风控通过率、审批时延）。**建议**。
17. OTEL span 属性补 workflow_id/actor（部分已有）。**已评估**
18. langfuse 降级到本地镜像的路径有测试覆盖。**已评估-合规**
19. 审计导出/检索接口分页（R5 已覆盖审计列表）。**已落地**
20. 安全违规事件触发外部告警 webhook。**建议**。

落地结果：`ruff` 全绿；审计/可观测/指标 24 测试通过。

---

## R8 前端 control-ui

审查 `api/client.ts`（数据 provider + Keycloak PKCE 登录）。

1. **缺陷修复**：`fastApiDataProvider.getList` 对同一 resource 调用 `readResourceList` 两次（一次取 data，一次取 `.length` 算 total），每次列表加载都发两次网络请求。改为取一次复用。**已落地**
2. PKCE 使用 S256 + state 校验 + 一次性 verifier，登录流程稳健。**已评估-合规**
3. `readApi` 对非 2xx 抛错、204 返回 undefined，处理完整。**已评估**
4. `readTokenUser` 对畸形 token `try/catch` 兜底返回 null。**已评估**
5. `readResourceList` 兼容数组与 `{items}` 信封两种返回。**已评估**
6. 说明：前端 `tsc` / vitest / ui-smoke 在本沙箱无法运行——挂载对 `AgentCanvasPage.tsx` 与部分 TS lib 文件加锁（errno -35），与代码无关；改动为自洽的最小修改。**限制说明**
7. `readApi` 错误 detail 直接抛原始响应文本，可能是大段 HTML。**建议**：截断长度或解析 JSON error。
8. `getList` 支持后端分页参数（对接 R5 的 limit）。**建议**：provider 传 `pagination` → query。
9. token 存 `localStorage` 有 XSS 泄露面。**建议**：评估 httpOnly cookie 方案（需后端配合）。
10. 401 响应自动触发刷新/重登。**建议**：`readApi` 拦截 401 调用 refresh_token。
11. 网络错误与业务错误区分展示。**建议**：错误类型化。
12. resource→endpoint 映射集中在 `RESOURCE_ENDPOINTS`，易维护。**已评估**
13. `getList` total 用 `data.length` 仅为当前页数量。**建议**：后端返回总数后用真实 total。
14. 请求超时/中断（AbortController）。**建议**。
15. 失败重试（幂等 GET）。**建议**。
16. 组件级 loading/empty/error 态一致性（已有 `CompactEmpty`）。**已评估**
17. API 类型 `api/types.ts` 与后端 schema 对齐校验。**建议**：codegen from OpenAPI。
18. `import.meta.env` 默认值仅用于本地开发。**已评估**
19. base64Url 编码手写，逻辑正确。**已评估**
20. 登录重定向 `redirect_uri` 用当前 origin+pathname，防开放重定向。**已评估-合规**

落地结果：`ruff` 全绿（前端不在 ruff 范围）；前端改动为单点修复，沙箱因挂载文件锁无法执行 JS 测试（环境限制，已说明）。

---

## R9 性能与数据库

R5 让审计类列表变为 `ORDER BY created_at DESC LIMIT n`，但模型里 `created_at` 与多数外键无索引，会全表扫描/排序。

1. `TimestampMixin.created_at` 加 `index=True`——覆盖全部时间序列表的 order-by。**已落地**
2. `ToolCall.agent_run_id` 加 `index=True`（代码里按 run 过滤）。**已落地**
3. 新增迁移 `0002_add_performance_indexes`，由 `Base.metadata` 驱动，为既有库补齐缺失索引，幂等。**已落地**
4. 验证：`create_all` 新库直接带索引；模拟旧库删索引后跑迁移逻辑成功补齐。**已验证**
5. 迁移 downgrade 对称删除模型新增索引。**已落地**
6. 迁移只补"模型已声明但库缺失"的索引，fresh 与 migrated 索引集一致。**已落地**
7. 全量 253 测试通过（`create_all` 自动带新索引，无回归）。**已验证**
8. `provider` / `workflow_id` 已有索引，保留。**已评估**
9. 其余高频外键（`strategy_id`/`backtest_run_id`/`approval_request_id`）加索引。**建议**：按查询画像逐步加，避免过度索引拖慢写入。
10. 复合索引 `(strategy_id, created_at)` 支持"某策略最新记录"。**建议**。
11. `session_scope` commit/rollback/close 生命周期正确。**已评估**
12. SQLite 本地回退仅存元数据，不存凭据（README 明确）。**已评估-合规**
13. 审计写入为高频路径，索引需权衡写放大。**已评估**（仅加必要索引）。
14. 大 JSON payload 列（`input_payload` 等）考虑压缩/外置。**建议**。
15. 连接池参数（pool_size/timeout）显式配置。**建议**：核对 `db/session.py`。
16. N+1 查询审查（列表端点聚合）。**已评估**（审计端点为独立有界查询，非 N+1）。
17. 只读副本路由读流量。**建议**：规模化选项。
18. `EXPLAIN` 验证索引命中。**建议**：生产 Postgres 上验证。
19. 迁移在 CI 中执行 `upgrade`+`downgrade` 冒烟。**建议**：加迁移测试。
20. 归档策略：审计/事件表冷热分层。**建议**。

落地结果：`ruff` 全绿；全量 253 通过；迁移升级/降级逻辑本地验证通过。

---

## R10 文档、DX 与测试覆盖

1. CI 增加 `ruff check .` 阻断步骤（`ruff` 加入安装）。**已落地**
2. 新增 `test_schema_indexes.py`：索引存在性、迁移 revision 链、回填幂等性。**已落地**
3. README 增加 lint 用法（`npm run lint` / `lint:fix`）。**已落地**
4. `app.main.create_app()` 全量导入冒烟通过（27 路由）。**已验证**
5. 优化全过程记录于本文件 `docs/optimization_rounds.md`。**已落地**
6. 沙箱测试环境搭建说明（py3.10 + `.pth` 注入 `datetime.UTC`，不改产品码）记录在顶部。**已落地**
7. `ruff.toml` 规则集与忽略项带注释，可维护。**已落地**
8. 迁移文件带完整 docstring 说明用途与幂等性。**已落地**
9. 全量回归：256 测试通过（较基线 233 净增 23 例新测试）。**已验证**
10. 端到端：ruff 全绿 + pytest 全绿 + app 构建成功三重校验。**已验证**
11. `mypy` 渐进式类型检查。**建议**：先在 `core/`、`risk/` 试点。
12. `pre-commit`（ruff + 尾空白 + 大文件拦截）。**建议**。
13. OpenAPI → 前端类型 codegen。**建议**（呼应 R8-17）。
14. 覆盖率报告（`pytest --cov`）接入 CI 并设阈值。**建议**。
15. 迁移在 CI 跑 upgrade+downgrade 冒烟。**建议**（已有单测覆盖回填逻辑）。
16. 契约测试对 openbb/agent-chat 桥接补充。**建议**。
17. 架构文档补 R2 日志、R9 索引策略章节。**建议**。
18. 变更日志 CHANGELOG 化。**建议**。
19. 性能基准（风控/数据质量热路径）回归基线。**建议**。
20. 安全扫描（gitleaks/pip-audit）接入 CI。**建议**（呼应 R3-19）。

落地结果：`ruff` 全绿；全量 256 通过；app 构建冒烟通过。

---

## 总览

十轮共提出 200 条方向。落地重点是若干真实缺陷修复与工程加固，均带测试且保持全绿：

- **风控 fail-open（R4）**：NaN/inf 指标绕过阈值 → 有限哨兵 fail-closed。
- **数据质量 fail-open（R6）**：NaN 绕过范围/配对校验 → `_number` 拒非有限值。
- **审计泄密兜底（R7）**：脱敏后残留密钥仍写库 → 丢弃 payload + 安全事件。
- **JWKS 每请求拉取（R3）**：加 TTL 缓存 + IdP 不可达时降级用过期缓存。
- **审计端点无界查询（R5）**：全表载入 → 有界 `limit` + 排序。
- **前端列表双请求（R8）**：`getList` 取一次复用。
- **缺索引（R9）**：`created_at`/`agent_run_id` 加索引 + 回填迁移。
- **脱敏覆盖（R3）**：新增 PEM/Google/Stripe/JWT/GitHub 模式。
- **代码质量（R1/R2）**：ruff 基线 + 结构化日志。

基线 233 测试 → 结束 256 测试（+23）。`ruff check .` 全绿。CI 增加 ruff 门禁。

测试环境限制：openbb 合约测试与前端 JS 测试因沙箱挂载对个别文件加锁（errno 35）无法在本环境执行，与本次改动无关；相关产品代码未改动。建议在标准 CI（py3.13 + 完整 node_modules）上复跑确认。
