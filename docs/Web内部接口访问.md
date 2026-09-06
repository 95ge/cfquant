# Web 内部接口访问

Web 服务将访问能力分为三类：

| 类型 | 凭据 | 当前接口 | 用途 |
| --- | --- | --- | --- |
| 公开只读 | 无 | `GET /api/health` | 存活检查 |
| 内部只读 | `X-CFQuant-Internal-Key` | `GET /api/internal/runtime-route` | 识别当前共享行情源的桥接和运行模式 |
| 管理与业务 | 主 API Key 或网页登录令牌 | 原有接口 | 配置、账户、行情、交易和运维操作 |

内部密钥由 Web 服务首次启动时自动生成，默认保存在：

```text
runtime/config/cfquant_internal_api_key
```

该文件位于运行目录并已被 Git 忽略。也可以通过环境变量指定固定密钥或其他密钥文件：

```text
CFQUANT_INTERNAL_API_KEY=your-internal-secret
CFQUANT_INTERNAL_API_KEY_FILE=D:\cfquant-runtime\internal-api-key
```

请求示例：

```http
GET /api/internal/runtime-route HTTP/1.1
Host: 127.0.0.1:8765
X-CFQuant-Internal-Key: cfqi_xxx
```

接口只返回 `bridge_id`、`mode`、`transport`、通道和在线状态，不返回资金账号、QMT 目录、主 API Key 或网页登录信息。内部密钥仅对白名单路径有效，不能用于访问 `/api/config` 的完整内容、账户接口或交易接口。

`cfquant/tests/2_数据获取测试.py` 默认使用 `auto` 通信模式。启动时会读取本机内部密钥并请求该接口，以中文显示 Web 当前识别到的行情源；如果 Web 尚未启动或接口不可用，则继续使用 cfquant 原有的自动发现机制。
