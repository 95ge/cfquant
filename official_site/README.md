# cfquant 官网原型

这是 `cfquant.org` 官网的前后端分离原型，独立于现有 QMT 策略、桥接服务和 Web 控制台。

## 启动

```powershell
cd D:\兴业证券SMT-Q\python\cfquant2
python official_site\backend\server.py --host 127.0.0.1 --port 8780
```

也可以双击：

```text
official_site\start_site.bat
official_site\stop_site.bat
```

访问：

```text
http://127.0.0.1:8780/
http://127.0.0.1:8780/95ge
```

后台默认账号：

```text
root
root123456
```

可用环境变量覆盖：

```powershell
$env:CFQUANT_SITE_ADMIN_USER="root"
$env:CFQUANT_SITE_ADMIN_PASSWORD="your-strong-password"
```

## 功能范围

- 官网首页默认进入项目介绍，游客可先了解本地桥接能力、下载入口和更新策略；论坛仍可查看内容，点击帖子会进入独立详情页，注册用户可发帖和回复。
- 注册只要求手机号唯一，邮箱可选且只校验唯一性，不做验证码验证。
- 下载页支持本地更新包镜像和外部链接。
- 用户中心支持互动通知、站内通知和已读状态。
- 反馈表单支持登录用户和未登录联系方式，支持上传最多 4 张截图用于问题排查。
- `/95ge` 后台支持运营总览、点击统计、用户管理、讨论管理、反馈处理、站内通知和更新包登记/编辑/上下架/删除。

## 前后端分离配置

前端静态文件在：

```text
official_site\frontend
```

后端 API 在：

```text
official_site\backend\server.py
```

默认本地开发时前端和后端同源运行，不需要改配置。若后续把前端放到独立域名或 Nginx 静态目录，修改：

```text
official_site\frontend\config.js
```

例如：

```javascript
window.CFQUANT_SITE_CONFIG = {
  apiBase: "https://api.cfquant.org",
};
```

## 数据文件

SQLite 数据库会自动创建在：

```text
official_site\data\cfquant_site.sqlite3
```

更新包文件放在：

```text
official_site\packages
```

对外版本接口：

```text
GET /api/releases/latest
GET /api/releases/latest/download
```

控制台更新会优先读取官网最新项目包；官网不可达或未配置本地 zip 包时，再回退到 GitHub。

反馈截图保存目录：

```text
official_site\uploads\feedback
```
