# Source Scope

This skill is intentionally limited to public project documentation that is tracked in the repository and suitable for publication. It should help another AI answer `cfquant` usage and compatibility questions without reading local private state.

## Public Source Set

Use the facts summarized in this skill from these public docs:

| Source doc | Public-doc role |
| --- | --- |
| `README.md` | Project positioning, requirements, installation modes, Python entrypoint, Web Console overview, doc index. |
| `docs/外部Python接入.md` | External Python install, imports, `transport=auto`, manual `configure()`, environment variables, troubleshooting. |
| `docs/QMT函数封装能力清单.md` | Big-QMT bridge positioning, callable boundary, implemented capabilities, conditional capabilities, Web API status. |
| `docs/xtdata平替追踪.md` | `xtquant.xtdata` compatibility state, implemented and conditional `xtdata` groups, unsupported MiniQMT client semantics. |
| `docs/xttrader平替追踪.md` | `XtQuantTrader` and callback compatibility state, implemented trading/query methods, conditional account/business methods. |
| `docs/miniQMT迁移到大QMT指南.md` | Migration scope, workflow, mode selection, account routing, field mapping, latency validation, migration order. |
| `docs/QMT部署教程*.md`, `docs/通用模式部署指南.md`, `docs/极致模式部署指南.md`, `docs/高级模式部署指南.md` | Deployment walkthroughs and mode-specific QMT script choices. |
| `docs/Web账号运行配置说明.md` | Account binding, account type, QMT directory, `bridge_id`, account routing, multi-account behavior. |
| `docs/运维与更新.md`, `docs/版本日志.md` | Maintenance, update/rollback concepts, recent published changes. |
| `web_dashboard/app.js` public API-debug metadata | Shipped Web Console endpoint list, field labels, parameter docs, return-field docs, and callback event examples. Use only the documented debug metadata, not unrelated implementation details. |

The source docs report these update anchors:

- `docs/QMT函数封装能力清单.md`: updated 2026-08-18.
- `docs/xtdata平替追踪.md`: updated 2026-08-13.
- `docs/xttrader平替追踪.md`: updated 2026-07-08.

## Exclusion Rule

Do not consult or summarize files ignored by the project `.gitignore`, even if they exist locally. Do not use ignored local artifacts as evidence for public API behavior. This excludes local runtime state, generated packages, credentials, upload data, logs, local databases, private notes, and ignored website source material.

If a user asks for information that would require ignored/private files, answer with a boundary statement such as:

> The public docs packaged with this skill do not cover that detail. I can only answer from the published/tracked docs unless you explicitly provide the source material.

## Evidence Standard

- Use `已实现` only when the public docs mark the capability as implemented.
- Use `条件可实现` or `兼容入口` when the docs say availability depends on the user's QMT version, broker environment, permissions, or callable exposure.
- Use `不应实现`, `不建议`, or `未完全平替` when the docs define a MiniQMT behavior as outside the big-QMT bridge scope.
- Avoid undocumented exact performance promises. The migration docs recommend measuring min, p50, p95, max, timeout count, and recovery after QMT restart/disconnect in the user's real environment.

## Answering Style

Prefer concise Chinese answers for Chinese user requests. Use exact interface names, file/script names, account type values, and endpoint paths. When giving examples, use placeholder account IDs and make trade examples clearly illustrative.
