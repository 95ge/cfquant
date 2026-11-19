# 桌面程序与 SDK 的 Python 环境

CFQuant EXE 启动本地服务时始终使用随程序提供的 Python。启动、重启、PipeHub、LTtx 及内置运行时升级不受 SDK 目标解释器设置影响。

桌面设置中的“CFQuant SDK 安装环境”用于选择外部策略所用的 Python，例如 Conda 环境、venv 或 IDE 配置的解释器。选择后点击“安装 / 同步 CFQuant”，将 SDK 安装到该环境。SDK 同步不停止或重启程序自身的服务。

Web 初始化和设置页指定外部 Python 后，会先安装当前版本的 SDK，成功后保存路径；失败会显示错误并保留原设置。选择“仅使用程序自带环境”不向外部 Python 安装 SDK。

已有自定义解释器配置继续作为 SDK 安装目标保留。程序下次启动或重启时使用内置 Python。
