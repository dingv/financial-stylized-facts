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

NumPy、SciPy、Pandas 用于数值和数据处理，Matplotlib 用于画图，statsmodels 用于统计交叉验证，Jinja2 用于后续报告模板，pytest 用于测试。当前 Python 包仍是骨架，环境可用不代表评估功能已经实现。

`environment.yml` 固定主要版本系列；`environments/linux-64.explicit.txt` 保存本次安装的确切包构建和下载校验信息。前者便于维护，后者用于 Linux x86-64 上重建同一组包。此环境不包含 GPU 计算依赖，也未安装后续可选的 GARCH 包 arch。

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
