import os
import traceback
import requests
from typing import Tuple, List

def pic_generator(module: str, prompt: str, enabled_rewrite: bool = False, return_type: str = "url") -> [int, str]:
    # 通过环境变量获取秘钥和模型ID以及 api 端点
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_endpoint = os.environ.get("OPENAI_IMAGE_ENDPOINT")

    print(f"Moudle: {module}")
    print(f"Prompt: {prompt}")
    # 通过 OpenAI API 生成图片
    header = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": module,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    
    response = requests.post(openai_endpoint, headers=header, json=data)
    
    print(response.json())
    if response.status_code != 200:
        raise Exception(f"OpenAI API 请求失败，状态码：{response.status_code}，错误信息：{response.text}")
    
    # 获取生成的图片的 URL
    generated_image_url = response.json()["data"][0]["url"]

    if return_type == "url":
        return 0, generated_image_url
    elif return_type == "base64":
        # 通过图片的 URL 获取图片的 base64 编码
        response = requests.get(generated_image_url)
        if response.status_code != 200:
            raise Exception(f"获取生成的图片失败，状态码：{response.status_code}，错误信息：{response.text}")
        
        return 0, response.json()["image"]
    else:
        raise Exception(f"不支持的返回类型：{return_type}")

