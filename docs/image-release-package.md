# 数智小徽镜像交付说明

本文档描述如何在外网机器生成当前定制版 `nanobot-webui` 的镜像压缩包，并把它带入内网环境部署。

## 目标

- 外网机器直接基于当前仓库源码构建镜像
- 导出为 `tar.gz` 格式的镜像包
- 同时生成一套内网运行所需的 `docker-compose.yml`、配置模板和中文说明
- 内网机器不需要源码，不需要重新构建

## 前提

外网打包机器需要：

- Docker
- `docker compose`
- `gzip`

内网部署机器需要：

- Docker
- `docker compose`
- 能执行 `docker load`

## 打包命令

在仓库根目录执行：

```bash
scripts/build-image-release.sh
```

默认会：

1. 构建镜像 `nanobot-webui:local`
2. 清理并重建 `deployment/release/`
3. 导出镜像为 `deployment/release/nanobot-webui-local.tar.gz`
4. 生成部署文件：
   - `docker-compose.yml`
   - `.env.example`
   - `config.json`
   - `config.template.json`
   - `README.md`
   - `DEPLOYMENT-GUIDE.md`

## 常用参数

```bash
scripts/build-image-release.sh --help
```

可选参数：

- `--image-tag <tag>`：指定导出的镜像标签
- `--release-dir <dir>`：指定输出目录
- `--archive-name <name>`：指定镜像压缩包文件名
- `--skip-build`：跳过构建，直接导出已有镜像

当前镜像默认使用 `/assistant/` 作为前端访问前缀，可通过运行时环境变量
`WEBUI_BASE_PATH` 调整。

## 内网部署步骤

进入生成好的发布目录，例如：

```bash
cd deployment/release
```

1. 准备环境文件：

```bash
cp .env.example .env
```

2. 编辑目录里已经生成好的 `config.json`，至少填好：

- `agents.defaults.model`
- `providers.custom.apiKey`
- `providers.custom.apiBase`

3. 在目标机器准备宿主机目录：

```bash
mkdir -p /data/nanobot/user/public/logs
mkdir -p /data/nanobot/skills
mkdir -p /data/nanobot
cp config.json /data/nanobot/config.json
```

4. 导入镜像：

```bash
gunzip -c nanobot-webui-local.tar.gz | docker load
```

5. 启动：

```bash
docker compose up -d
```

6. 查看日志：

```bash
docker compose logs -f
```

## 默认运行约定

- 默认发布端口：`18781`
- 默认容器名：`nanobot-webui-local`
- 默认时区：`Asia/Shanghai`
- 默认关闭登录：`WEBUI_AUTH_DISABLED=true`
- 默认只运行 WebUI：`WEBUI_ONLY=true`
- 默认实例根目录：`/data/nanobot/user/public`
- 默认配置文件路径：`/data/nanobot/config.json`
- 默认技能目录：`/data/nanobot/skills`

## 运行数据位置

默认宿主机路径：

- `/data/nanobot/user/public`：会话、工作区、日志等运行态数据
- `/data/nanobot/skills`：可选自定义技能目录

如果需要迁移实例，优先保留这些宿主机目录以及你的 `/data/nanobot/config.json`。
