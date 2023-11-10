# -*- coding: utf8 -*-
import json
import telebot
import os
import openai
import traceback

def main_handler(event, context):
    # 对 webhook 进行鉴权
    if event['headers']['x-telegram-bot-api-secret-token'] != os.getenv('telegram_bot_api_secret_token'):
        return "Api auth failed"
    print("Received event: " + json.dumps(event, indent = 2)) 
    tele_token = os.getenv("tele_token")

    if not tele_token:
        return "No tele_token found"

    bot = telebot.TeleBot(tele_token)
    update = json.loads(event['body'].replace('\"', '"'))
    # print("Received message: " + json.dumps(update, indent = 2))
    message = update['message']

    # 命令处理器
    if bot and message['entities'][0]['type'] == 'bot_command':
        bot = telebot.TeleBot(tele_token)
        ret, msg = command_handler(message, bot)
        if ret == 0:
            return(msg)
        print(bot.get_me())
    return("Received message: " + json.dumps(message, indent = 2))


def command_handler(message: dict, bot: telebot.TeleBot) -> tuple[int, str]:
    command_args: str = message['text'].split(" ")
    if command_args[0] == '/echo':
        bot.send_message(message['chat']['id'], message['text'][6:], reply_to_message_id=message['message_id'])
        return 0, "Echo command exec success"
    if command_args[0] == '/askgpt':
        try:
            bot.send_message(message['chat']['id'], askgpt(message['text'][8:]), reply_to_message_id=message['message_id'], parse_mode="MarkdownV2")
        except Exception as e:
            bot.send_message(message['chat']['id'], "Error:\n==========\n" + str(e.args))
            ret = bot.forward_message(os.getenv('tg_admin'), message['chat']['id'], message['message_id'])
            tg_admin: str | None = os.getenv('tg_admin')
            if tg_admin:
                bot.send_message(tg_admin, "Error:\n==========\n" + str(e.args) + "\n\nTraceback:\n==========\n" + traceback.format_exc(),
                    reply_to_message_id=ret.message_id)
            print("Error:\n==========\n" + str(e.args) + "\n\nTraceback:\n==========\n" + traceback.format_exc())
            return 1, "Askgpt command exec error, traceback send to admin"
        else:
            return 0, "Askgpt command exec success"
    return 1, "No command is matched"


def askgpt(prompt: str) -> str:
    openai.api_key = os.getenv('openai_api_key')
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-1106",
        messages=[
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    print("Answer:\n" + completion.choices[0].message.content)
    return completion.choices[0].message.content