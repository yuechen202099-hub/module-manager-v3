# 评价报告目录

本目录保存 V2.x 的产品评价报告。

## 生成方式

标准生成：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-product-evaluation.ps1 -Change "说明本次修改"
```

跳过自动检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-product-evaluation.ps1 -SkipChecks -Change "说明本次修改"
```

## 使用规则

- 生产发布前后各生成一份。
- 核心业务修改完成后生成一份。
- 正式运行期间每周至少生成一份。
- 小修改可以只追加到最近一份报告的“变更记录”。
- 报告不得写入服务器密码、数据库密码、OSS AccessKey、JWT 密钥。

评分标准见：

```text
docs/PRODUCT_EVALUATION_RULES.md
```
