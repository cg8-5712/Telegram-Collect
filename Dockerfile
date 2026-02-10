FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建数据目录
RUN mkdir -p data sessions logs

# 暴露 Web 端口
EXPOSE 5000

# 默认启动统一服务（监控 + Web）
CMD ["python", "start.py"]
