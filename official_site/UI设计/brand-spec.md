# cfquant brand spec

本轮方向：专业、克制、工程化的金融工具界面，以浅色工作台为默认，使用低饱和蓝青作为唯一主操作色，并通过克制的中文衬线标题与紧凑正文强化阅读层级。

## Tokens

```css
:root {
  --bg: oklch(97.5% 0.005 245);
  --surface: oklch(99.5% 0.002 245);
  --fg: oklch(18.5% 0.024 248);
  --muted: oklch(45% 0.024 248);
  --border: oklch(85.5% 0.017 248);
  --accent: oklch(42.5% 0.13 232);

  --font-display: "Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif;
  --font-body: "PingFang SC", "Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", Consolas, "Liberation Mono", monospace;
}
```

## Visual Rules

1. 首屏必须直接说明 cfquant 是大 QMT 到 miniQMT 形态的本地桥接层，避免泛 AI / Web3 叙事。
2. 信息结构优先使用表格、列表、状态 pill、运行链路、快速导读和表单，不使用大面积抽象渐变或发光装饰。
3. 卡片和按钮圆角不超过 8px，边框轻、阴影弱，保持金融工程工具的稳定感。
4. 版本号、脚本名、SHA256、错误信息和数据字段使用等宽字体，并允许换行，不能撑破移动端布局。
5. 主要 CTA 每个视口只保留一个实心按钮；论坛、反馈、文档等入口使用次级或幽灵按钮。
6. 页面切换、按钮 hover、弹窗打开使用轻量位移动效；在 `prefers-reduced-motion` 下关闭动画。
