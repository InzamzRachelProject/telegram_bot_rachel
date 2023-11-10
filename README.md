# TelegramBotRachel

## Before All

回归本心了，最近尝试了腾讯云的 scf，发现延迟完全可以接受，使用 `webhook` 监控信息进行回复。而且不需要担心客户端程序出错重启，每次都启动一个新函数实例，稳定性和费用都有所减少。

这是我的第二个电报机器人尝试，这一切的契机源自接触了 Serverless ，其中的函数计算和工作流的运作方式让我觉得我的机器人可以进行改造（~~从节约成本角度来说，机器人的工作量并不大，但是需要安装客户端翻墙或者购买墙外服务器，开销大一点。而且单独挂一个机器人有点浪费资源~~）。

Telegram 提供了 Webhook 订阅，~~于是计划将机器人打造成通过 Webhook 响应的一系列云函数~~。选用的语言也是我一直很想尝试的 Go ，也是从零开始学习 Go 的一次学习。

事实上我当时预计的是启用云函数的延迟也许可以忽略，但事实上并不可以。整个操作的延迟比较大，无法接受。一些任务的执行会采用云函数，其他还是部署在服务器上。服务器采用的是香港的轻量级云服务器。

## Rachel

Rachel 来源于海伯利安中学者索尔·温博特的女儿之名。伯劳触摸她以后她开始逆时而行，被逆熵场包围。我很喜欢这个故事，于是我的这个机器人暂时命名为 Rachel（瑞秋）。

Rachel 是这个项目的核心，后续计划将一些小工具都开放对接接口，使用 Rachel 监控以及控制，作为 Serverless 的中枢系统。

## Doc

English Version will update later...
~~Maybe~~

## TODO

- [x] 重构代码
- [x] Echo
- [ ] OjContestCanlanderWithLark
- [ ] OjContestCanlanderWithGoogle
- [ ] AppleBooksNoteExport
- [ ] EveryDayMSG
- [ ] Fitness Summary
- [ ] Codeforces PeekingTom
- [x] Trans to Webhook Mode
