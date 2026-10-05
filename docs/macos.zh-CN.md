# macOS 安装与开发 {#macos-setup}

以下步骤在 Terminal 的 zsh 或 Bash 中执行，涵盖 Python 环境、Web/CLI/MCP
入口以及源码开发。sqlseed 在 macOS、Windows 和 Linux 上使用相同的 Python API。

## 选择 Python 与架构 {#choose-python-and-its-architecture}

需要 Python 3.10 或更高版本；Python 3.12 与兼容性测试环境一致。
从 [python.org](https://www.python.org/downloads/macos/) 或现有包管理器安装维护中的
Python。python.org 的 universal2 安装包同时支持 Intel 和 Apple Silicon。
保留 Apple 管理的 `/usr/bin/python3`，不要替换它。详见
[Python 的 macOS 安装说明](https://docs.python.org/3/using/mac.html)。

```bash
command -v python3
python3 --version
python3 -c 'import platform, sys; print(sys.executable); print(platform.machine())'
```

Apple Silicon 原生 Python 应显示 `arm64`，Intel Python 显示 `x86_64`。
Apple Silicon 使用原生终端和解释器，避免将 Rosetta Python 与 ARM 库混用。
安装了多个解释器时，将后文的 `python3` 替换为目标版本（如 `python3.12`）或完整路径。
激活虚拟环境前，系统中没有 `python` 命令是正常情况。

## 创建新环境 {#create-a-fresh-environment}

在项目目录或专用应用目录中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -c 'import sys; print(sys.executable)'
```

输出的解释器应位于当前目录的 `.venv/bin` 中。虚拟环境不能从 Windows 复制过来，
也不能在不同 Python 架构间直接复用。迁移源码目录时，先将旧 `.venv` 重命名为尚未使用的
备份名称，再用以上命令新建环境。保留数据库和配置文件，只重建虚拟环境。
移动源码目录后，若已安装命令仍引用旧路径，也应重建环境。

## 安装与启动 {#install-and-start}

在激活的环境中安装 Web 与 CLI 两个入口包：

```bash
python -m pip install sqlseed-web sqlseed-cli
python -m pip check
sqlseed --help
sqlseed-web
```

访问 `http://127.0.0.1:8630`，按 Control-C 停止服务。SQLite 使用 Python 内置驱动。
按[快速开始](guide.md#quick-start)创建表并生成数据；只用 Python API 时安装 `sqlseed`。
AI、MCP 与精确版本安装组合见[安装指南](guide.md#installation)。

不激活环境时，也可显式运行 `.venv/bin/python`、`.venv/bin/sqlseed` 与
`.venv/bin/sqlseed-web`。从其他目录调用时使用完整路径，例如
`/Users/yourname/sqlseed-env/.venv/bin/sqlseed`。含空格的路径要加引号。桌面 MCP 客户端可能不继承 Terminal
的 `PATH`，可用下面的命令取得当前环境中 MCP 入口的完整路径：

```bash
python -m pip install mcp-server-sqlseed
python -c 'import sysconfig; from pathlib import Path; print(Path(sysconfig.get_path("scripts")) / "mcp-server-sqlseed")'
```

将输出的完整路径填入客户端的 `command`，例如
`/Users/yourname/sqlseed-env/.venv/bin/mcp-server-sqlseed`，`args` 使用空数组。
不要在该字段中填写 shell 激活命令或字面的 `~`。
可选 AI MCP 的入口是 `mcp-server-sqlseed-ai`；完整配置见 [MCP 指南](guide.md#mcp-server)。

### Intel Mac 的 MCP 依赖 {#intel-macs-and-mcp-dependencies}

MCP 通过 PyJWT 引入 `cryptography`。从 cryptography 49 开始，上游不再支持 Intel
macOS，也不再发布 Intel macOS wheel。单独使用 Core、CLI 和 Web 不需要此依赖。
参见[上游发布说明](https://cryptography.io/en/latest/changelog/#v49-0-0)。

因此，Intel Mac 安装 MCP 或完整开发环境时可能需要在本机编译 cryptography。
编译需要 Xcode Command Line Tools、Rust 和 OpenSSL，工具链架构应与 Python 一致。
已安装 Homebrew 时，先准备上游要求的工具：

```bash
xcode-select --install
brew install rust openssl@3
export OPENSSL_DIR="$(brew --prefix openssl@3)"
```

工具准备好后重新运行安装命令。已有 Command Line Tools 时跳过 `xcode-select --install`。
这些工具只服务于可选依赖的编译，SQLite 与普通 Core/Web 使用不需要它们。
编译失败时参考 [cryptography 编译说明](https://cryptography.io/en/50.0.1/installation/#building-cryptography-on-macos)，
不要通过锁定旧版 cryptography 来绕过。仓库带哈希锁定且限制源码构建范围的 CI 安装策略见
[CI 依赖维护说明](https://github.com/sunbos/sqlseed/blob/main/.github/DEPENDENCIES.md)。

## 源码开发 {#develop-from-source}

克隆仓库并进入根目录，创建新环境。在一次解析中提供全部五个本地包，避免候选插件
从 PyPI 安装另一版本的 Core 或 CLI：

```bash
git clone https://github.com/sunbos/sqlseed.git
cd sqlseed
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,all,docs]' -e './plugins/sqlseed-cli' -e './plugins/sqlseed-ai[dev,mcp]' -e './plugins/mcp-server-sqlseed' -e './plugins/sqlseed-web[dev]'
python -m pip check
```

开发需要 Git 和 Python；前端与 Pages 部署回归使用 Node.js 24。
Make 是便捷入口，也可直接执行底层命令。`make dev-install` 包含文档依赖。

```bash
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
lint-imports
pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
node --test plugins/sqlseed-web/tests/test_*.cjs tests/test_deploy_pages.cjs
python scripts/sync_docs.py --check
python -m mkdocs build --strict
make mutmut
```

外部 PostgreSQL 与真实 LLM 用例在服务不可用时可能跳过，跳过不代表已验证这些服务。
CI 范围与架构矩阵以 [ci.yml](https://github.com/sunbos/sqlseed/blob/main/.github/workflows/ci.yml)
为准。Codecov 汇总 Linux、Windows、原生 Apple Silicon 和 Intel macOS 的 Python 3.12
覆盖率报告，让平台专属分支进入同一覆盖率门禁。完整审查门禁见[贡献指南](https://github.com/sunbos/sqlseed/blob/main/CONTRIBUTING.md)。

## PostgreSQL 测试 {#postgresql-tests}

选择独立的本地 PostgreSQL 测试数据库或 Docker engine。
在开发环境之外使用 PostgreSQL 时，安装 `python -m pip install 'sqlseed[postgres]'`。

已有本地 PostgreSQL 服务时，创建仅供测试的数据库并配置 SQLAlchemy URL。
下面的用户名、密码和端口需要替换为实际测试配置：

```bash
export PG_TEST_URL='postgresql+psycopg://test_user:test_password@127.0.0.1:5432/sqlseed_test'
pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py plugins/sqlseed-web/tests/test_workbench_postgresql_cycles.py -v
```

测试会建表和写入，因此该 URL 必须指向可以丢弃的测试数据库。
配置 `PG_TEST_URL` 后，fixture 直接使用该服务，不启动 Docker。
使用 Docker Desktop 或其他可用的 Docker engine 时，不设置此变量：

```bash
unset PG_TEST_URL
docker info
pytest tests/integration/test_pg_*.py tests/integration/test_url_e2e.py plugins/sqlseed-web/tests/test_workbench_postgresql_cycles.py -v
```

Testcontainers 会创建并清理自己的 PostgreSQL 容器。仅安装 Docker CLI 不够，engine
必须正在运行且可访问。真实模型验收单独执行，见 [AI 集成指南](gemma4-integration.md)。
