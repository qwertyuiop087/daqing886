# 用稳定的 Python 3.11 镜像，避开 3.14 的坑
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码文件
COPY app.py .

# 启动命令
CMD ["python", "app.py"]
