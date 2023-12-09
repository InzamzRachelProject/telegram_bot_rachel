# 使用 python 作为基础镜像
FROM python:3.10.13-bullseye

COPY . /app

# 切换工作目录
WORKDIR /app

# 安装依赖
RUN pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple

# 设置环境变量
ENV FLASK_APP=index.py

# 启动 Flask 服务, 启动 DEBUG 模式
CMD ["flask", "run", "--host=0.0.0.0", "--port=9000", "--debugger"]

# 暴露 9000 端口
EXPOSE 9000