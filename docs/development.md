# 开发环境

本项目统一使用 **Conda 环境 `financial-stylized-facts`**，不用 venv。

服务器环境路径为 `/home/dingwei/envs/financial-stylized-facts`；代码位于 `/home/dingwei/financial-stylized-facts`。两者分开保存，Git 只管理代码和环境配方。

## 日常使用

在服务器终端运行：

```bash
source /opt/anaconda3/etc/profile.d/conda.sh
conda activate financial-stylized-facts
cd /home/dingwei/financial-stylized-facts
```

如果当前终端已经能使用 `conda activate`，可以省略第一行。在 VS Code 中选择这个环境的 Python：
`/home/dingwei/envs/financial-stylized-facts/bin/python`。

## 环境里有什么

NumPy、SciPy、Pandas 用于数值和数据处理，Matplotlib 用于画图，statsmodels 用于统计交叉验证，Jinja2 用于报告模板，pytest 用于测试。当前 Python 包已提供十一项描述诊断、适用的近似统计证据与 HTML 报告；方法范围见[评估方案](evaluation-plan.md)。

`environment.yml` 固定主要版本系列；`environments/linux-64.explicit.txt` 保存本次安装的确切包构建和下载校验信息。前者便于维护，后者用于 Linux x86-64 上重建同一组包。此环境不包含 GPU 计算依赖，已安装条件厚尾所需 arch 8.0.0。

本次环境已实际验证：收益与峰度计算、ACF、时间采样、PNG 输出和 HTML 模板均可运行；`pip check` 通过，原有 base 与 sasaki-fx 的 Conda 包记录未变化。

| 组件 | 已验证版本 |
| --- | --- |
| python | 3.12.15 |
| numpy | 2.2.6 |
| scipy | 1.15.2 |
| pandas | 2.2.3 |
| matplotlib | 3.10.9 |
| statsmodels | 0.15.0 |
| jinja2 | 3.1.6 |
| pytest | 8.4.2 |
| arch | 8.0.0 |

## 在另一台机器重建

一般按维护配方创建：

```bash
conda env create -f environment.yml
conda activate financial-stylized-facts
python -m pip install --no-deps --no-build-isolation -e .
```

如需在 Linux x86-64 上使用本次精确版本，在尚不存在该环境时运行：

```bash
conda create -n financial-stylized-facts --file environments/linux-64.explicit.txt
conda activate financial-stylized-facts
python -m pip install --no-deps --no-build-isolation -e .
```

若同名环境已存在，先检查，不删除或覆盖。精确清单只覆盖 Conda 包；最后一条命令将当前 Git 版本的项目安装为可编辑包。因此复现时也需记录 Git 提交号。

## 后续加包

激活这个环境再安装。确有新依赖时同时更新配方、精确清单和相关验证，不例行升级所有包。不改 Conda base 或已有的 sasaki-fx 环境。

Conda 对维护配方和精确环境导出的说明见[官方环境管理文档](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html)。

## 安装包验收

```bash
python tools/verify_distribution.py --output /tmp/fsf-package-trial
```

使用新的 tmp 目录。工具从源码副本生成 sdist，再从解包的 sdist 生成 wheel；把 wheel 装到临时目录，在源码目录之外核对导入来源、完整测试和三种演示。共享当前 Conda 的依赖，不创建 venv、不修改当前已安装的项目，也不声称重新求解了依赖。`verification.json` 保存包哈希与验收结果，`verification.log` 保存详细命令输出。

GitHub 工作流另外从 `environment.yml` 建立新的 Conda 环境执行同一验收。只有实际运行通过后才能将其计入兼容性证据；工作流文件本身不等于验证完成。发布上传不包含在自动化中。
