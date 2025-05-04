from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosClientError, CosServiceError
import os
import logging
import sys

# 设置日志级别
logging.basicConfig(level=logging.INFO, stream=sys.stdout)


class COSUploader:
    def __init__(self, bucket, region="ap-hongkong"):
        """初始化 COSUploader 类，设置 COS 配置和客户端"""
        self.secret_id = os.environ["COS_SECRET_ID"]  # 从环境变量中获取 SecretId
        self.secret_key = os.environ["COS_SECRET_KEY"]  # 从环境变量中获取 SecretKey
        self.token = None  # 如果使用永久密钥，token 保持为 None
        self.scheme = "https"  # 使用 https 协议访问 COS

        self.config = CosConfig(
            Region=region,
            SecretId=self.secret_id,
            SecretKey=self.secret_key,
            Token=self.token,
            Scheme=self.scheme,
        )

        self.client = CosS3Client(self.config)
        self.bucket = bucket  # 存储桶名

    def upload(self, key, local_file_path, enable_md5=False, retries=10):
        """
        上传文件到 COS。

        :param key: 文件在 COS 中的路径
        :param local_file_path: 本地文件路径
        :param enable_md5: 是否启用 MD5 校验
        :param retries: 失败时重试的次数，默认重试 10 次
        :return: 返回上传文件的响应
        """
        try:
            # 使用高级接口上传文件
            response = self.client.upload_file(
                Bucket=self.bucket,
                Key=key,
                LocalFilePath=local_file_path,
                EnableMD5=enable_md5,
            )
            return response

        except (CosClientError, CosServiceError) as e:
            logging.error(f"上传失败: {e}")
            for i in range(retries):
                try:
                    logging.info(f"正在重试上传: 第 {i+1} 次")
                    response = self.client.upload_file(
                        Bucket=self.bucket, Key=key, LocalFilePath=local_file_path
                    )
                    return response
                except (CosClientError, CosServiceError) as retry_e:
                    logging.error(f"重试失败: {retry_e}")
            raise Exception(f"文件上传失败，已重试 {retries} 次")


# 提供给其他文件调用的上传接口
def upload_file_to_cos(bucket, key, local_file_path, retries=10, region="ap-hongkong"):
    uploader = COSUploader(bucket, region="ap-hongkong")
    return uploader.upload(key, local_file_path, retries=retries)
