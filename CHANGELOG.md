##  (2023-11-27)




## 0.3.0 (2023-11-27)

* :sparkles: Finish weekly utils. ([f1a5aa9](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/f1a5aa9))
* :sparkles: Rewrite echo in python. ([4dc244f](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/4dc244f))
* :tada: feat: 迁移到 webhook 框架并且使用 scf 处理 ([b693abc](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/b693abc))
* :tada: Init commit. ([3757c05](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/3757c05))
* :tada: Init commit. ([d2dcf5a](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/d2dcf5a))
* :truck: chore: 优化源码目录结构 ([0305638](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/0305638))
* :wrench: Add JetBrains configure file. ([941aa21](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/941aa21))
* ✨ feat: 添加 rss 订阅函数，获取 rss 的更新信息并发送信息 ([b4846d9](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/b4846d9))
* ✨ feat: 同时解析了 atom 和 rss feed，并且解析所有字段 ([e2476ae](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/e2476ae))
* ✨ feat: 新增功能根据 post 的信息检测 rss 更新 ([bdb6f4e](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/bdb6f4e))
* ✨ feat(webhook): 新增 rss 相关的命令处理逻辑，后续与 rss 订阅组件对接 ([ce808fa](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/ce808fa))
* 🍎 chore: ignore .DS_Store ([cfc2db4](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/cfc2db4))
* 🐛 fix: 修复调用错误时的判断分支，删除测试代码 ([038e9e1](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/038e9e1)), closes [#3](https://github.com/InzamzRachelProject/telegram_bot_rachel/issues/3)
* 🐛 fix: 修复更新数据库时不断增加记录的错误 ([661ad13](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/661ad13)), closes [#2](https://github.com/InzamzRachelProject/telegram_bot_rachel/issues/2)
* 🐛 fix: 修复请求中不存在 force 字段导致的 keyValueError ([337662a](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/337662a)), closes [#1](https://github.com/InzamzRachelProject/telegram_bot_rachel/issues/1)
* 🐛 fix: 修正返回格式为字典 ([a3e02a1](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/a3e02a1))
* 🐛 fix: 修正通过 http 发送请求的错误格式解析 ([c9c87a7](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/c9c87a7))
* 💥 feat: 当前根据 chat_id 的区分 rss 的订阅 hash ([55d2464](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/55d2464))
* 🗃 feat: 适配 rss 订阅数据库的更改 ([6b7b556](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/6b7b556))
* 🚚 chore: 优化目录结构 ([6572ea6](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/6572ea6))
* 🚚 chore: 优化目录结构 ([2845906](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/2845906))
* 🚚 chore: 优化源码目录结构 ([90ec248](https://github.com/InzamzRachelProject/telegram_bot_rachel/commit/90ec248))


### BREAKING CHANGE

* 现在需要传入 chat_id 同时提供通过 chat_id 获取订阅 rss 的接口

- MongoDB 中的 `hash_collection` 结构已更改,通过 chat_id区分文档,每个文档现在包含一个 `subscribe_info` 数组,其中包含哈希、rss_url 和 xml 信息。

参数：
- `event_body`：事件体现在包含必要的参数，包括 `force` 和 `chat_id`。
	- force[string]: 是否忽略缓存,当为 `true` 会忽略缓存
	- chat_id[string]: chat_id 用于标识订阅者并获取其订阅的 RSS URL。

返回格式：
- 返回格式现在包括 RSS URL 作为键，以及对应的新文章作为值的列表。


