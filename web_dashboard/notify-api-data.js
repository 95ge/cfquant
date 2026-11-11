/* Account messages are independent of QMT trading and monitor notifications. */
window.CFQUANT_NOTIFY_API = [{
  id: 'notify.send', module: 'notify', group: '消息推送', name: 'send',
  title: '发送自定义 Webhook 消息', status: 'extension',
  description: '向企业微信、钉钉、飞书或通用 Webhook 发送用户编写的文本。',
  signature: 'notify.send(message, account_id=None, *, title="", webhook_url=None, provider=None, secret=None, account_type=None, account_key=None, bridge_id=None, timeout=8)',
  parameters: [
    { name: 'message', default: '必填', help: '非空文本，支持换行。企业微信含标题最多 2048 个 UTF-8 字节，其余平台接口上限 20000 字节。' },
    { name: 'account_id', default: 'None', help: '绑定界面填写的资金账号字符串，不是 Webhook 账号或 bridge_id。未指定地址时必须提供此参数或 account_key。' },
    { name: 'title', default: '""', help: '可选标题，最多 200 字符；在平台文本首行显示。' },
    { name: 'webhook_url', default: 'None', help: '本次调用的完整 HTTP(S) 推送地址，必须与 provider 同时提供；完整覆盖账号配置，不修改已保存配置。' },
    { name: 'provider', default: 'None', help: 'wecom＝企业微信，dingtalk＝钉钉，feishu＝飞书，generic＝通用 JSON；必须与 webhook_url 同时提供。' },
    { name: 'secret', default: 'None', help: '本次地址的可选加签密钥，仅钉钉和飞书使用；显式地址不会继承账号密钥。' },
    { name: 'account_type', default: 'None', help: '同资金账号有多个类型时指定 STOCK / CREDIT 等；省略时必须能唯一匹配绑定。' },
    { name: 'account_key', default: 'None', help: '绑定的唯一标识，可从账号配置响应读取。' },
    { name: 'bridge_id', default: 'None', help: '同资金账号有多个部署时用于消歧，一般无需填写。' },
    { name: 'timeout', default: '8', help: 'Webhook 网络超时秒数，1–30；发送失败或结果未知不会自动重试。' },
  ], orderFields: [],
  resultRows: [['sent', '平台确认接收后为 True，不表示最终用户已读。'], ['provider / source', '实际平台与 explicit（本次指定）或 account（绑定配置）。'], ['account_key', '使用账号绑定时返回实际匹配的绑定标识。'], ['http_status', 'Webhook HTTP 响应状态。']],
  resultHelp: '同步等待结果。参数无效抛 ValueError，直接投递失败抛 notify.WebhookError，账号路由错误由 SDK 抛 CfquantError / CfquantTimeout。异常中不包含推送地址或密钥。',
  usage: '在绑定页的“账号消息推送”配置默认地址，已有绑定可“仅保存推送配置”。账号方式需 cfquant Web 和 LTtx 服务在线，QMT 可离线；显式地址由调用程序直接发送。',
  note: '优先级：本次同时指定地址和平台 > 资金账号绑定配置。缺失或多个匹配时明确报错。自定义消息不受监控自动通知的开关、交易时段、去重规则影响。',
  example: `from cfquant import notify

# 换成绑定界面中的资金账号
result = notify.send("策略计算完成\\n今日无新增委托", account_id="YOUR_ACCOUNT_ID", title="策略通知")
print(result)

# 临时改用另一个机器人，不修改账号默认配置
result = notify.send(
    "数据处理完成",
    webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_TOKEN",
    provider="feishu",
    # secret="YOUR_SIGNING_SECRET",  # 机器人启用加签时填写
)
print(result)`,
  http: { method: 'POST', path: '/api/notifications/send', body: { account_id: 'YOUR_ACCOUNT_ID', message: '策略计算完成', title: '策略通知' } },
}];
