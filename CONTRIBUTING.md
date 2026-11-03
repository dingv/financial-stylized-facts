# Contributing

欢迎提交问题、方法改进与数据适配器。提交 issue 时，请提供运行命令、输入字段、配置、预期结果与实际输出。小型可复现样本比完整行情文件更便于排查。

## 开发环境

```bash
conda env create -f environment.yml
conda activate financial-stylized-facts
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest -q
```

## 方法与测试

统计方法的变更需说明估计对象、时间单位、缺失处理和参考来源，并补充手算、独立参考实现或已知性质测试。合成序列用于检验算法；面向用户的示例与报告使用有来源记录的真实数据。

结果结构发生变化时，更新相应导出与文档。报告正文解释图表与发现，计算细节放统计方法文档。

## 数据与提交

`data/examples/` 存放随仓库分发的小型真实样本，新增样本需记录来源、字段、变换、SHA256 和分发条件。个人研究数据放 `data/raw/`，不会被 Git 跟踪；临时输出放 tmp。

提交聚焦代码、测试、用户文档或精选示例，不包含环境目录、个人配置、密钥、开发日志或批量输出。
