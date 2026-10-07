# OpenClaw 多实例管理器

`openclaw-instance` 为同一普通用户管理多个 OpenClaw profile：独立配置、凭据、工作区、日志、端口和 systemd 用户服务。创建失败保留数据，删除必须明确指定实例；已有非受管实例只用于端口避让。

适用范围：一台 Linux 服务器、同一可信管理员、自用业务。所有实例共享 OpenClaw 安装版本；同一用户的进程能够访问彼此文件，本项目不提供客户之间的安全隔离。

## 安装

需要 Linux、Bash 5、Node、已安装的 OpenClaw、`jq`、`flock`、`ss`、systemd、`loginctl` 和常见 GNU 工具（coreutils、findutils、util-linux）。脚本拒绝 root 运行，不自动安装依赖或提权。

使用实际运行 OpenClaw 的普通账号，执行：

```bash
bash scripts/install.sh
export PATH="$HOME/.local/bin:$PATH"
openclaw-instance preflight
```

第一次部署，由管理员为该账号启用 linger：

```bash
sudo loginctl enable-linger <运行用户名>
```

然后重新登录该账号。无桌面环境时，确认 `/run/user/$(id -u)` 和用户服务管理器已存在；脚本会在未设置时自动补充 `XDG_RUNTIME_DIR`。不要通过 `sudo openclaw-instance` 操作实例。

`preflight` 检查 CLI 所需能力、用户服务管理器、linger、可发现的已有实例及端口，不创建管理目录。初次 `create` 创建注册表；已存在的管理目录缺少或损坏注册表时不会重新初始化。

已做真实集成验证的版本和验证边界见 [验证记录](docs/verification.md)。其他 OpenClaw 版本先通过能力检查，再在隔离环境运行集成测试；能力检查不是兼容性保证。

## 快速使用

```bash
openclaw-instance create company-a
openclaw-instance create company-b
openclaw-instance list
openclaw-instance status company-a --json
openclaw-instance configure company-a
openclaw-instance restart company-a
openclaw-instance logs company-a -f
```

创建会生成每实例独立 token、只监听 loopback，并等待最多 60 秒验证 Gateway 健康。模型和渠道没有自动配置，健康的 Gateway 不等于能完成模型对话或接收 WhatsApp 消息。

配置渠道时始终带明确 profile，例如：

```bash
openclaw --profile company-a channels login --channel whatsapp
```

`configure` 需要真实交互终端，保留实例锁而不长期持有全局锁。修改模型和渠道后，按需要执行管理器的 `restart`。不要在向导或原生命令中更改受管端口、workspace、日志路径、认证方式或服务身份。

## 命令

| 命令 | 含义 |
|---|---|
| `preflight` | 只读预检，输出 JSON |
| `create NAME` | 创建；已就绪同名实例只返回现状 |
| `list [--json]` | 枚举受管实例，查询实时状态 |
| `status NAME [--json]` | 显示管理阶段、实际服务、健康、配置偏差和路径 |
| `start NAME` | 启动；已 remove 的实例会重新安装服务 |
| `stop NAME` | 停止，保留全部数据和端口 |
| `restart NAME` | 原生停止后启动，并验证健康 |
| `logs NAME [-f]` | 查看最近 100 行；`-f` 跟随文件轮转，服务停机也可读 |
| `configure NAME` | 原生交互配置，结束后检查管理约束 |
| `doctor NAME` | 只读诊断；有偏差或 Gateway 不健康时返回非零 |
| `remove NAME` | 卸载服务，保留数据、记录和端口 |
| `purge NAME --confirm NAME` | 永久删除服务、数据、记录，并释放端口 |

名称为小写字母开头、最长 32 位的小写字母/数字/连字符，`default` 和 `dev` 保留。命令成功返回 0；前置条件、操作或健康验证失败返回非零。`status`/`list` 的非健康实例通过结构化字段报告，查询成功仍可返回 0。

## 目录与状态

```text
~/.local/bin/openclaw-instance
~/.local/state/openclaw-instance-manager/
    instances.json
    manager.lock
    <profile>.lock
~/.openclaw-<profile>/
    .instance-manager-owner
    openclaw.json
    workspace/
    logs/openclaw.log
    ... OpenClaw 自己管理的凭据和会话
```

无需 `/var/lib` 写权限。第一版固定使用真实 HOME 下这些路径；不接受改变配置目录、状态目录、profile、端口、鉴权或服务身份的环境变量。`XDG_CONFIG_HOME`、`XDG_STATE_HOME` 如设置，必须等于对应 HOME 默认目录。

管理目录和实例根目录 `0700`，注册表和配置 `0600`，默认 `umask 077`。本地文件系统支持 ext 系列、XFS、Btrfs、ZFS、overlayfs 和 tmpfs；不接受 NFS/CIFS 等远程文件系统。生产 HOME 应持久化，不使用 tmpfs。

注册表格式为 `schemaVersion: 1`，包含所属用户名/UID以及以 profile 为键的 `instances`。每项记录：

- profile、用户名/UID、state/config/workspace 绝对路径、服务名。
- `port`/`portEnd`、创建时间、创建时 OpenClaw 版本。
- `ownerId`（与实例内所有者标记匹配）、`serviceFingerprint`（原生 unit 的 SHA-256）。
- `state`、`stage`、`configComplete` 和脱敏的 `lastError`。

注册表没有 API Key、Gateway token、聊天数据和渠道凭据。服务指纹用于识别手工改动，不能代替安全隔离。锁文件会在 purge 后保留，避免并发等待者锁到不同 inode。

`state` 是管理状态，不是实时服务状态：

- `creating`：尚未完成；进程被强制中断后也可能保持此状态。
- `ready`：创建或启动流程曾成功；此时服务仍可能被停止或发生故障。
- `failed`：创建失败，数据和端口保留。
- `removed`：服务卸载，数据和端口保留，可 start 恢复。
- `deleting`：已开始删除数据，失败后可修复原因并重试 purge。

`serviceStatus` 和 `gatewayHealth` 每次重新读取；`drift` 标出路径、服务或配置偏差。JSON 业务字段明确标记模型与渠道仍需单独验证，不推断业务已可用。

## 端口与服务

从 19000 起每 200 个端口分配一块，保留 `[base, base+199]`。包括 stop、remove、failed 在内的实例都继续预留；只有成功 purge 释放。

分配会检查注册表、当前用户可读的默认/命名 profile 配置、systemd 用户 Gateway 服务、IPv4/IPv6 TCP/UDP 监听端口。配置按原生 CLI 读取，支持 OpenClaw 解析的 JSON5。浏览器固定 CDP 端口一并避让；无法判定的浏览器 URL 或不完整自定义范围会阻止分配，不冒险猜测。

不可能阻止外部程序随后抢占端口；发生冲突时返回错误，不杀外部进程。其他用户不可读且已停止的实例、自定义服务名或外部 supervisor 管理的实例，需要管理员事先安排不重叠的端口区间。

服务由 `openclaw --profile NAME gateway install` 生成。第一版不接受服务 drop-in 或手工修改的 unit；发现偏差就停止相关变更。它也不自动升级 OpenClaw 或修复服务。升级共享 OpenClaw 需另行安排维护和完整备份，升级后重新验证版本能力及服务一致性。

OpenClaw 2026.9.5 的非交互停止要求 `gateway stop --force`。管理器在验证 profile、目录和服务指纹后，为用户明确请求的 stop/restart/remove/purge 及本次创建失败清理传入该参数；安装不使用 `--force`。

日志由 OpenClaw 自己轮转，活动文件上限 20 MiB。管理器不持久化原生 CLI 的失败输出，避免配置错误带出凭据；日志和原生交互配置仍属于敏感运维内容，不要公开分享未经检查的日志。

## 故障恢复

**创建失败或被强制中断：**先运行 `status`、`doctor`、`logs`。每个阶段先记入注册表；创建失败只尝试清理能证明属于本次操作的服务，不删除实例数据。如果无需保留新实例数据，执行 `purge NAME --confirm NAME` 后重新创建。第一版不自动续跑失败创建。

**注册表缺失或损坏：**停止管理器操作，从同一次备份恢复注册表和对应实例目录。不要删掉管理目录来“初始化”，也不要扫描目录生成新注册表。第一版不导入或自动认领已有实例。

**服务/路径偏差：**用带明确 profile 的 `openclaw gateway status --deep` 私下核对实际配置与服务。恢复已知正确的备份和路径后重试；不要仅改注册表中的指纹来绕过检查。实例根目录、配置、workspace、日志关键路径不得是符号链接。

**删除失败：**服务不能确认停止时不删数据。目录有挂载点、端口仍被监听或目录权限阻止删除时会保留记录和预留端口。修复原因后重试同一 purge；内部普通符号链接只删除链接本身，不跟随删除外部目标。

## 备份和远程访问

备份时停止相关实例，确保没有正在进行的管理或配置操作，再一起备份 `~/.local/state/openclaw-instance-manager/` 和相应的 `~/.openclaw-<profile>/`。包括所有者标记、隐藏文件和凭据。备份含敏感数据，应限制读取权限；恢复到相同用户名、UID、HOME，服务仍需按实际状态检查。

loopback 默认不开放公网。通过 SSH 转发访问实际分配端口，例如：

```bash
ssh -N -L 19000:127.0.0.1:19000 user@server
```

客户端仍需该实例的 Gateway 鉴权信息；管理器不会把 token 写进列表、注册表或命令参数。

## 测试

```bash
# ShellCheck + Linux 下的故障注入测试；不修改宿主机 OpenClaw
bash tests/run.sh

# 真实 OpenClaw + systemd 用户服务 + 容器重启恢复
bash tests/integration.sh
```

测试镜像固定 OpenClaw 2026.9.5。集成测试需要 Docker 支持特权 systemd 容器，仓库只读挂载；不挂载宿主 HOME 或 Docker socket，结束后删除测试容器。生产部署不需要 Docker。

集成测试的容器重启不能替代目标服务器的真实 SSH 退出和服务器重启验收，部署后还需按 [验证记录](docs/verification.md) 的清单核对。

接口依据：[多 Gateway](https://docs.openclaw.ai/gateway/multiple-gateways)、[基础初始化](https://docs.openclaw.ai/cli/setup)、[配置 CLI](https://docs.openclaw.ai/cli/config)、[服务管理](https://docs.openclaw.ai/cli/gateway/service)、[日志](https://docs.openclaw.ai/gateway/logging)。
