# V5.1 GitHub同步与发布规则

V5.1的正式远端仓库为：

`https://github.com/vardy777/stock-screener-v5-1`

## 强制工作流

V5.1后续每个正式开发、修复、验收或发布节点均必须：

1. 明确变更边界与验收标准；
2. 完成针对性测试及必要的全量回归；
3. 执行密钥、运行数据和Git差异检查；
4. 创建边界清晰、可审计的Git提交；
5. 推送至GitHub，并核对远端分支提交哈希；
6. 冻结版本需创建版本标签；正式artifact需作为GitHub Release附件发布并记录SHA-256；
7. 在交付报告中列出提交、标签、测试结果、远端地址和仍待真实窗口验证事项。

未推送到上述远端的本地修改不得宣称为V5.1正式版本。

## 永不上传

- `.env`、PushPlus token、API key、密码、OAuth凭据及其他secret；
- `v5_1/data/`、`v5_1/shadow_data/`、账本、持仓、通知状态和真实运行事实；
- logs、cache、`.pyc`、`__pycache__`和临时审查目录；
- 未验收实验、无关G1修改、历史V5脏改动和用户私有文件。

## 当前边界

- GitHub仓库保持private；
- `research_locked=true`；
- `broker_orders=false`；
- GitHub同步不等于生产切换授权，不改变Scheduler、8899或生产所有权；
- 策略有效性只有在预注册的严格真实证据门禁通过后才能评价。
