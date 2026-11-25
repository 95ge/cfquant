# SDK 自定义消息推送

在“账号绑定 → 编辑 / 添加绑定 → 账号消息推送”中启用默认 Webhook，选择企业微信、钉钉、飞书或通用 JSON，填写机器人完整地址。钉钉、飞书启用加签时还需填写密钥。

新绑定随表单保存；已有绑定可点“仅保存推送配置”，立即生效，不触发 QMT 停止、部署或重启。配置保存在服务端运行配置中，重启后继续使用。编辑时不返回地址、密钥原文，留空保留已保存值；更换平台必须填写新地址，更换地址后需要重新填写加签密钥。“清除已保存的推送配置”需保存后生效。

```python
from cfquant import notify

# account_id 是绑定界面中的资金账号，使用字符串传入。
result = notify.send(
    "策略计算完成\n今日无新增委托",
    account_id="YOUR_ACCOUNT_ID",
    title="策略通知",
)
print(result)

# 本次显式指定地址和平台，优先于账号配置，也可不传账号。
result = notify.send(
    "数据处理完成",
    account_id="YOUR_ACCOUNT_ID",
    webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_TOKEN",
    provider="feishu",
    # secret="YOUR_SIGNING_SECRET",  # 机器人启用加签时填写
)
print(result)
```

平台参数：`wecom` 企业微信，`dingtalk` 钉钉，`feishu` 飞书，`generic` 通用 Webhook。通用请求体为 `{"title":"...","message":"..."}`；三类机器人使用各平台的文本消息格式。[飞书机器人协议](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)、[钉钉机器人协议](https://open.dingtalk.com/document/robots/custom-robot-access)、[企业微信机器人协议](https://developer.work.weixin.qq.com/document/path/91770)。

完整签名：

```python
notify.send(message, account_id=None, *, title="", webhook_url=None,
            provider=None, secret=None, account_type=None,
            account_key=None, bridge_id=None, timeout=8)
```

- 同时提供 `webhook_url` 和 `provider` 时，完整使用本次配置；`secret` 只使用本次提供的值，不继承绑定的密钥，也不更新绑定。
- 未覆盖地址时，必须传资金账号 `account_id` 或绑定唯一标识 `account_key`。按需用 `account_type`、`bridge_id` 消除同号多绑定的歧义。无匹配、多匹配、未启用账号推送或未配置地址均明确报错，不回退到其他账号或全局监控通知。
- 显式地址由运行 SDK 的程序直接访问；账号配置方式通过已配置的 LTtx 进入 A，由 A 的独立通知执行队列发送，不依赖页面或 QMT 在线。远程服务仍使用 `cfquant.configure(host=..., port=..., token=...)` 配置连接。切换连接配置会重置通知连接。
- 这是同步接口，`timeout` 默认 8 秒、范围 1–30 秒；账号方式另预留 5 秒 RPC 等待余量。不自动重试，超时后先核对接收端，避免重复发送。不要在要求低延迟的行情/交易回调中同步等待网络，可放到自己的后台队列。
- 返回 `sent=True` 表示 Webhook 平台确认接收，包含 `provider`、`source`（`explicit` / `account`）、`http_status`；账号方式额外返回 `account_key`。不代表最终用户已读。参数错误抛 `ValueError`；直接发送失败抛 `notify.WebhookError`；账号服务失败按 SDK 返回 `CfquantError` / `CfquantTimeout`。
- 企业微信文本（含标题）最多 2048 个 UTF-8 字节，其余消息正文在本接口限制为 20000 字节；机器人自身的关键词、安全和频率规则仍生效。标题最多 200 字符。
- 自定义消息按调用发送，不受“监控”自动通知的总开关、订阅类型、交易日时段、心跳或去重设置影响。账号推送开关只控制使用该账号默认配置；显式地址仍可独立发送。

HTTP 接口沿用 Web 登录 / API Key 鉴权：

```http
POST /api/notifications/send
Content-Type: application/json
X-API-Key: YOUR_API_KEY

{"account_id":"YOUR_ACCOUNT_ID","title":"策略通知","message":"数据处理完成"}
```

参数与 SDK 相同，响应为 `{ok, data}`。HTTP 请求始终由服务端投递。网页“接口 → 系统 → 发送自定义消息”及“Python API 参考 → 消息推送”提供参数说明与示例。

保存绑定的 `POST /api/account-config` 可带 `notification_webhook`：

```json
{"enabled":true,"provider":"dingtalk","url":"https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN","secret":"YOUR_SIGNING_SECRET"}
```

省略该字段保留原配置。已有绑定也可调用 `POST /api/account-config/webhook`，请求体为 `{"account_key":"绑定标识","notification_webhook":{...}}`，只更新通知配置。传 `{"enabled":false}` 停用但保留地址；`{"clear":true}` 清除配置；`{"clear_secret":true}` 清除加签密钥。更换平台时需要重新提供完整地址。配置读取只返回 `enabled`、`provider`、`url_configured`、`secret_configured`，地址与密钥为空串。

配置和错误响应不会回显机器人令牌；运行配置文件属于私密运行数据，不应进入公开源码或发布包。
