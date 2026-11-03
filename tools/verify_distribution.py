"""Build sdist -> wheel and exercise the installed wheel outside the source tree.

Use the project's Conda Python. No venv, dependency installation or network calls.
Installed package files are isolated; dependency versions come from that Conda.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile


def verify(source,output):
    source,output=Path(source).resolve(),Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    if hasattr(os,"sched_getaffinity"):
        os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    env=dict(os.environ,OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",PIP_NO_INDEX="1")
    env.pop("PYTHONPATH",None)
    env.pop("PYTHONHOME",None)
    started=time.monotonic()
    log=output/"verification.log"
    def run(command,cwd,extra_env=None):
        with log.open("a") as stream:
            stream.write("\nCOMMAND: "+repr(command)+"\n")
            stream.flush()
            subprocess.run(command,cwd=cwd,env={**env,**(extra_env or {})},stdout=stream,stderr=subprocess.STDOUT,
                           check=True,timeout=120)
    tree=output/"source-copy"
    tree.mkdir()
    for name in ["pyproject.toml","README.md","MANIFEST.in","environment.yml","src","docs","examples","tests","tools","environments",".github"]:
        src=source/name
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src,tree/name,ignore=shutil.ignore_patterns("__pycache__","*.egg-info",".DS_Store",".pytest_cache"))
        else:
            shutil.copy2(src,tree/name)
    dist=output/"dist"
    dist.mkdir()
    run([sys.executable,"-c","from setuptools.build_meta import build_sdist; build_sdist("+repr(str(dist))+")"],tree)
    archive=next(dist.glob("*.tar.gz"))
    unpack=output/"unpacked"
    unpack.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path=Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected archive member: "+member.name)
        tar.extractall(unpack,filter="data")
    unpacked=next(unpack.iterdir())
    for name in ["docs/usage.md","docs/internal/statistical-contract.md","tests/test_report.py","tools/verify_distribution.py","src/financial_stylized_facts/demo.py"]:
        assert (unpacked/name).is_file(),name
    run([sys.executable,"-c","from setuptools.build_meta import build_wheel; build_wheel("+repr(str(dist))+")"],unpacked)
    wheel=next(dist.glob("*.whl"))
    with zipfile.ZipFile(wheel) as zipped:
        members=zipped.namelist()
        assert "financial_stylized_facts/templates/report.html" in members
        assert "financial_stylized_facts/demo.py" in members
        assert all(not p.startswith(("data/","tests/","examples/",".git/")) for p in members)
    target=output/"installed"
    run([sys.executable,"-m","pip","install","--no-deps","--no-compile","--target",str(target),str(wheel)],output)
    runner=output/"isolated_cli.py"
    runner.write_text('''import importlib.abc, importlib.metadata, json, pathlib, sys
target=pathlib.Path(sys.argv.pop(1)).resolve()
sys.path.insert(0,str(target))
if "--without-arch" in sys.argv:
    sys.argv.remove("--without-arch")
    class NoArch(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname=="arch" or fullname.startswith("arch."):
                raise ModuleNotFoundError("arch deliberately unavailable in optional-dependency audit")
    sys.meta_path.insert(0,NoArch())
import financial_stylized_facts as package
assert pathlib.Path(package.__file__).resolve().is_relative_to(target)
dist=importlib.metadata.distribution("financial-stylized-facts")
assert pathlib.Path(dist.locate_file("")).resolve()==target
assert package.__version__==dist.version
from financial_stylized_facts.cli import main
raise SystemExit(main(sys.argv[1:]))
''',encoding="utf-8")
    isolated=[sys.executable,"-I",str(runner),str(target)]
    run(isolated+["--version"],output)
    # Also exercise the actual installed console script, not only python -m.
    entry=target/("Scripts/fsf.exe" if os.name=="nt" else "bin/fsf")
    run([str(entry),"--help"],output,{"PYTHONPATH":str(target)})
    run([sys.executable,"-m","pytest","-q",str(unpacked/"tests")],unpacked,{"PYTHONPATH":str(target)})
    cases=[("basic",2400,False),("activity",2400,False),("activity-no-arch",512,True)]
    report_rows=[]
    for label,n,no_arch in cases:
        dest=output/label
        command=isolated+(["--without-arch"] if no_arch else [])+["demo","--kind","activity" if label.startswith("activity") else "basic",
                      "--observations",str(n),"--output",str(dest)]
        run(command,output)
        result=json.loads((dest/"report/results.json").read_text())
        manifest=json.loads((dest/"demo.json").read_text())
        assert len(result["coverage"])==11
        assert all(len(g["findings"]["by_fact"])==11 and g["distribution"]["n"]==n for g in result["groups"])
        assert result["provenance"]["input_sha256"]==hashlib.sha256((dest/"prices.csv").read_bytes()).hexdigest()
        assert manifest["canonical_sha256"]==result["provenance"]["input_sha256"]
        assert result["provenance"]["package_version"]==manifest["generator"]["package_version"]
        if no_arch:
            assert all(g["conditional_tails"]["status"]=="dependency_missing" for g in result["groups"])
        text=(dest/"report/index.html").read_text()
        assert "data:image/png;base64," in text and '<script src=' not in text
        report_rows.append({"case":label,"paths":len(result["groups"]),"n_per_path":n,
                            "input_sha256":result["provenance"]["input_sha256"],
                            "conditional_status":[g["conditional_tails"]["status"] for g in result["groups"]]})
    summary={"passed":True,"package_isolated_from_source":True,"shared_conda_dependencies":True,"sdist_tests_against_wheel_passed":True,
             "source_archive":archive.name,"wheel":wheel.name,"wheel_sha256":hashlib.sha256(wheel.read_bytes()).hexdigest(),
             "cases":report_rows,"elapsed_seconds":time.monotonic()-started}
    (output/"verification.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    verify(args.source,args.output)
