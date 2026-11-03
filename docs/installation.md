# 安装与第一次试用

当前是私有试用版，**尚未上传 PyPI**。已经获得仓库访问权限的人可从源码安装；收到 wheel 文件的人可直接安装文件。暂不使用 `pip install financial-stylized-facts` 从公共索引安装，以免误装同名项目。

## 从源码安装

先取得仓库，再在仓库目录中运行：

```bash
git clone https://github.com/dingv/financial-stylized-facts.git
cd financial-stylized-facts
conda env create -f environment.yml
conda activate financial-stylized-facts
python -m pip install --no-deps --no-build-isolation .
python -m pip check
fsf --version
```

这里统一使用 Conda，不使用 venv。配方包含报告、条件厚尾和验证所需依赖，不需要 GPU。已有同名环境时先检查，不删除或覆盖；维护者可按[开发说明](development.md)使用现有环境。

私有仓库的 HTTPS 克隆需要你自己的 GitHub 访问方式；不要把密码或 token 写进命令、脚本或分享的配置。正式公开后再更新访问说明。

## 从 wheel 文件安装

在已有本项目依赖的 Conda 环境中：

```bash
conda activate financial-stylized-facts
python -m pip install --no-deps /path/to/financial_stylized_facts-VERSION-py3-none-any.whl
python -m pip check
fsf --version
```

把示例路径和 VERSION 换成实际文件。若环境尚未准备好，先使用随源码提供的 `environment.yml`。基础库依赖 NumPy、SciPy、Pandas、Matplotlib、Jinja2；条件厚尾另外依赖 arch。不安装 arch 也能运行其他诊断，报告会明确显示条件厚尾不可用。

## 不准备市场数据，先看演示

选一个**尚不存在**的输出目录：

```bash
fsf demo --output /tmp/fsf-first-demo
```

打开 `/tmp/fsf-first-demo/report/index.html`。报告提供五种已知性质的合成序列，切换下拉框即可比较。`prices.csv` 保存生成的数据，`demo.json` 保存种子、生成参数与分析设置；同版本、同种子和配置可重现。它不是下载的市场行情，也不是拟合真实市场的模型。

默认每条路径 2400 个一分钟收益。增加 `--seed 123` 可以换种子，增加 `--observations 5000` 可以用更长的合成样本。程序不会覆盖已有输出目录；重试时请换新目录。

另一个示例专门展示人为构造的量价关系与时间方向：

```bash
fsf demo --kind activity --output /tmp/fsf-activity-demo
```

它同时展示原过程与时间反转。关系是按公式构造的，仅用于理解与核对算法，不能当成真实市场证据。

## 在服务器运行，怎样看报告

HTML 已嵌入图像，可从 VS Code 资源管理器把 `report/index.html` 下载到本地，用浏览器打开，不需要启动网站服务或开放服务器端口。若需要自己重新画图或核对数值，再一起下载同目录的 JSON 和 CSV。

自己的数据从[使用指南](usage.md)开始；真实数据源的字段转换见[数据指南](data-guide.md)。支持与限制见[评估方法](evaluation-plan.md)。首版只承诺已记录环境的验证结果，不把 Python 版本范围或通用 wheel 标签当作所有系统已测试的证明。
