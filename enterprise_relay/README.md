# CFQuant Enterprise Relay Server MVP

这是企业版 Relay Server 的第一阶段实现，提供：

- 服务端首次激活和管理员登录；
- 一次性节点配对、节点心跳和状态查询；
- `market`/`trade` 加密信封的受控转发；
- 企业版行情授权校验、消息大小和队列上限；
- SQLite 状态、审计记录和 Linux/Windows 服务模板。

## 本地启动

首次启动前通过环境变量提供一次性激活码，避免把激活码写入命令行历史：

```powershell
$env:CFQUANT_RELAY_ACTIVATION_CODE = "<one-time-code>"
python -m enterprise_relay.server --data-dir .\relay-data --market-forwarding
```

如需直接提供 HTTPS，可同时指定证书和私钥；生产环境也可以把服务放在 Nginx、Caddy 或企业网关后面：

```powershell
python -m enterprise_relay.server --data-dir .\relay-data --market-forwarding `
  --tls-certfile C:\certs\relay.crt --tls-keyfile C:\certs\relay.key
```

Linux：

```bash
export CFQUANT_RELAY_ACTIVATION_CODE='<one-time-code>'
python -m enterprise_relay.server --data-dir ./relay-data --market-forwarding
```

服务启动后：

1. `POST /api/v1/auth/bootstrap` 使用激活码创建首个 `owner` 管理员；
2. `POST /api/v1/auth/login` 获取服务端管理会话；
3. 管理员调用 `POST /api/v1/admin/pairing` 创建一次性节点配对码；
4. 节点调用 `POST /api/v1/nodes/claim`，随后使用返回的节点令牌发送心跳和消息。

MVP 默认监听 `127.0.0.1:8890`。未提供证书时服务使用 HTTP，生产部署必须使用内置 TLS、HTTPS 反向代理、企业 VPN 或专用网络，并使用 `enterprise_relay/deploy/` 中的 systemd/Windows Service 模板。

完整账号、授权、Linux/Windows 部署和运维边界见项目内部设计文档。
