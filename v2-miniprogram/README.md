# 施工采集微信小程序

AppID：`wx5334c0fcd7afc72e`

## 打开方式

1. 安装并打开微信开发者工具。
2. 选择“导入项目”。
3. 项目目录选择：`模块更换项目管理器V2.0/v2-miniprogram`。
4. AppID 使用：`wx5334c0fcd7afc72e`。
5. 进入后先打开“详情”，体验版阶段勾选“不校验合法域名、web-view 域名、TLS 版本以及 HTTPS 证书”。

## 当前体验版接口

备案和域名证书完成前，默认接口先使用：

`https://www.sgcc.online`

配置位置：

`miniprogram/utils/config.js`

体验版和正式版均固定使用：

`https://www.sgcc.online`

## 上传体验版

1. 微信开发者工具右上角点击“上传”。
2. 版本号建议填写：`0.1.0-experience`。
3. 项目备注填写：`施工采集体验版`。
4. 到微信公众平台后台，进入“管理 -> 版本管理”。
5. 将刚上传的开发版本设为体验版。
6. 在“成员管理 -> 体验成员”中添加内部施工员微信号。
7. 施工员扫码体验版二维码使用。

## 正式发布前必须配置

在微信公众平台进入：

`开发管理 -> 开发设置 -> 服务器域名`

至少配置：

- request 合法域名：`https://www.sgcc.online`
- uploadFile 合法域名：`https://www.sgcc.online`
- downloadFile 合法域名：`https://www.sgcc.online`

小程序端不再开放手动填写服务器地址，避免施工员误填裸域或 IP。

## 当前功能

- 施工员登录。
- 只显示管理员已开放的施工终端。
- 施工员最多同时处理 5 个已指派终端。
- 只显示未施工资料组。
- 采集器扫码录入。
- 模块资产编号扫码录入。
- 五类照片槽位拍照或选图。
- 上传前压缩照片。
- 弱网/断网时保存本机缓存。
- 网络恢复后自动补传，也可手动上传缓存。
- 上传成功后清理本机缓存照片。

## 后端复用接口

- `POST /auth/login`
- `GET /local-test/construction/tasks`
- `POST /local-test/construction/tasks/{task_id}/claim`
- `POST /local-test/construction/tasks/{task_id}/release`
- `GET /local-test/construction/tasks/{task_id}/groups`
- `GET /local-test/groups/{group_id}`
- `POST /local-test/construction/groups/{group_id}/upload-batch`

## 注意事项

- 小程序正式版不允许使用裸 IP 作为接口域名。
- 原生小程序端使用 `wx.scanCode` 调用微信扫码能力。`serratus/quaggaJS` 依赖浏览器 DOM、video 和 canvas，继续保留在网页施工端使用，不直接放进原生小程序运行。
- `wx.scanCode` 只返回扫码编号，不会复用扫码画面作为采集器照片；采集器照片需要在照片槽位中单独拍摄。
- 施工上传不代表审阅完成，上传后仍进入网页审阅工作台归档。
