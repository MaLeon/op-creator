# 验证记录

日期：2026-09-21。生产服务器尚未连接；本记录区分隔离测试结果与目标服务器验收。

## 实际测试环境

| 项目 | 版本/说明 |
|---|---|
| OpenClaw | **2026.9.5 (ec9c1a1)**，npm 精确版本安装 |
| Linux 用户空间 | Debian GNU/Linux 12 bookworm，aarch64 |
| Node | v24.21.0 |
| Bash | 5.2.15 |
| systemd | 252.39-1~deb12u2 |
| jq | 1.6 |
| 运行身份 | 普通用户 operator，UID 1001，linger=yes |
| 隔离方式 | Docker Desktop Linux 容器，独立 systemd PID 1、用户服务和 HOME |

测试期间没有挂载或修改宿主 OpenClaw 配置、凭据、服务；仓库只读挂载。特权容器只用于 systemd 集成测试，不是生产架构。

## 自动化检查

运行方式：`bash tests/run.sh`。包含 Bash ShellCheck 和非 root Linux 下的 Python unittest；使用真实文件权限、flock 和文件操作，OpenClaw/systemctl/loginctl/ss 接口由独立测试夹具模拟。

覆盖并发首次创建、同名并发、独立 token、重复创建、端口/浏览器区间冲突、非受管配置避让、停机端口预留、生命周期、remove/start 恢复、初始化/配置/安装/健康失败、60 秒健康期限、强制中断、注册表损坏或丢失、写入权限失败、停止/卸载失败、部分删除重试、环境变量污染、路径/服务/配置偏差、符号链接及非交互配置拒绝。

ShellCheck 通过；**24 项测试全部通过**，本次完整回归耗时 139.477 秒。

## 真实 OpenClaw/systemd 集成测试

运行方式：`bash tests/integration.sh`。结果：**通过**。

已验证：

1. 普通用户安装管理器，原生 CLI 能力预检通过。
2. 原生创建一个不受管理器管理的 `legacy` profile/service，端口 19600。
3. 管理器创建 `alpha`/`bravo`，分别使用 19000/19200，独立配置和服务，均通过带鉴权健康检查。
4. 错误 token 的健康请求被拒绝。
5. 停止 alpha 时 bravo 保持健康；alpha 可重新启动，bravo 可重启。
6. remove alpha 保留数据，再 start 恢复原生服务。
7. 隔离 systemd 容器重启后，alpha/bravo 均自动启动并恢复健康。
8. purge alpha 后 bravo 保持健康；继续 purge bravo 后受管列表为空。
9. legacy 配置和服务文件 SHA-256 校验前后一致，其服务保持 active。

运行末尾输出：

```text
/home/operator/.openclaw-legacy/openclaw.json: OK
/home/operator/.config/systemd/user/openclaw-gateway-legacy.service: OK
active
INTEGRATION PASS — OpenClaw OpenClaw 2026.9.5 (ec9c1a1)
```

集成中发现并修复了模拟接口未反映的两点：systemd 无匹配通配服务时返回非零；OpenClaw 2026.9.5 非交互停止需要 `--force`。对应原生调用已修正，夹具已同步。

## 尚未执行的目标服务器验收

- 目标服务器实际发行版、CPU 架构、Node/OpenClaw 版本与文件系统预检。
- 真实 SSH 会话退出后，重新登录确认两个测试实例仍健康。
- 经管理员安排的服务器真实重启后，确认用户管理器和实例自动恢复。
- 实际业务模型凭据配置和一次模型请求；实际渠道登录及消息收发。

这些项目不能由容器重启或 Gateway 健康推断为已通过。生产验证时只使用明确的新测试 profile，不操作已有业务实例；将上述目标环境信息及结果补充到部署记录。

## 最终结果

静态检查通过，24 项故障回归通过，真实 OpenClaw/systemd 集成通过。未执行的目标服务器项目保留在上方清单中，没有以模拟测试替代。

本次原始输出保存在工作目录的 `.test-results/unit.log` 和 `.test-results/integration.log`（已加入忽略规则）。
