# 同账号独立市场部署说明

## 适用场景

有些券商的大 QMT 会把上海市场和深圳市场拆成两个独立交易端，但两个交易端使用同一个资金账号。本目录用于这种场景：

- `000001.SZ` 这类深圳标的自动路由到深圳交易端。
- `601222.SH` 这类上海标的自动路由到上海交易端。
- 账号仍然是同一个账号，系统内部只按标的市场切换交易桥接。

## 网页端配置

在网页的账号绑定页面中：

1. 编辑对应资金账号。
2. 开启“同账号独立市场路由”。
3. 填写“上海交易端目录”和“深圳交易端目录”，建议填写各自 QMT 的 `bin.x64` 目录。
4. `bridge_id` 可以留空，系统会自动生成，例如 `acct_xxx_sh`、`acct_xxx_sz`。
5. 保存绑定。

保存后，系统会分别写入独立配置文件：

- 上海交易端：`cfquant_bridge_config_SH.json`
- 深圳交易端：`cfquant_bridge_config_SZ.json`

这两个 JSON 会声明各自的 `bridge_id`、请求通道和 `market`。

## QMT 端运行哪个脚本

根据当前账号使用的模式选择对应脚本。

### 通用 ctypes / 单文件低延迟模式

- 上海 QMT 运行：`CFQUANT_CTYPE_ALL_LOWLAT_SH.py`
- 深圳 QMT 运行：`CFQUANT_CTYPE_ALL_LOWLAT_SZ.py`

### 高级模式 LTtx 交易端

- 上海 QMT 交易端运行：`CFQUANT_TRADE_LOWLAT_SH.py`
- 深圳 QMT 交易端运行：`CFQUANT_TRADE_LOWLAT_SZ.py`

### 极致模式

- 上海 QMT 运行：`CFQUANT_LITE_SH.py`
- 深圳 QMT 运行：`CFQUANT_LITE_SZ.py`

## 手工复制时的注意事项

这些 `_SH` / `_SZ` 文件现在是完整市场入口，已经内置对应主入口代码，不会在 QMT 运行时读取上层目录里的原始入口脚本。手工复制时只需要复制当前模式对应的市场文件：

- 通用 ctypes：`CFQUANT_CTYPE_ALL_LOWLAT_SH.py` / `CFQUANT_CTYPE_ALL_LOWLAT_SZ.py`
- 高级模式交易端：`CFQUANT_TRADE_LOWLAT_SH.py` / `CFQUANT_TRADE_LOWLAT_SZ.py`
- 极致模式：`CFQUANT_LITE_SH.py` / `CFQUANT_LITE_SZ.py`

通用 ctypes 和高级模式交易端仍按原模式要求部署 `cfquant` 核心包；极致模式市场入口不需要复制 `cfquant` 核心包。

## 账号数据和回调

同账号独立市场开启后，主桥可以只作为账号配置和路由身份存在，上海、深圳两个市场入口分别在线即可。

- 下单、撤单按证券代码市场发送到对应 SH/SZ 子桥。
- 持仓、委托、成交会分别查询 SH/SZ 子桥，并在 Web 端合并展示。
- 资金属于同一个资金账号，Web 端不会把 SH/SZ 两边的资金简单相加；会取第一个成功子桥的资金结果，并保留分市场查询明细用于排查。
- 交易回调按 SH/SZ 子桥分别上报，Web 端按主账号订阅时会同时接收两个子桥的回调。

## 路由规则

系统优先按完整代码后缀判断市场：

- `.SH` 走上海交易端。
- `.SZ` 走深圳交易端。

如果没有后缀，会按代码开头推断：

- `5`、`6`、`9` 开头默认上海。
- `0`、`1`、`2`、`3` 开头默认深圳。

批量下单中如果同时包含上海和深圳标的，系统会自动拆分为两组请求，分别发送到对应交易端，再合并返回结果。

## 排查要点

如果 QMT 日志里仍然显示 `bridge_id=default`，通常说明没有读到对应市场 JSON，重点检查：

- 网页绑定是否已经开启“同账号独立市场路由”并保存。
- SH/SZ 两个 QMT 的 `bin.x64` 目录是否填写正确。
- 对应目录里是否生成了 `cfquant_bridge_config_SH.json` 或 `cfquant_bridge_config_SZ.json`。
- 上海 QMT 是否运行 `_SH.py`，深圳 QMT 是否运行 `_SZ.py`。
- 是否复制的是最新完整市场入口文件，而不是旧包装脚本。

正常启动后，日志中会出现类似信息：

```text
cfquant ctypes market route market:SH bridge_id:acct_xxx_sh
cfquant lowlat market route market:SZ bridge_id:acct_xxx_sz
```
