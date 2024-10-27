import os
import traceback
import requests
from typing import Tuple, List

import requests
import redis
import json

r = redis.from_url(os.getenv("REDIS_URL"))
# Initialize Redis connection

def askgpt(prompt: str, module: str, user_id: str, base64_image: str = None) -> str:
    url = os.getenv("OPENAI_API_URL")
    allowed_users = os.getenv("ALLOWED_USERS", "").split(',')
    print(f"ALLOWED_USERS: {allowed_users}")
    print(f"User: {user_id}_call_count, Count: {r.get(user_id)}")
    print(f"Ask GPT: {prompt}")

    # Limit user's calls by checking redis 
    if user_id not in allowed_users:
        user_count = r.get(f"{user_id}_call_count")
        if user_count is not None and int(user_count) >= os.getenv("MAX_CALLS", 5):
            return "You have exceeded the maximum number of calls to this service."
        else:
            r.setex(f"{user_id}_call_count", 7200, 1 if user_count is None else int(user_count) + 1)

    # Get previous context
    past_conversation = r.get(f'{user_id}_context')
    if past_conversation is None:
        past_conversation = [
            {
                "role": "system",
                "content": "You are an awesome chatbot"
            }
        ]
    else:
        past_conversation = json.loads(past_conversation)
    
    # Add new user's message
    if base64_image:
        past_conversation.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        )
    else:
        past_conversation.append(
            {
                "role": "user",
                "content": prompt
            },
        )

    payload = {
        "model": module,
        "messages": past_conversation,
        "stream": False,
        "max_tokens": 2048,
    }
    headers = {"Authorization": "Bearer " + os.getenv("OPENAI_API_KEY")}

    response = requests.post(url, json=payload, headers=headers, stream=False).json()
    
    # Save current context
    past_conversation.append(
        {
            "role": "assistant",
            "content": response["choices"][0]["message"]["content"]
        }
    )
    r.setex(f'{user_id}_context', 7000, json.dumps(past_conversation))

    return  response["choices"][0]["message"]["content"]

def pic_generator(
    module: str,
    prompt: str,
    enabled_rewrite: bool = False,
    return_type: str = "url",
    size="1024x1024",
) -> [int, str]:
    # 通过环境变量获取秘钥和模型ID以及 api 端点
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_endpoint = os.environ.get("OPENAI_IMAGE_ENDPOINT")

    print(f"Moudle: {module}")
    print(f"Prompt: {prompt}")
    # 通过 OpenAI API 生成图片
    header = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }
    data = {"model": module, "prompt": prompt, "n": 1, "size": size}

    response = requests.post(openai_endpoint, headers=header, json=data)

    print(response.json())
    if response.status_code != 200:
        raise Exception(
            f"OpenAI API 请求失败，状态码：{response.status_code}，错误信息：{response.text}"
        )

    # 获取生成的图片的 URL
    generated_image_url = response.json()["data"][0]["url"]

    if return_type == "url":
        return 0, generated_image_url
    elif return_type == "base64":
        # 通过图片的 URL 获取图片的 base64 编码
        response = requests.get(generated_image_url)
        if response.status_code != 200:
            raise Exception(
                f"获取生成的图片失败，状态码：{response.status_code}，错误信息：{response.text}"
            )

        return 0, response.json()["image"]
    else:
        raise Exception(f"不支持的返回类型：{return_type}")
