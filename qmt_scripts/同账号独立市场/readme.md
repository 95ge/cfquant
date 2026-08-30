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

这些 `_SH` / `_SZ` 文件是市场入口包装脚本，会先声明市场，再执行原始入口脚本。因此手工复制时，需要确保对应的原始入口脚本也能被找到：

- `CFQUANT_CTYPE_ALL_LOWLAT_SH.py` / `_SZ.py` 需要能找到 `CFQUANT_CTYPE_ALL_LOWLAT.py`
- `CFQUANT_TRADE_LOWLAT_SH.py` / `_SZ.py` 需要能找到 `CFQUANT_TRADE_LOWLAT.py`
- `CFQUANT_LITE_SH.py` / `_SZ.py` 需要能找到 `CFQUANT_LITE.py`

推荐把本目录中的市场脚本和 `qmt_scripts` 目录里的原始入口脚本一起放到 QMT 可访问的位置。

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
- 原始入口脚本是否能被市场入口包装脚本找到。

正常启动后，日志中会出现类似信息：

```text
cfquant ctypes market route market:SH bridge_id:acct_xxx_sh
cfquant lowlat market route market:SZ bridge_id:acct_xxx_sz
```
