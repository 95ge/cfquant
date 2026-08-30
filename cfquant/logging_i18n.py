# -*- coding: utf-8 -*-
import os
import re
import threading


_LANG_LOCK = threading.RLock()
_LOG_LANGUAGE = ""
_LOG_ENABLED = None


_TRANSLATIONS = [
    (r"^tx trade bridge reload failed:(?P<error>.+)$", "交易桥模块重载失败：{error}"),
    (r"^normal bridge reload failed:(?P<error>.+)$", "普通桥模块重载失败：{error}"),
    (r"^QMT log output enabled=(?P<enabled>.+)$", "QMT 日志输出已切换 enabled={enabled}"),
    (r"^pipe transport reload failed:(?P<error>.+)$", "Pipe 传输模块重载失败：{error}"),
    (r"^pipe bridge reload failed:(?P<error>.+)$", "Pipe 桥接模块重载失败：{error}"),
    (r"^cfquant normal bridge module loaded$", "cfquant 普通桥模块已加载"),
    (r"^cfquant entry version:(?P<version>.+)$", "cfquant 入口版本：{version}"),
    (
        r"^cfquant bridge id:(?P<bridge_id>[^ ]+) normal_channel:(?P<normal>[^ ]+) callback_channel:(?P<callback>.+)$",
        "cfquant 桥接ID={bridge_id} 普通通道={normal} 回调通道={callback}",
    ),
    (
        r"^cfquant normal bridge pump max_count:(?P<count>[^ ]+) max_ms:(?P<ms>.+)$",
        "cfquant 普通桥泵处理上限 条数={count} 耗时={ms}ms",
    ),
    (
        r"^cfquant normal bridge timer scheduled key:(?P<key>[^ ]+) interval_ms:(?P<interval>.+)$",
        "cfquant 普通桥定时器已注册 key={key} 间隔={interval}ms",
    ),
    (
        r"^cfquant normal bridge timer schedule failed:(?P<error>.+)$",
        "cfquant 普通桥定时器注册失败：{error}",
    ),
    (
        r"^cfquant normal bridge context ready version:(?P<version>.+)$",
        "cfquant 普通桥 ContextInfo 已就绪 版本={version}",
    ),
    (
        r"^cfquant normal bridge timer cancel failed:(?P<error>.+)$",
        "cfquant 普通桥定时器取消失败：{error}",
    ),
    (r"^cfquant normal bridge stopped$", "cfquant 普通桥已停止"),
    (
        r"^cfquant callback publish failed event=(?P<event>[^ ]+) error=(?P<error>.+)$",
        "cfquant 回调事件发布失败 event={event} 错误={error}",
    ),
    (r"^cfquant lowlat trade bridge module loaded$", "cfquant 极速交易桥模块已加载"),
    (r"^cfquant lowlat entry version:(?P<version>.+)$", "cfquant 极速交易入口版本：{version}"),
    (
        r"^cfquant bridge id:(?P<bridge_id>[^ ]+) trade_channel:(?P<trade>.+)$",
        "cfquant 桥接ID={bridge_id} 交易通道={trade}",
    ),
    (
        r"^cfquant lowlat trade context ready version:(?P<version>.+)$",
        "cfquant 极速交易桥 ContextInfo 已就绪 版本={version}",
    ),
    (r"^cfquant lowlat trade bridge stopped$", "cfquant 极速交易桥已停止"),
    (r"^cfquant ctypes all-in-one lowlat bridge module loaded$", "cfquant ctypes 单文件低延迟桥模块已加载"),
    (r"^cfquant ctypes all-in-one lowlat entry version:(?P<version>.+)$", "cfquant ctypes 单文件低延迟入口版本：{version}"),
    (
        r"^cfquant ctypes bridge id:(?P<bridge_id>[^ ]+) pipe:(?P<pipe>[^ ]+) normal_channel:(?P<normal>[^ ]+) trade_channel:(?P<trade>[^ ]+) callback_channel:(?P<callback>.+)$",
        "cfquant ctypes 桥接ID={bridge_id} pipe={pipe} 普通通道={normal} 交易通道={trade} 回调通道={callback}",
    ),
    (
        r"^cfquant ctypes trade loop in thread:(?P<thread>[^ ]+) sleep_seconds:(?P<sleep>.+)$",
        "cfquant ctypes 交易循环后台线程={thread} 轮询间隔={sleep}秒",
    ),
    (
        r"^cfquant ctypes lowlat trade loop error:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易循环异常：{error}",
    ),
    (r"^cfquant ctypes lowlat trade loop started in worker thread$", "cfquant ctypes 低延迟交易循环已在后台线程启动"),
    (r"^cfquant ctypes lowlat trade loop entering current QMT thread$", "cfquant ctypes 低延迟交易循环进入当前 QMT 线程"),
    (
        r"^cfquant ctypes lowlat trade dispatch error source=(?P<source>[^ ]+) error=(?P<error>.+)$",
        "cfquant ctypes 低延迟交易请求派发异常 来源={source} 错误={error}",
    ),
    (
        r"^cfquant ctypes lowlat trade timer scheduled key:(?P<key>[^ ]+) interval_ms:(?P<interval>.+)$",
        "cfquant ctypes 低延迟交易定时器已注册 key={key} 间隔={interval}ms",
    ),
    (
        r"^cfquant ctypes lowlat trade timer schedule failed:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易定时器注册失败：{error}",
    ),
    (
        r"^cfquant ctypes lowlat trade timer cancel failed:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易定时器取消失败：{error}",
    ),
    (
        r"^cfquant ctypes normal context ready version:(?P<version>.+)$",
        "cfquant ctypes 普通桥 ContextInfo 已就绪 版本={version}",
    ),
    (
        r"^cfquant ctypes lowlat trade context ready version:(?P<version>.+)$",
        "cfquant ctypes 低延迟交易桥 ContextInfo 已就绪 版本={version}",
    ),
    (r"^cfquant ctypes lowlat trade bridge stopped$", "cfquant ctypes 低延迟交易桥已停止"),
    (r"^cfquant ctypes normal bridge stopped$", "cfquant ctypes 普通桥已停止"),
    (
        r"^cfquant ctypes lowlat callback publish failed event=(?P<event>[^ ]+) error=(?P<error>.+)$",
        "cfquant ctypes 回调事件发布失败 event={event} 错误={error}",
    ),
    (
        r"^stage=request_dequeued raw=(?P<raw>.+)$",
        "阶段=请求出队 raw={raw}",
    ),
    (
        r"^stage=parse_invalid parse_ms=(?P<parse_ms>[^ ]+) raw=(?P<raw>.+)$",
        "阶段=解析失败 解析耗时={parse_ms}ms raw={raw}",
    ),
    (
        r"^stage=request_enqueued_qmt_thread action=(?P<action>[^ ]+) id=(?P<id>.+)$",
        "阶段=请求转入QMT线程 action={action} id={id}",
    ),
    (
        r"^stage=request_received action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) parse_ms=(?P<parse_ms>[^ ]+) params=(?P<params>.+)$",
        "阶段=收到请求 action={action} id={id} 解析耗时={parse_ms}ms 参数={params}",
    ),
    (
        r"^stage=response_ready action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) dispatch_ms=(?P<dispatch_ms>[^ ]+) result=(?P<result>.+)$",
        "阶段=响应已生成 action={action} id={id} 处理耗时={dispatch_ms}ms 结果={result}",
    ),
    (
        r"^stage=response_sent action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) total_ms=(?P<ms>.+)$",
        "阶段=响应已发送 action={action} id={id} 客户端={client_id} 总耗时={ms}ms",
    ),
    (r"^tx trade bridge context ready$", "交易桥 ContextInfo 已就绪"),
    (r"^tx trade bridge stopped$", "交易桥已停止"),
    (
        r"^tx trade bridge started LTtx=(?P<endpoint>[^ ]+) request_channel=(?P<channel>.+)$",
        "交易桥已启动 LTtx={endpoint} 请求通道={channel}",
    ),
    (
        r"^tx trade response_ready action=(?P<action>[^ ]+) id=(?P<id>.+)$",
        "交易请求已生成响应 action={action} id={id}",
    ),
    (
        r"^tx trade request_error action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) error=(?P<error>.+)$",
        "交易请求处理失败 action={action} id={id} 错误={error}",
    ),
    (
        r"^tx trade response_sent action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) total_ms=(?P<ms>.+)$",
        "交易响应已发送 action={action} id={id} 客户端={client_id} 总耗时={ms}ms",
    ),
    (
        r"^query_trade_detail start account=(?P<account>[^ ]+) account_type=(?P<account_type>[^ ]+) detail_type=(?P<detail_type>.+)$",
        "交易明细查询开始 账号={account} 账号类型={account_type} 明细类型={detail_type}",
    ),
    (
        r"^query_trade_detail call failed account=(?P<account>[^ ]+) detail_type=(?P<detail_type>[^ ]+) error=(?P<error>.+)$",
        "交易明细查询调用失败 账号={account} 明细类型={detail_type} 错误={error}",
    ),
    (
        r"^query_trade_detail format failed detail_type=(?P<detail_type>[^ ]+) index=(?P<index>[^ ]+) type=(?P<type>[^ ]+) error=(?P<error>.+)$",
        "交易明细格式化失败 明细类型={detail_type} 序号={index} 数据类型={type} 错误={error}",
    ),
    (
        r"^query_trade_detail done detail_type=(?P<detail_type>[^ ]+) count=(?P<count>.+)$",
        "交易明细查询完成 明细类型={detail_type} 数量={count}",
    ),
    (
        r"^trade detail getattr failed type=(?P<type>[^ ]+) field=(?P<field>[^ ]+) error=(?P<error>.+)$",
        "交易明细读取属性失败 数据类型={type} 字段={field} 错误={error}",
    ),
    (
        r"^trade detail get failed type=(?P<type>[^ ]+) field=(?P<field>[^ ]+) error=(?P<error>.+)$",
        "交易明细 get 读取失败 数据类型={type} 字段={field} 错误={error}",
    ),
    (
        r"^qmt userdata log cleanup log_dir=(?P<dir>.+) retention_days=(?P<days>[^ ]+) deleted=(?P<deleted>[^ ]+) failed=(?P<failed>[^ ]+) dry_run=(?P<dry_run>.+)$",
        "QMT userdata 日志清理完成 目录={dir} 保留天数={days} 删除={deleted} 失败={failed} dry_run={dry_run}",
    ),
    (
        r"^account subscribed account=(?P<account>[^ ]+) client_id=(?P<client_id>.+)$",
        "账号回调已订阅 账号={account} 客户端={client_id}",
    ),
    (
        r"^account unsubscribed account=(?P<account>[^ ]+) client_id=(?P<client_id>.+)$",
        "账号回调已取消订阅 账号={account} 客户端={client_id}",
    ),
    (
        r"^normal bridge started LTtx=(?P<endpoint>[^ ]+) request_channel=(?P<channel>.+)$",
        "普通桥已启动 LTtx={endpoint} 请求通道={channel}",
    ),
    (r"^normal bridge worker is released by quote/timer/handlebar callbacks$", "普通桥 worker 由行情/定时器/handlebar 回调唤醒"),
    (r"^normal bridge context ready$", "普通桥 ContextInfo 已就绪"),
    (r"^normal bridge worker thread started in init context$", "普通桥 worker 线程已在 init context 中启动"),
    (
        r"^normal bridge recv error: (?P<error>.+)$",
        "普通桥接收请求异常：{error}",
    ),
    (
        r"^normal bridge request queued action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) queue_size=(?P<size>[^ ]+) coalesced=(?P<coalesced>.+)$",
        "普通桥请求已入队 action={action} id={id} 队列长度={size} 合并查询={coalesced}",
    ),
    (
        r"^normal bridge request queued action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) queue_size=(?P<size>.+)$",
        "普通桥请求已入队 action={action} id={id} 队列长度={size}",
    ),
    (
        r"^normal bridge request coalesced action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>.+)$",
        "普通桥请求已合并 action={action} id={id} 等待方={waiters}",
    ),
    (
        r"^normal bridge quote subscribed id=(?P<id>[^ ]+) kind=(?P<kind>.+)$",
        "行情订阅已建立 id={id} 类型={kind}",
    ),
    (
        r"^normal bridge whole quote publish enabled id=(?P<id>[^ ]+) internal_id=(?P<internal>.+)$",
        "全推行情发布已开启 id={id} 内部订阅={internal}",
    ),
    (
        r"^normal bridge quote unsubscribed id=(?P<id>.+)$",
        "行情订阅已取消 id={id}",
    ),
    (
        r"^normal bridge worker error source=(?P<source>[^ ]+) error=(?P<error>.+)$",
        "普通桥 worker 异常 来源={source} 错误={error}",
    ),
    (
        r"^normal bridge worker response source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) total_ms=(?P<ms>.+)$",
        "普通桥响应完成 来源={source} action={action} id={id} 总耗时={ms}ms",
    ),
    (
        r"^normal bridge worker coalesced_response source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>[^ ]+) total_ms=(?P<ms>.+)$",
        "普通桥合并响应完成 来源={source} action={action} id={id} 等待方={waiters} 总耗时={ms}ms",
    ),
    (
        r"^normal bridge worker coalesced_error source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>[^ ]+) error=(?P<error>.+)$",
        "普通桥合并请求处理失败 来源={source} action={action} id={id} 等待方={waiters} 错误={error}",
    ),
    (
        r"^normal bridge worker request_error source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) error=(?P<error>.+)$",
        "普通桥请求处理失败 来源={source} action={action} id={id} 错误={error}",
    ),
    (
        r"^normal bridge internal whole quote subscribed id=(?P<id>.+)$",
        "普通桥内部全推行情订阅成功 id={id}",
    ),
    (
        r"^normal bridge internal whole quote subscribe failed: (?P<error>.+)$",
        "普通桥内部全推行情订阅失败：{error}",
    ),
    (
        r"^normal bridge timer scheduled key=(?P<key>.+)$",
        "普通桥定时器已注册 key={key}",
    ),
    (
        r"^normal bridge timer schedule failed: (?P<error>.+)$",
        "普通桥定时器注册失败：{error}",
    ),
    (
        r"^normal bridge send_error action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) error=(?P<error>.+)$",
        "普通桥错误响应已发送 action={action} id={id} 客户端={client_id} 错误={error}",
    ),
    (
        r"^normal bridge callback event sent event=(?P<event>[^ ]+) account=(?P<account>.+)$",
        "普通桥交易回调事件已发送 event={event} 账号={account}",
    ),
    (
        r"^pipe normal bridge started pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>.+)$",
        "Pipe 普通桥已启动 pipe={pipe} 请求通道={channel}",
    ),
    (r"^pipe normal bridge stopped$", "Pipe 普通桥已停止"),
    (
        r"^pipe trade bridge started pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>.+)$",
        "Pipe 交易桥已启动 pipe={pipe} 请求通道={channel}",
    ),
    (r"^pipe trade bridge stopped$", "Pipe 交易桥已停止"),
    (
        r"^pipe connected pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>[^ ]+) bridge_id=(?P<bridge_id>.+)$",
        "Pipe 已连接 pipe={pipe} 请求通道={channel} 桥接ID={bridge_id}",
    ),
    (
        r"^pipe connect/read failed: (?P<error>.+)$",
        "Pipe 连接或读取失败：{error}",
    ),
    (
        r"^pipe push failed: (?P<error>.+)$",
        "Pipe 推送失败：{error}",
    ),
]


def normalize_log_language(value=None):
    value = str(value or "").strip().lower()
    if value in ("en", "english"):
        return "en"
    return "zh"


def normalize_log_enabled(value=None):
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off", "disable", "disabled", "closed", "close"):
        return False
    return True


def get_log_language():
    with _LANG_LOCK:
        if _LOG_LANGUAGE:
            return _LOG_LANGUAGE
    return normalize_log_language(os.environ.get("CFQUANT_QMT_LOG_LANGUAGE") or os.environ.get("CFQUANT_LOG_LANGUAGE") or "zh")


def set_log_language(value):
    global _LOG_LANGUAGE
    lang = normalize_log_language(value)
    with _LANG_LOCK:
        _LOG_LANGUAGE = lang
    return lang


def get_log_enabled():
    with _LANG_LOCK:
        if _LOG_ENABLED is not None:
            return bool(_LOG_ENABLED)
    return normalize_log_enabled(os.environ.get("CFQUANT_QMT_LOG_ENABLED") or os.environ.get("CFQUANT_LOG_ENABLED") or "1")


def set_log_enabled(value):
    global _LOG_ENABLED
    enabled = normalize_log_enabled(value)
    with _LANG_LOCK:
        _LOG_ENABLED = enabled
    return enabled


def translate_log(message, language=None):
    text = str(message)
    if normalize_log_language(language or get_log_language()) == "en":
        return text
    for pattern, template in _TRANSLATIONS:
        match = re.match(pattern, text)
        if not match:
            continue
        try:
            return template.format(**match.groupdict())
        except Exception:
            return text
    return text
