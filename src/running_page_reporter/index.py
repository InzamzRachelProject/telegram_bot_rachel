import hmac
import os
import hashlib
import json
import requests
from pymongo import MongoClient
from telebot import TeleBot
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import interp1d
import polyline
from flask import Flask, request, jsonify

app = Flask(__name__)

class PolylineConverter:
    def __init__(
        self,
        polyline_str,
        output_file,
        width=10,
        height=10,
        num_points=200,
        aspect_ratio=None,
    ):
        self.polyline_str = polyline_str
        self.output_file = output_file
        self.width = width
        self.height = height
        self.num_points = num_points
        self.aspect_ratio = aspect_ratio

    def _smooth_polyline(self, coords):
        lats, lons = zip(*coords)

        lat_interp = interp1d(np.arange(len(lats)), lats, kind="cubic")
        lat_smooth = lat_interp(np.linspace(0, len(lats) - 1, self.num_points))

        lon_interp = interp1d(np.arange(len(lons)), lons, kind="cubic")
        lon_smooth = lon_interp(np.linspace(0, len(lons) - 1, self.num_points))

        return list(zip(lat_smooth, lon_smooth))

    def _decode_polyline(self):
        return polyline.decode(self.polyline_str)

    def convert_to_png(self):
        coords = self._decode_polyline()
        smooth_coords = self._smooth_polyline(coords)
        smooth_lats, smooth_lons = zip(*smooth_coords)

        fig, ax = plt.subplots(figsize=(self.width, self.height))
        ax.plot(smooth_lons, smooth_lats, linewidth=2, color="skyblue")

        if self.aspect_ratio:
            ax.set_aspect(self.aspect_ratio)

        ax.set_axis_off()

        plt.savefig(
            self.output_file,
            format="png",
            bbox_inches="tight",
            pad_inches=0,
            transparent=True,
        )
        plt.close()


# # 示例使用
# polyline_str = "kyfzD}cjzRPi@c@mAqEQg@T[bAt@`B|EBd@YLoAaAsAoE?u@|A`AzAtECh@iBm@kAeFBo@tAp@fAlENx@yAs@gA{D?w@|@Dn@p@l@~DAn@iAq@kAuDE_At@p@hBnEE`@y@MgAy@YaET[vAZb@vBRxBUX}@Mo@o@c@}DHc@fBxAt@xCE`@U@{Am@i@sEH]z@T`AdCZ|Ba@EgB{@]wDP[pAv@~@xDCb@YJeA{@{@kEJYz@XbA"
# output_file = "output_smooth.png"

# # 创建PolylineConverter对象并调用convert_to_png方法
# aspect_ratio = 1.0  # 调整此值以更改图像的比例
# converter = PolylineConverter(polyline_str, output_file, aspect_ratio=aspect_ratio)
# converter.convert_to_png()


def calculate_pace(average_speed):
    return 60.0 / (average_speed * 3.6).__round__(2)


def send_telegram_message_with_image(chat_id, message, image_file):
    # 替换为你的 Telegram 发送消息的逻辑
    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    bot = TeleBot(telegram_bot_token)
    bot.send_photo(chat_id, open(image_file, "rb"), caption=message)


def check_github_webhook_secret(request):
    data = request.get_json()
    # 替换为你的 GitHub Webhook Secret
    print(data)
    github_webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET")

    github_webhook_signature = data["headers"]["x-hub-signature"]

    # 获取 GitHub Webhook 的 HTTP 请求体
    github_webhook_body = data["body"]

    # 计算签名
    signature = (
        "sha1="
        + hmac.new(
            github_webhook_secret.encode("utf-8"),
            github_webhook_body.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()
    )

    print("Signature: " + signature)
    print("X-Hub-Signature: " + github_webhook_signature)
    
    # 对比签名
    if not hmac.compare_digest(signature, github_webhook_signature):
        raise Exception("Invalid GitHub Webhook Secret")


@app.route('/event-invoke', methods=['POST'])
def main_handler():
    
    file_url = os.environ.get("REMOTE_FILE_URL")

    check_github_webhook_secret(request)

    telegram_config = {
        "mongo_uri": os.environ.get("MONGO_URI"),
        "database": os.environ.get("DATABASE_NAME"),
        "collection": os.environ.get("COLLECTION_NAME"),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID"),
    }

    client = MongoClient(telegram_config["mongo_uri"])
    db = client[telegram_config["database"]]
    collection = db[telegram_config["collection"]]

    # 从数据库中获取之前的活动信息
    previous_activities = collection.find_one({"config_key": "running_page"})
    previous_activities = previous_activities or {"hash": "", "activities": []}

    # 从远程 URL 获取最新的活动信息
    response = requests.get(file_url)
    file_content = response.text

    current_hash = hashlib.sha256(file_content.encode("utf-8")).hexdigest()

    # 如果是第一次运行或数据库中没有相应字段，则只更新数据库中的哈希值和活动信息
    if not previous_activities.get("hash"):
        collection.update_one(
            {"config_key": "running_page"},
            {"$set": {"hash": current_hash, "activities": json.loads(file_content)}},
            upsert=True,
        )
        print("第一次运行，更新数据库。")
    elif current_hash != previous_activities["hash"]:
        # 更新数据库中的哈希值和活动信息
        collection.update_one(
            {"config_key": "running_page"},
            {"$set": {"hash": current_hash, "activities": json.loads(file_content)}},
            upsert=True,
        )

        # 解析最新的活动信息
        current_activities = json.loads(file_content)

        # 查找新增的活动
        new_activities = [
            activity
            for activity in current_activities
            if activity not in previous_activities["activities"]
        ]

        for activity in new_activities:
            # 构建消息
            message = f'跑步汇报：\n\nHello，主人！刚刚记录了您的跑步信息，现在为您呈上详细报告：这次运动，您成功跑了{activity["distance"]}米，持续了{activity["moving_time"]}，始于{activity["start_date_local"]}。您选择在{activity["location_country"]}起跑，穿越了一段美妙的路线。\n\n总的来说，您的平均心率维持在{activity["average_heartrate"]}，速度平均每秒{activity["average_speed"]}米。这是您的第{activity["streak"]}次连续跑步，真是令人振奋！'
            # 构建图片
            polyline_str = activity["summary_polyline"]
            output_file = "output_smooth.png"
            aspect_ratio = 1.0
            converter = PolylineConverter(
                polyline_str, output_file, aspect_ratio=aspect_ratio
            )
            converter.convert_to_png()
            # 调用发送 Telegram 消息的函数
            send_telegram_message_with_image(telegram_config["telegram_chat_id"], message, output_file)

        print("文件已更新。处理新的活动。")
    else:
        print("文件未更新。没有新的活动需要处理。")

    client.close()
    return jsonify({"message": "success"})