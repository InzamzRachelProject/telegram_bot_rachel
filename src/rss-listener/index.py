import os
import json
import requests
from pymongo import MongoClient
from telebot import TeleBot


def get_subscribed_rss_links_dict():
    # 连接 MongoDB
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_client = MongoClient(mongo_uri)

    # 连接到 TelegramBot 数据库
    db = mongo_client.TelegramBot

    # 获取 config 集合中的订阅链接
    config_collection = db.config
    config_document = config_collection.find_one({"type": "rss"})

    if config_document:
        return config_document.get("subscribe_info", {})
    else:
        return {}


def send_telegram_message(chat_id, text):
    # 获取 Telegram Bot Token
    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    # 创建 TeleBot 实例
    bot = TeleBot(telegram_bot_token)

    # 发送消息
    bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=False)


def main_handler(event, context):
    # 获取 MongoDB URI 和 RSS 订阅函数的 URL 从环境变量中
    mongo_uri = os.environ.get("MONGO_URI")
    rss_function_url = os.environ.get("RSS_FUNCTION")

    # 获取订阅链接列表
    subscribed_info = get_subscribed_rss_links_dict()

    if not subscribed_info:
        print("No RSS links subscribed.")
        return

    for chat_id, rss_links in subscribed_info.items():
        # 构造 HTTP 请求体
        request_body = {
            "chat_id": chat_id
        }

        # 构造 HTTP 请求头
        headers = {"Content-Type": "application/json"}

        # 调用 RSS 订阅函数
        response = requests.post(
            rss_function_url, data=json.dumps(request_body), headers=headers
        )

        # 解析 RSS 订阅函数的返回结果
        rss_result = response.json()
        if rss_result.get("errorCode") == -1:
            print(f"Error: {rss_result['errorMessage']}")
            continue

        # 输出描述新更新内容的文字
        for rss_url, articles in rss_result.items():
            if articles:
                print(f"New updates from {rss_url}:")
                for article in articles:
                    message_text = f"New article: <b>{article['title']}</b>\nLink: {article['link']}"
                    send_telegram_message(chat_id=chat_id, text=message_text)
            else:
                print(f"No new updates from {rss_url}.")


if __name__ == "__main__":
    main_handler(None, None)  # 在本地测试时调用 main_handler 函数
