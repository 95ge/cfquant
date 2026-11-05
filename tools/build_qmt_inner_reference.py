"""Generate the offline native QMT directory from the SDK and official HTML snapshots.

python tools/build_qmt_inner_reference.py --source-dir runtime/reports/inner_api_docs
Only function headings and prototypes are extracted; source articles are linked.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import runpy
import sys
from urllib.parse import quote

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qmt_inner_examples import example_for, PARAMETER_HELP

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'cfquant/qmt_inner_catalog.py'
SDK = ROOT / 'cfquant/qmt_inner.py'
OUTPUT = ROOT / 'web_dashboard/qmt-inner-api-data.js'
GROUPS = dict(system='系统与会话', market='行情与数据', trade='交易',
              callbacks='交易回调', reference='扩展数据与因子')
FALLBACK = {
    'set_account': ('设置交易回报订阅账号', 'ContextInfo.set_account(accountid)'),
    'set_universe': ('设置策略证券池', 'ContextInfo.set_universe(stock_list)'),
    'get_universe': ('获取策略证券池', 'ContextInfo.get_universe()'),
    'get_smart_algo_param': ('获取智能算法参数', ''),
}


def sdk_nodes():
    return {cls.name: {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
            for cls in ast.parse(SDK.read_text(encoding='utf-8')).body if isinstance(cls, ast.ClassDef)}


def signature_and_parameters(node, path):
    if node is None:
        return path + '(*args, **kwargs)', [
            dict(name='*args', default='按原生重载传入', help='按大 QMT 原型的位置顺序传参；需要的 ContextInfo 可由桥接端补入。'),
            dict(name='**kwargs', default='可省略', help='关键字参数由终端原生函数解释；不同版本的重载建议使用位置参数。')]
    args = node.args
    signature = path + '(' + re.sub(r'^self,? ?', '', ast.unparse(args)) + ')'
    defaults = [None] * (len(args.args) - len(args.defaults)) + args.defaults
    parameters = [dict(name=arg.arg, default=ast.unparse(default) if default is not None else '必填',
                       help=PARAMETER_HELP.get(arg.arg, '含义与取值沿用对应的大 QMT 原型。'))
                  for arg, default in zip(args.args, defaults) if arg.arg != 'self']
    if args.vararg:
        parameters.append(dict(name='*' + args.vararg.arg, default='可省略', help='保留原生可选位置参数及重载顺序。'))
    if args.kwarg:
        parameters.append(dict(name='**' + args.kwarg.arg, default='可省略', help='重载支持范围以当前 SDK 签名及 QMT 终端为准。'))
    return signature, parameters


def official_metadata(document, name, url):
    pattern = re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)')
    headings = document.select('h2, h3, h4')
    heading = next((h for h in headings if pattern.search(h.get_text())), None)
    if heading is None:
        mention = document.find(string=pattern)
        if mention:
            heading = mention.find_previous(re.compile(r'^h[234]$'))
    if heading is None:
        if name not in FALLBACK:
            raise ValueError('Missing official heading: ' + name)
        title, prototype = FALLBACK[name]
        return title, prototype, url
    title = heading.get_text(' ', strip=True).lstrip('# ')
    title = re.split(r'\s*-\s*', title, maxsplit=1)[-1]
    if not pattern.search(heading.get_text()):
        title = FALLBACK.get(name, (name, ''))[0]
    parts = []
    for sibling in heading.next_siblings:
        if getattr(sibling, 'name', '') in ('h2', 'h3', 'h4'):
            break
        text = sibling.get_text() if hasattr(sibling, 'get_text') else str(sibling)
        if text.strip() in ('示例', '示例：', '示例:'):
            break
        parts.append(text)
    text = '\n'.join(parts)
    text = re.sub(r'#[^\n]*', '', text)
    match = re.search(r'(?:ContextInfo\.)?' + re.escape(name) + r'\s*\(', text)
    prototype = ''
    if match:
        depth = 1
        end = match.end()
        while end < len(text) and depth:
            depth += (text[end] == '(') - (text[end] == ')')
            end += 1
        if depth == 0:
            prototype = re.sub(r'\s+', ' ', text[match.start():end]).strip()
    return title, prototype or FALLBACK.get(name, ('', ''))[1], url + '#' + quote(heading['id'])


def build(source_dir):
    catalog = runpy.run_path(str(CATALOG))
    classes = sdk_nodes()
    documents = {category: BeautifulSoup((source_dir / page).read_text(encoding='utf-8'), 'html.parser')
                 .select_one('.theme-default-content') for category, page in catalog['INNER_CATEGORIES'].items()}
    if any(document is None for document in documents.values()):
        raise ValueError('Missing official document content')
    entries = []
    methods = list(catalog['INNER_METHODS'].items()) + [(('callbacks', name), 'callback') for name in catalog['INNER_CALLBACKS']]
    for (category, name), owner in methods:
        url = catalog['INNER_DOC_ROOT'] + catalog['INNER_CATEGORIES'][category]
        title, native, url = official_metadata(documents[category], name, url)
        signature, parameters = signature_and_parameters(classes['Qmt' + category.title()].get(name), 'qmt.' + category + '.' + name)
        note = 'QMT 已登录并运行更新后的 cfquant 桥接策略时可调用；是否存在请用 qmt.capabilities() 查询。'
        if owner == 'context_arg':
            note += ' ContextInfo 可省略，由桥接端补入。'
        if category == 'reference':
            note += ' 需要 QMT 端已配置对应扩展数据或因子；K 线偏移相对于桥接策略当前上下文。'
        if category == 'callbacks':
            signature = 'qmt.callbacks.' + name + '(callback)'
            parameters = [dict(name='callback', default='必填', help='外部 Python 函数；按原生回调顺序接收参数，首个参数为当前 qmt.context 代理。')]
            note += ' 只接收当前桥接策略订阅账号产生的回报；注册不会生成交易事件。'
        example, example_title = example_for(category, name)
        entries.append(dict(id='qmt_inner.' + category + '.' + name, module='qmt_inner', category=category,
            group=GROUPS[category], name=name, title=title, description=title + '。通过 QmtInnerApi 的 ' + category + ' 分类调用。',
            status='native', source=url, signature=signature, nativeSignature=native, parameters=parameters,
            usage='函数名和交易枚举沿用大 QMT，返回值保留原生语义。', note=note, example=example, exampleTitle=example_title,
            resultHelp='原生交易对象保留 m_ 字段，支持属性和字典访问；DataFrame、Series、NumPy 数组通过协议恢复。',
            resultRows=[['原生结果', '沿用 QMT 返回值；不转换为 XtOrder / XtPosition，也不推测委托编号。'],
                        ['接口缺失或调用错误', '明确抛出异常；不会切换接口或自动重发交易。']], orderFields=[],
            related=['qmt_inner.system.QmtInnerApi', 'qmt_inner.system.capabilities']))
    for name, node_name, title in [('QmtInnerApi', '__init__', '连接大 QMT 内置接口'),
                                  ('capabilities', 'capabilities', '查询终端接口能力'), ('close', 'close', '关闭会话并清理订阅')]:
        signature, parameters = signature_and_parameters(classes['QmtInnerApi'][node_name], name if name == 'QmtInnerApi' else 'qmt.' + name)
        example, example_title = example_for('system', name)
        entries.insert(0 if name == 'QmtInnerApi' else len(entries), dict(
            id='qmt_inner.system.' + name, module='qmt_inner', category='system', group=GROUPS['system'],
            name=name, title=title, description=title, status='native', source=catalog['INNER_DOC_ROOT'] + 'start_now.html',
            signature=signature, nativeSignature='', parameters=parameters, usage='from cfquant import QmtInnerApi；独立于 XtQuantTrader 使用。',
            note='面向外部数据查询、研究和实盘交易。已登记 %s 个原生方法及 %s 个回调；核心查询、行情订阅和定时器已通过华泰模拟终端实测，未对全部方法实测。' % (len(catalog['INNER_METHODS']), len(catalog['INNER_CALLBACKS'])),
            resultHelp='默认自动选择通信方式。account_id / account_type 用于选择 Web 账号绑定；交易函数仍按原生要求传入账号。',
            resultRows=[['capabilities()', '逐分类返回方法是否存在；存在性不等于已实测或当前模型可执行。'],
                        ['close()', '清理本会话行情订阅、schedule_run 定时器和回调；失败可再次关闭。'],
                        ['ContextInfo', 'qmt.context 是桥接策略上下文代理，不是新建的独立策略。']],
            orderFields=[], example=example, exampleTitle=example_title, related=['qmt_inner.market.get_full_tick', 'qmt_inner.trade.get_trade_detail_data']))
    for entry in entries:
        ast.parse(entry['example'], filename=entry['id'])
    payload = dict(groups=GROUPS, methodCount=len(catalog['INNER_METHODS']), callbackCount=len(catalog['INNER_CALLBACKS']),
                   catalogSha256=hashlib.sha256(CATALOG.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
                   sdkSha256=hashlib.sha256(SDK.read_text(encoding='utf-8').encode('utf-8')).hexdigest(), entries=entries)
    return '// Generated by tools/build_qmt_inner_reference.py; edit its sources.\nwindow.CFQUANT_QMT_INNER_API = ' + json.dumps(payload, ensure_ascii=False, indent=2) + ';\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = build(args.source_dir)
    if args.check:
        raise SystemExit(0 if OUTPUT.exists() and OUTPUT.read_text(encoding='utf-8') == content else 'Native QMT directory is outdated')
    OUTPUT.write_text(content, encoding='utf-8')
    print('Generated native QMT directory from current SDK catalog')
