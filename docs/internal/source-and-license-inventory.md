# 来源与许可准备清单

2026-11-03 核对专用 Conda 中的包元数据和自带许可文件。这里只记录来源；不是法律审查结论，也不把依赖许可视为本项目已经选定的许可。正式代码许可和维护者署名见待确认的 [发布决定](../release-readiness.md)。

本库的工程实现按技术文档中的公式编写，通过第三方函数交叉核对；没有 vendored 的第三方源码目录。依赖通过正常安装取得，wheel 不捆绑这些包、Conda 环境或字体文件。报告由 Matplotlib 渲染为 PNG，不嵌入字体文件。

| 直接依赖 / 工具 | 已核对版本 | 自带许可标识或文件 |
| --- | --- | --- |
| NumPy | 2.2.6 | BSD 类，dist-info/LICENSE.txt；数值组件的单独条款仍保留在原包 |
| SciPy | 1.15.2 | BSD 类，dist-info/LICENSE.txt；随包子组件另有许可 |
| Pandas | 2.2.3 | BSD-3-Clause，dist-info/LICENSE |
| Matplotlib | 3.10.9 | 基于 PSF 的 Matplotlib 许可，dist-info/LICENSE；字体另有许可 |
| Jinja2 | 3.1.6 | BSD，dist-info/licenses/LICENSE.txt |
| arch（可选） | 8.0.0 | NCSA，dist-info/licenses/LICENSE.md |
| statsmodels（测试参考） | 0.15.0 | BSD-3-Clause，dist-info/licenses/LICENSE.txt |
| pytest（测试） | 8.4.2 | MIT，dist-info/licenses/LICENSE |
| setuptools（构建） | 84.0.0 | MIT；构建工具自带的子组件保持自身许可 |

以上是本次验证版本，不声称覆盖依赖范围内所有将来的版本。[Matplotlib 官方许可说明](https://matplotlib.org/stable/project/license.html)、[arch 官方许可文件](https://github.com/bashtage/arch/blob/main/LICENSE.md)可补充核对。`tools/audit_release.py` 导出实际安装的所有 Python distribution 元数据及许可文件哈希；未把软件包 metadata 当成已经审阅每个传递依赖完整条款。

## 数据与研究材料

- EBS、FRED 与 Bokeh 股票样本只在外部路径读取，原行情及论文 PDF 不在源码或安装包中。
- Bokeh 样本可公开下载不等于本项目已经取得任意再分发授权；真实数据报告也可能透露行情，不默认发布。
- `fsf demo` 的合成序列由本库生成；种子和公式随包提供。它们不包含原行情片段。
- 方法引用见 [参考资料](../references.md)。没有将论文图片、段落或第三方实现复制成项目资产。

## 检查边界

发布扫描会检查当前文件、Git 可达历史中的常见凭据模式、大文件和高风险路径，只输出文件名/模式类别，不回显疑似秘密。规则扫描不能证明不存在任何秘密；公开前还应复核发布差异及署名。开发文档含已有服务器目录与项目背景，属于有意记录的环境说明；公开前可移除不需要的本地部署信息，不能当作密码处理。
