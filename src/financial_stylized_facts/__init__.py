"""Cross-market diagnostics. Public entry points: AnalysisConfig, analyze_csv."""

__version__ = "0.14.0.dev0"

from .data import AnalysisConfig

__all__ = ["AnalysisConfig","analyze_csv","__version__"]


def analyze_csv(input_path,output_dir,config=None,*,title="金融市场 · 统计评估报告",source_provenance=None):
    """Analyze canonical prices into a new directory; returns the results dict.

    Never modifies input, downloads data, or overwrites an existing output.
    The plotting/report modules load only when analysis is requested.
    """
    from .report import analyze_csv as analyze
    return analyze(input_path,output_dir,config,title=title,source_provenance=source_provenance)
