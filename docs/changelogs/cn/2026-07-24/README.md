# 2026-07-24 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 从 BNOS 参考项目拷贝并适配可复用 UI 组件](./01_拷贝适配BNOS组件.md)
- [02 Git 仓库初始化与 .gitignore 配置](./02_Git仓库初始化.md)
- [03 综合更新总结](./03_综合更新总结.md)

---

## 修改文件清单

### 新增文件

| 文件 | 改动 |
|------|------|
| `gui/core/utils/__init__.py` | 新建工具包 |
| `gui/core/utils/dialog_utils.py` | 从 BNOS 适配：明亮主题对话框（ThemedDialogBase、themed_input、themed_message、show_text_dialog） |
| `gui/core/utils/file_utils.py` | 从 BNOS 适配：文件操作工具（get_project_root、open_folder、open_terminal、ensure_dir） |
| `gui/core/utils/log_viewer.py` | 从 BNOS 适配：日志查看对话框 |
| `gui/core/toast/__init__.py` | 新建 Toast 包 |
| `gui/core/toast/toast_notification.py` | 从 BNOS 适配：明亮主题 Toast 弹窗（淡入淡出动画、窗口跟随、智能替换） |
| `gui/core/toast/toast_queue_manager.py` | 从 BNOS 适配：Toast 队列管理器（单例、FIFO、堆叠显示、生命周期回调） |
| `gui/core/system/__init__.py` | 新建系统包 |
| `gui/core/system/thread_pool.py` | 从 BNOS 适配：全局固定线程池（单例、QRunnable 封装、完成回调） |
| `gui/core/system/shortcut_manager.py` | 从 BNOS 适配：快捷键管理器（定义、持久化、冲突检测） |
| `docs/changelogs/cn/2026-07-24/01_拷贝适配BNOS组件.md` | 新增详细变更记录 |
| `docs/changelogs/cn/2026-07-24/02_Git仓库初始化.md` | 新增详细变更记录 |
| `docs/changelogs/cn/2026-07-24/03_综合更新总结.md` | 新增：BNOS Runtime 重构、GUI 全面重建、规范更新等综合变更 |
| `docs/changelogs/en/2026-07-24/README.md` | 英文版本更新总览 |
| `docs/changelogs/en/2026-07-24/01_AdaptBNOSComponents.md` | English detailed record |
| `docs/changelogs/en/2026-07-24/02_GitRepoInit.md` | English detailed record |

### 修改文件

| 文件 | 改动 |
|------|------|
| `.gitignore` | 新增 `nodes/` 和 `referencees/` 忽略规则 |
| `docs/changelogs/README.md` | 新增 2026-07-24 索引项 |
| `BNOS-AI伴侣开发方案.md` | AAA 设计补充会话上下文感知；技术决策记录 #14/#15；实施计划更新 |
| `bnos_runtime/engine.py` | 启动流程重写、状态管理、进程管理 |
| `bnos_runtime/pipeline_loader.py` | 依赖顺序加载、自动注入配置 |
| `bnos_runtime/venv_resolver.py` | 自动检测 venv，支持自愈 |
| `gui/core/message_manager.py` | 大幅重写，适配新状态管理系统 |
| `gui/main.py` | 启动流程规范化，移除 BNOS 硬依赖 |
| `gui/main_window.py` | 布局调整，集成 AppState，窗口关闭信号 |
| `gui/pages/chat_page.py` | 聊天气泡 WeChat 风格重构，输入区域改进 |
| `gui/pages/node_page.py` | **节点管理页面重写**：引擎状态栏、启停按钮、状态树 |
| `gui/pages/settings_page.py` | 主题色选择、节点配置编辑、关于页面 |
| `gui/resources/theme.py` | 颜色值从 AppConfig 动态加载，支持运行时切换 |
| `gui/widgets/chat_bubble.py` | 自适应宽度、底部堆叠、用户/AI 左右分区 |
| `gui/widgets/sidebar.py` | 图标文字对齐、选中态高亮 |
| `gui/widgets/status_bar.py` | 实时引擎状态、节点数显示 |
| `canvas_layout.json` | 画布节点布局调整 |
| `node_registry.json` | 更新节点列表（移除 gui_adapter/user_input） |
| `pipeline.json` | 精简配置，移除过时连线 |
| `run.bat` | 支持 --engine-only / --gui-only 参数 |
| `tests/test_llm_aaa_pipeline.py` | 适应合并后的 AAA 节点 |
| `节点开发规范.md` | 新增多端口监听陷阱、超时保护、data_type 同步等章节 |
| `node_config_json_开发规范.md` | 补充 parameters.type 取值规范、resource_limit 必填 |

---

**最后更新**：2026-07-24
