import json
import os
import requests
import telebot
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from modules.ask_ai import pic_generator
from modules.get_random_quote import get_random_quote


class CardMaker:
    def __init__(self, json_data, font_path, image_path, text_padding=80, gap=10):
        self.data = json_data
        self.font_path = font_path
        self.image_path = image_path
        self.font_size = 48
        self.text_padding = text_padding
        self.gap = gap

    def calculate_text_size(self, text, font_size, max_width):
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        total_height, line_width = 0, 0

        for char in text:
            # 另起一行的条件
            if char == "\n" or line_width > max_width:
                total_height += font_size + self.gap  # 增加行高
                line_width = 0  # 重置当前行宽

            # 根据字符类型决定占用宽度
            if ord(char) >= 128:  # 非ASCII字符
                char_width = font_size
            else:  # ASCII字符
                char_width = font_size / 2

            # 如果当前行累计大小已大于1050px，需要换行
            if line_width + char_width > max_width:
                total_height += font_size + self.gap  # 增加行高
                line_width = char_width  # 当前行宽为当前字符宽度
            else:
                line_width += char_width  # 累加至当前行宽

        total_height += font_size + self.gap  # 增加行高
        return total_height

    def choose_font_size(self, text_max_width=1050, text_max_height=920):
        # 这个函数需要读取self.data中的 quote，comment（可能不存在），speaker三个字符串
        # 通过二分法计算需要使用的字体大小，单位是px
        # 规则如下：
        # 1. 遇到换行符号，另起一行
        # 2. 每个非ASCII字符占一个字体大小，ASCII字符占半个字体大小，行高度为字体大小
        # 3. 当前行累计大小已经大于 1050px 需要强制换行
        # 4. quote，comment（可能不存在），speaker 两两之间需要空一行
        # 5. 累计高度不能超过 920px
        # 上界和下界初始化
        low, high = 30, 60
        best_font_size = low
        quote = self.data.get("content", "")
        comment = self.data.get("comments", "")
        speaker = self.data.get("speaker", "")
        if speaker == "":
            speaker = "——" + self.data["author"]

        print("quote:", quote)
        print("comment:", comment)
        print("speaker:", speaker)

        # 二分法搜索合适字体大小
        while low <= high:
            mid = (low + high) // 2

            quote_height = self.calculate_text_size(quote, mid, text_max_width)
            comment_height = self.calculate_text_size(comment, mid, text_max_width)
            speaker_height = self.calculate_text_size(speaker, mid, text_max_width)

            total_height = quote_height + comment_height + speaker_height

            # 添加两个段落之间的空行
            total_height += 2 * (mid + self.gap)

            if total_height > text_max_height:
                high = mid - 1  # 太大，减小字体大小
            else:
                best_font_size = mid  # 更新最佳字体大小
                low = mid + 1  # 尝试更大的字体大小
                self.best_height = total_height

        return best_font_size

    def split_text_into_list(self, max_width=1050):
        # 根据现在 self.font_size 的大小
        # 将 quote，comment（可能不存在），speaker 三个字符串按照行宽限制拆分成 list，更新到成员变量中
        # 规则如下：
        # 1. 遇到换行符号，另起一行
        # 2. 每个非ASCII字符占一个字体大小，ASCII字符占半个字体大小，行高度为字体大小
        # 3. 当前行累计大小已经大于 1050px 需要强制换行
        # 4. quote，comment（可能不存在），speaker 两两之间需要空一行
        # 5. 累计高度不能超过 920px
        self.quote_lines = []
        self.comment_lines = []
        self.speaker_lines = []

        quote = self.data.get("content", "")
        comment = self.data.get("comments", "")
        speaker = self.data.get("speaker", "")
        if speaker == "":
            speaker = "——" + self.data["author"]

        print("quote:", quote)
        print("comment:", comment)
        print("speaker:", speaker)

        # 处理文本拆分
        self.quote_lines = self.split_text(quote, max_width)

        self.comment_lines = self.split_text(comment, max_width)

        self.speaker_lines = self.split_text(speaker, max_width)

    def split_text(self, text, max_width):
        """根据提供的行宽和其他规则拆分文本。"""
        lines = []  # 存储拆分的行
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))  # 用于计算文本尺寸的绘图对象
        current_line = ""
        current_width = 0
        for char in text:
            # 遇到换行符号另起一行
            if char == "\n":
                lines.append(current_line)
                current_line = ""
                current_width = 0
                continue

            # 计算字符宽度，非ASCII字符记为一个字体大小，ASCII字符占半个字体大小
            char_width = self.font_size if ord(char) > 128 else self.font_size / 2

            # 如果当前行累积大小超过1050px，则强制换行
            if current_width + char_width > max_width:
                lines.append(current_line)
                current_line = char
                current_width = char_width
            else:
                current_line += char
                current_width += char_width

        # 添加最后一行
        if current_line:
            lines.append(current_line)

        return lines

    def create_card(self, output_path):
        # 加载封面图片并应用模糊滤镜
        cover_image = Image.open(self.image_path)
        cover_image = cover_image.filter(ImageFilter.GaussianBlur(40))

        # 计算合适的尺寸以填充背景
        width, height = cover_image.size
        target_width, target_height = 1920, 1080
        max_ratio = max(target_width / width, target_height / height)
        min_ratio = min(target_width / width, target_height / height)
        new_size = (int(width * max_ratio), int(height * max_ratio))
        bg_cover_image = cover_image.resize(new_size, Image.Resampling.LANCZOS)

        # 如果尺寸不匹配，则进行裁剪
        if new_size[0] != target_width or new_size[1] != target_height:
            cover_image = self.crop_to_fit(bg_cover_image, target_width, target_height)

        # 创建一个同样大小的图像用于绘画
        img = Image.new("RGB", (1920, 1080))
        img.paste(cover_image)

        # 继续之前的步骤
        d = ImageDraw.Draw(img)
        cover_image = Image.open(self.image_path)
        new_size = (int(width * min_ratio), int(height * min_ratio))
        cover_image = cover_image.resize(new_size, Image.Resampling.LANCZOS)

        # 粘贴书籍封面的缩略图
        cover_image.thumbnail(new_size)
        img.paste(cover_image, (0, 0), cover_image.convert("RGBA"))

        self.font_size = self.choose_font_size(
            target_width - new_size[0] - self.text_padding * 2,
            target_height - self.text_padding * 2,
        )
        self.split_text_into_list(target_width - new_size[0] - self.text_padding * 2)
        # 添加文本和图片，文本颜色改为白色提高对比度

        text_begin_height = 1080 / 2 - self.best_height / 2

        quote_font = ImageFont.truetype(self.font_path, self.font_size)
        speaker_font = ImageFont.truetype(
            font=self.font_path,
            size=self.font_size,
        )
        book_info_font = ImageFont.truetype(font=self.font_path, size=self.font_size)

        for quote in self.quote_lines:
            d.text(
                (new_size[0] + 80, text_begin_height),
                quote,
                fill="black",
                font=quote_font,
                align="left",
            )
            text_begin_height += self.font_size + self.gap
        text_begin_height += self.font_size + self.gap

        for speaker in self.speaker_lines:
            d.text(
                (new_size[0] + 80, text_begin_height),
                speaker,
                fill="black",
                font=quote_font,
                align="right",
            )
            text_begin_height += self.font_size + self.gap
        text_begin_height += self.font_size + self.gap

        for comment in self.comment_lines:
            d.text(
                (new_size[0] + 80, text_begin_height),
                comment,
                fill="black",
                font=quote_font,
                align="left",
            )
            text_begin_height += self.font_size + self.gap
        text_begin_height += self.font_size + self.gap

        # 保存图像
        img.save(output_path)

    def crop_to_fit(self, image, target_width, target_height):
        """
        图片按比例缩放后，如果不符合目标尺寸，则从中间裁剪到目标大小。
        """
        width, height = image.size
        top = (height - target_height) // 2
        left = (width - target_width) // 2
        right = (width + target_width) // 2
        bottom = (height + target_height) // 2
        return image.crop((left, top, right, bottom))


def send_quote_pic_to_telegram(message):
    # 假设JSON数据和字体文件路径如下
    json_data = get_random_quote()
    print(json_data)
    font_path = "fonts/AlibabaHealthFont2.0CN-85B.ttf"

    ret, pic_url = pic_generator(
        "dall-e-3", json_data["content"], return_type="url", size="1024x1792"
    )
    print(ret, pic_url)
    with open("image.png", "wb") as f:
        f.write(requests.get(pic_url).content)
    # 创建CardMaker实例
    card_maker = CardMaker(
        json_data,
        font_path,
        image_path="/tmp/image.png",
    )
    # 生成卡片，并保存到文件
    card_maker.create_card("/tmp/quote.png")

    tele_token = os.getenv("tele_token")

    bot = telebot.TeleBot(tele_token)
    bot.send_photo(
        chat_id=message["chat"]["id"],
        photo=open("/tmp/quote.png", "rb"),
        reply_to_message_id=message["message_id"],
    )


if __name__ == "__main__":
    message = {
        "chat": {
            "id": 1470074308,
        }
    }
    send_quote_pic_to_telegram(message)
