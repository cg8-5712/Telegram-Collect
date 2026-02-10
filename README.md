# Telegram 群组关键词监控系统

一个基于 Telegram 用户账号的群组消息监控系统，用于实时监控群组中的关键词（如红包消息），并自动发送通知。

## 功能特点

- ✅ 账号B登录监控，账号A接收通知（无需登录）
- ✅ 支持多群组同时监控
- ✅ 三种关键词匹配方式：精确匹配、模糊匹配、正则表达式
- ✅ 自定义通知消息格式
- ✅ 配置热重载（无需重启即可更新群组和关键词）
- ✅ 消息链接生成，快速跳转到原消息
- ✅ 发送失败自动重试
- ✅ 断线自动重连
- ✅ 详细日志记录

## 系统架构

```
账号 B (监控账号) → 监听群组消息 → 检测关键词 → 发送通知 → 账号 A (接收通知)
```

- **账号 B**：需要登录，加入目标群组，负责监听消息并发送通知
- **账号 A**：无需登录，只需配置用户名或ID，用于接收通知消息

## 快速开始

### 环境要求

- Python 3.8+
- Telegram 账号（账号B）
- Telegram API 凭证（api_id 和 api_hash）

### 1. 获取 API 凭证

1. 访问 https://my.telegram.org
2. 登录你的 Telegram 账号
3. 点击 "API development tools"
4. 创建一个新应用，获取 `api_id` 和 `api_hash`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置系统

复制配置模板并编辑：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml` 文件：

```yaml
# 账号B - 监控账号（需要登录）
monitor_account:
  phone: "+86138xxxxxxxx"  # 手机号（必须以+开头）
  api_id: "YOUR_API_ID"     # 从 my.telegram.org 获取
  api_hash: "YOUR_API_HASH" # 从 my.telegram.org 获取

# 账号A - 通知接收账号（无需登录）
notify_target:
  username: "@your_username"  # 账号A的用户名

# 监控群组列表
monitor_groups:
  - group_id: -1001234567890  # 群组ID
    group_name: "红包福利群"
    enabled: true

# 关键词配置
keywords:
  contains:
    - "红包"
    - "抢红包"
```

**注意：** Telegram 只支持手机号登录，手机号必须以 `+` 开头（如：`+8613812345678`）

### 4. 获取群组 ID

运行以下脚本获取群组ID：

```bash
python get_group_id.py
```

使用已保存的 session，无需重复登录。

### 5. 启动系统

**方式一：统一启动（推荐）**

同时启动监控服务和 Web 管理界面：

```bash
python start.py
```

访问 Web 管理界面：http://localhost:5000

**方式二：分别启动**

仅启动监控服务：
```bash
python main.py
```

仅启动 Web 管理界面：
```bash
python web_app.py
```

首次运行会要求输入验证码登录账号B。

## Docker 部署

### 1. 准备配置文件

复制配置模板并修改：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的配置：
- 账号B的 API ID、API Hash、手机号
- 账号A的用户名或 user_id
- 监控群组列表
- 关键词配置

### 2. 使用 Docker Compose 启动

```bash
# 构建并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 3. 服务说明

**tg-monitor 服务（统一容器）**
- **功能**: Telegram 消息监控服务 + Web 管理界面
- **端口**: 5000
- **访问**: http://localhost:5000
- **默认账号**: admin / admin123
- **数据卷**:
  - `./config.yaml` - 配置文件
  - `./sessions` - Telegram 会话文件
  - `./data` - 统计数据库
  - `./logs` - 日志文件

### 4. 首次登录

首次启动时需要登录 Telegram 账号B：

```bash
# 进入容器
docker exec -it tg-monitor bash

# 停止当前服务
pkill -f start.py

# 手动运行监控程序（会提示输入验证码）
python main.py
```

按提示输入验证码完成登录，session 会保存到 `./sessions` 目录。

登录成功后，退出容器并重启服务：

```bash
exit
docker-compose restart
```

### 5. 常用命令

```bash
# 查看运行状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 更新代码后重新构建
docker-compose up -d --build

# 进入容器调试
docker exec -it tg-monitor bash

# 查看 Web 服务日志
docker-compose logs -f | grep WebApp

# 查看监控服务日志
docker-compose logs -f | grep TelegramMonitor
```

### 6. 数据持久化

所有重要数据都通过 volume 挂载到宿主机：

- `./sessions/` - Telegram 登录会话
- `./data/` - SQLite 统计数据库
- `./logs/` - 运行日志
- `./config.yaml` - 配置文件

### 7. 生产环境建议

1. **修改 SECRET_KEY**
   ```yaml
   environment:
     - SECRET_KEY=使用随机生成的长字符串
   ```

2. **使用反向代理**
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

3. **配置 HTTPS**
   使用 Let's Encrypt 或其他 SSL 证书

4. **定期备份**
   ```bash
   # 备份数据
   tar -czf backup-$(date +%Y%m%d).tar.gz sessions/ data/ config.yaml
   ```

## 配置热重载

系统支持配置热重载功能，可以在不重启服务的情况下动态更新：

- 监控群组设置
- 关键词配置
- 通知消息模板

只需编辑 `config.yaml` 文件并保存，系统会在 5 秒内自动检测并应用新配置。

**工作原理：**
- 系统每 5 秒检查一次 `config.yaml` 文件的修改时间
- 检测到变化时自动重新加载配置
- 如果监控群组发生变化，会重新注册事件处理器
- 关键词和通知模板会立即更新

**支持热重载的配置项：**
- ✅ 监控群组（添加/删除/启用/禁用）
- ✅ 关键词配置（精确/模糊/正则）
- ✅ 通知消息模板

**不支持热重载的配置项：**
- ❌ 账号配置（monitor_account, notify_target）
- ❌ 系统配置（system）
- ❌ 日志配置（logging）

## 配置说明

### 关键词配置

支持三种匹配方式：

```yaml
keywords:
  # 精确匹配（整条消息完全匹配）
  exact:
    - "红包"

  # 模糊匹配（包含即可）
  contains:
    - "抢红包"
    - "发红包"
    - "领红包"

  # 正则表达式匹配
  regex:
    - "红包\\d+元"      # 匹配 "红包100元"
    - "\\d+元红包"      # 匹配 "100元红包"
```

### 通知格式

自定义通知消息格式：

```yaml
notification:
  format: |
    🔔 关键词提醒
    📍 群组：{group_name}
    🏷️ 关键词：{keyword}
    ⏰ 时间：{time}
    📝 消息：{message}
    🔗 链接：{link}

  include_link: true  # 是否包含消息链接
  forward_original: false  # 是否转发原始消息
```

**可用变量：**
- `{group_name}` - 群组名称
- `{keyword}` - 匹配到的关键词
- `{time}` - 时间（优先从消息内容中提取，如"北京时间17:45"，提取不到则使用消息发送时间+8小时转换为北京时间）
- `{message}` - 消息内容
- `{link}` - 消息链接

### 系统配置

```yaml
system:
  auto_reconnect: true        # 自动重连
  reconnect_delay: 30         # 重连延迟（秒）
  keep_alive_interval: 30     # 心跳保活间隔（秒），保持客户端在线
  retry_count: 3              # 发送失败重试次数
  retry_delay: 5              # 重试延迟（秒）
```

## 项目结构

```
Tg-goofish-0210/
├── main.py                 # 主程序入口
├── start.py                # 统一启动脚本（监控+Web）
├── web_app.py              # Web 管理界面
├── get_group_id.py         # 获取群组ID工具
├── config.yaml             # 配置文件
├── config.example.yaml     # 配置模板
├── requirements.txt        # 依赖列表
├── Dockerfile              # Docker 镜像
├── docker-compose.yml      # Docker Compose 配置
├── src/
│   ├── core/
│   │   ├── monitor.py      # 监控核心模块
│   │   ├── keyword_matcher.py  # 关键词匹配引擎
│   │   └── statistics.py   # 统计数据库
│   └── utils/
│       ├── config.py       # 配置加载工具
│       ├── config_reloader.py  # 配置热重载
│       └── logger.py       # 日志工具
├── sessions/               # Session 文件目录
├── data/                   # 数据库目录
└── logs/                   # 日志文件目录
```

## 常见问题

### 1. 如何获取群组ID？

- 公开群组：使用群组链接中的用户名
- 私密群组：运行 `python get_group_id.py` 获取

### 2. 账号A需要登录吗？

不需要。账号A只需要提供用户名（@username）或用户ID即可。

### 3. 支持多个群组吗？

支持。在 `config.yaml` 中添加多个群组配置即可。

### 4. 如何停止监控？

按 `Ctrl+C` 停止程序。

### 5. Session 文件是什么？

Session 文件保存了登录凭证，避免每次启动都需要输入验证码。请妥善保管，不要泄露。

### 6. 手机退出 Telegram 后收不到消息？

系统会自动发送心跳保活（默认 30 秒一次），保持客户端在线状态。如果心跳间隔太长，可以调短：

```yaml
system:
  keep_alive_interval: 15  # 改为 15 秒
```

### 7. 为什么有"数据库被锁定"或"ON CONFLICT"错误？

这是数据库表结构问题，需要删除旧数据库让系统自动重建：

```bash
# 停止服务
pkill -f start.py

# 删除数据库
rm data/statistics.db

# 重新启动
python start.py
```

### 8. 消息时间显示不对？

系统会自动处理：
- 优先从消息内容中提取时间（如"北京时间17:45"）
- 如果提取不到，使用消息发送时间 + 8小时转换为北京时间

## 故障排查

### 服务无法启动

```bash
# 查看日志
docker-compose logs

# 检查配置文件
cat config.yaml

# 删除旧 session 重新登录
rm -rf sessions/*
docker-compose restart
```

### Web 界面无法访问

```bash
# 检查端口占用
netstat -tlnp | grep 5000

# 查看服务日志
docker-compose logs | grep WebApp

# 重启服务
docker-compose restart
```

### 监控服务不工作

```bash
# 查看监控日志
docker-compose logs | grep TelegramMonitor

# 进入容器手动测试
docker exec -it tg-monitor bash
python main.py
```

## 注意事项

1. **账号安全**：不要频繁操作，避免触发 Telegram 的反垃圾机制
2. **API 凭证**：妥善保管 api_id 和 api_hash，不要泄露
3. **Session 文件**：不要分享 session 文件，它包含登录凭证
4. **群组权限**：确保账号B已加入目标群组
5. **合法使用**：仅用于个人合法用途，不要用于垃圾信息或骚扰
6. **心跳频率**：建议保持 15-30 秒，太短可能触发 Telegram 频率限制

## 技术支持

如有问题，请查看：
1. 日志文件 `logs/monitor.log`
2. 配置文件 `config.yaml`
3. Docker 日志 `docker-compose logs`

## 许可证

本项目仅供学习和个人使用。
