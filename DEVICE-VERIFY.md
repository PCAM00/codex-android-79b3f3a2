# Codex 独立运行环境：手机验收清单

本清单用于 **Codex / io.cdxbox** 安装包。不要卸载、覆盖或修改原来的 Termux 或 DSH。它是自建的 Termux 派生运行环境，不是 OpenAI 官方 Android App。

## 安装前

1. 核对 APK 下载哈希与随附的 `SHA256SUMS`。
2. 核对签名报告中的证书 SHA-256：

   `14cd1fad787e7b771fdeab9d8cd7096729e705786e1cad3dc6c9086629df7703`

3. 安装目标应是新应用 **Codex**，包名 **io.cdxbox**。如果系统提示更新另一款已有应用，先停止并核实，不要为了安装它卸载原 Termux。
4. 安装在手机主用户环境；不要假定工作资料或系统分身里的数据路径与本次编译路径一致。
5. 首次启动应完成自己的 bootstrap 初始化。出现初始化失败弹窗时保留错误内容，不要把 failsafe `/system/bin/sh` 能启动当成成功。

## 只读基础检查

在新应用自己的终端粘贴下面这段。整个检查在子 shell 中进行：即使误粘贴到原 Termux，也只退出检查，不关闭你的原终端。不会打印环境中的 API 令牌，也不会写文件。

```sh
(
  expected=/data/data/io.cdxbox/files/usr
  if [ "${PREFIX:-}" != "$expected" ]; then
    printf '停止：这不是 io.cdxbox 的原生终端。PREFIX=%s\n' "${PREFIX:-未设置}"
    exit 1
  fi
  printf 'PREFIX=%s\nHOME=%s\n' "$PREFIX" "$HOME"
  uid="$($PREFIX/bin/id -u)" || exit 1
  owner="$($PREFIX/bin/stat -c %u "$PREFIX")" || exit 1
  printf '进程 UID=%s，PREFIX 所有者=%s\n' "$uid" "$owner"
  [ "$uid" = "$owner" ] || { printf '失败：目录所有者不匹配\n'; exit 1; }
  printf '\n架构：'; "$PREFIX/bin/uname" -m || exit 1
  printf '\nBash 子进程：\n'
  "$PREFIX/bin/bash" --noprofile --norc -c 'printf "CHILD_EXEC_OK\n"' || exit 1
  printf '\n动态链接与工具启动：\n'
  "$PREFIX/bin/curl" --version || exit 1
  "$PREFIX/bin/proot" --version || exit 1
  printf '\n基础只读检查结束；这还不等于 Codex CLI 或网页客户端已验收。\n'
)
```

预期：PREFIX 正确、进程 UID 与目录所有者相同、架构为 aarch64、打印 CHILD_EXEC_OK，curl 与 proot 均能正常启动且没有缺少共享库的错误。

## 后续验收不能省略

- 新建第二个原生终端会话，确认仍然能正常启动。
- 验证 bootstrap 的第二阶段实际完成，而非仅仅解压成功。
- 分别确认原 Termux、DSH 仍可以正常打开；不复制它们的私有配置或密钥。
- 如要运行普通 Linux/glibc 或 musl 程序，另外验证隔离的 Linux 用户空间及 proot 子进程；Termux/Bionic 本身不等于普通 Linux。
- 真正 Codex CLI 的安装、网关身份、连续多轮、工具结果回传与会话恢复须再单独测试。
- 图形界面还需检查实际手机软键盘、安全区、横竖屏和后台恢复。

## 原生包管理限制

当前 bootstrap 原生 APT 网络源被隔离，不能直接安装面向 com.termux 前缀的官方二进制包。只可使用匹配 io.cdxbox 的原生构建产物。此限制不代表今后的 Linux guest 必须使用 Termux 包源；guest 包管理需按它自己的发行版单独配置。

## 报告范围

CI 的 APK、签名、ABI、DEX/Manifest 和内嵌 bootstrap 检查属于静态验证。只有在手机上完成上述检查后，才能记录真实安装与运行通过。不要因 APK 文件存在、安装器显示成功或系统 shell 能打开，就直接宣称整个客户端可用。
