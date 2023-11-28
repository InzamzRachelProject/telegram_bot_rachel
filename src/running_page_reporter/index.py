import os
import hashlib
import json
import requests
from pymongo import MongoClient
from telebot import TeleBot

def calculate_pace(average_speed):
    return 60.0 / (average_speed * 3.6).__round__(2)

def send_telegram_message(chat_id, message):
    # 替换为你的 Telegram 发送消息的逻辑
    telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    bot = TeleBot(telegram_bot_token)
    bot.send_message(chat_id, message)

def main_handler(event, context):
    file_url = os.environ.get('REMOTE_FILE_URL')

    telegram_config = {
        'mongo_uri': os.environ.get('MONGO_URI'),
        'database': os.environ.get('DATABASE_NAME'),
        'collection': os.environ.get('COLLECTION_NAME'),
        'telegram_chat_id': os.environ.get('TELEGRAM_CHAT_ID')
    }

    client = MongoClient(telegram_config['mongo_uri'])
    db = client[telegram_config['database']]
    collection = db[telegram_config['collection']]

    # 从数据库中获取之前的活动信息
    previous_activities = collection.find_one({'config_key': 'running_page'})
    previous_activities = previous_activities or {'hash': '', 'activities': []}

    # 从远程 URL 获取最新的活动信息
    response = requests.get(file_url)
    file_content = response.text

    current_hash = hashlib.sha256(file_content.encode('utf-8')).hexdigest()

    # 如果是第一次运行或数据库中没有相应字段，则只更新数据库中的哈希值和活动信息
    if not previous_activities.get('hash'):
        collection.update_one({'config_key': 'running_page'}, {'$set': {'hash': current_hash, 'activities': json.loads(file_content)}}, upsert=True)
        print("第一次运行，更新数据库。")
    elif current_hash != previous_activities['hash']:
        # 更新数据库中的哈希值和活动信息
        collection.update_one({'config_key': 'running_page'}, {'$set': {'hash': current_hash, 'activities': json.loads(file_content)}}, upsert=True)

        # 解析最新的活动信息
        current_activities = json.loads(file_content)

        # 查找新增的活动
        new_activities = [activity for activity in current_activities if activity not in previous_activities['activities']]

        for activity in new_activities:
            # 构建消息
            message = f'跑步汇报：\n\n您好！刚刚记录了您的跑步信息，现在给您来份详细报告：这次运动，您跑了{activity["distance"]}米，持续了{activity["moving_time"]}，从{activity["start_date"]}开始。选择在{activity["location_country"]}启程，穿越了一段不错的路线，详情可以点击查看路线。\n\n整体来看，您的平均心率保持在{activity["average_heartrate"]}，配速为{calculate_pace(activity["average_speed"])}分钟/公里，这是您的第{activity["streak"]}次跑步，真不错！'
            # 调用发送 Telegram 消息的函数
            send_telegram_message(telegram_config['telegram_chat_id'], message)

        print("文件已更新。处理新的活动。")
    else:
        print("文件未更新。没有新的活动需要处理。")

    client.close()
