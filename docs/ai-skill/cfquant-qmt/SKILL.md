---
name: cfquant-qmt
description: Answer cfquant QMT bridge API, deployment, migration, and xtquant compatibility questions from the published public docs only; excludes ignored local/private artifacts.
metadata:
  short-description: cfquant public API docs
---

# cfquant QMT

Use this skill when the user asks how to use `cfquant`, migrate MiniQMT/`xtquant` code to `cfquant`, call the Python SDK or Web API, choose a QMT deployment mode, understand account routing, or check which QMT/xtquant-compatible capabilities are publicly documented.

## Source Boundary

- Treat this skill and its `references/` files as a self-contained snapshot distilled from the tracked, public project docs.
- Do not use untracked files or any path matched by the repository `.gitignore` as source material for answers under this skill.
- If a requested detail is not covered by the packaged references, say that the published public docs do not specify it. Do not fill gaps from private notes, runtime data, local databases, logs, generated packages, credentials, uploads, or ignored website source files.
- Prefer the published docs over implementation inference. If the user explicitly asks for code debugging or development work, inspect the current tracked source separately and clearly distinguish that from public-doc behavior.
- Do not present `cfquant` as a complete MiniQMT clone. Public docs define it as a bridge around capabilities exposed by the running big-QMT strategy environment.
- Do not execute, encourage, or automate live trading actions without explicit user confirmation. For examples, use placeholders or small illustrative values.

## Routing

- For allowed sources and maintenance scope, read [references/source-scope.md](references/source-scope.md).
- For Python SDK imports, routing, `xtdata`, `XtQuantTrader`, object models, and callbacks, read [references/python-sdk.md](references/python-sdk.md).
- For HTTP and WebSocket endpoints, auth shape, request bodies, response envelope, and event streams, read [references/web-api.md](references/web-api.md).
- For QMT deployment modes, account binding, multi-account routing, startup, and migration order, read [references/deployment-routing.md](references/deployment-routing.md).
- For compatibility states, conditional features, and unsupported MiniQMT semantics, read [references/compatibility-boundaries.md](references/compatibility-boundaries.md).
- For compact sample code and request examples, read [references/examples.md](references/examples.md).

When answering, keep recommendations practical: start users on general mode unless the docs clearly justify advanced mode, route external Python through `transport=auto` by default, and call out public-doc limitations before suggesting workarounds.
