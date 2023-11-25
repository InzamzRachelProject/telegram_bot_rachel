import os
import json
import requests
from pymongo import MongoClient

def get_subscribed_rss_links():
    # 连接 MongoDB
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_client = MongoClient(mongo_uri)

    # 连接到 TelegramBot 数据库
    db = mongo_client.TelegramBot

    # 获取 config 集合中的订阅链接
    config_collection = db.config
    config_document = config_collection.find_one({"type": "rss"})
    
    if config_document:
        return config_document.get("rss_links", [])
    else:
        return []

def main_handler(event, context):
    # 获取 MongoDB URI 和 RSS 订阅函数的 URL 从环境变量中
    mongo_uri = os.environ.get("MONGO_URI")
    rss_function_url = os.environ.get("RSS_FUNCTION")

    # 获取订阅链接列表
    rss_links = get_subscribed_rss_links()

    if not rss_links:
        print("No RSS links found in the configuration.")
        return

    # 构造 HTTP 请求体
    request_body = {
        "rss": rss_links
    }

    # 构造 HTTP 请求头
    headers = {
        "Content-Type": "application/json"
    }

    # 调用 RSS 订阅函数
    response = requests.post(rss_function_url, data=json.dumps(request_body), headers=headers)

    # 解析 RSS 订阅函数的返回结果
    rss_result = response.json()

    # 输出描述新更新内容的文字
    for rss_url, articles in rss_result.items():
        if articles:
            print(f"New updates from {rss_url}:")
            for article in articles:
                print(f"- {article['title']} ({article['link']})")
        else:
            print(f"No new updates from {rss_url}.")

if __name__ == "__main__":
    main_handler(None, None)  # 在本地测试时调用 main_handler 函数
