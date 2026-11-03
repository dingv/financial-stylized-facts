"""Read-only release inventory. Findings contain names, never matched secrets.

Not a complete security or legal audit. Run before publishing a fixed commit.
"""
import argparse
import hashlib
import json
import re
import subprocess
from importlib.metadata import distributions
from pathlib import Path


PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "github_token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})",
    "aws_access_id": rb"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "credential_url": rb"https?://[^\s/:]+:[^\s/@]+@",
}


def audit(repo, output):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
    findings, current = [], []
    def scan(content, name, scope):
        for label, pattern in PATTERNS.items():
            if re.search(pattern, content):
                findings.append({"scope": scope, "path": name, "category": label})
        if len(content) > 2_000_000:
            findings.append({"scope": scope, "path": name, "category": "file_over_2MB"})
    for name in names:
        p = repo/name
        if not p.is_file():
            findings.append({"scope":"working_tree", "path":name,"category":"missing_or_non_file"})
            continue
        content = p.read_bytes()
        scan(content, name, "working_tree")
        if p.suffix.lower() in {".csv", ".pdf", ".sqlite", ".pem", ".key"} or any(part in {"raw", ".ssh", ".aws"} for part in p.parts):
            findings.append({"scope":"working_tree", "path":name,"category":"review_data_or_sensitive_path"})
        current.append({"path":name,"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()})
    blobs = 0
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        oid, _, name = line.partition(" ")
        if git("cat-file", "-t", oid).strip() == b"blob":
            blobs += 1
            scan(git("cat-file", "blob", oid), name, "reachable_git_history")
    packages = []
    for dist in sorted(distributions(), key=lambda d:d.metadata.get("Name", "").lower()):
        meta = dist.metadata
        licenses = []
        for item in dist.files or []:
            if any(s in str(item).lower() for s in ["license", "copying", "copyright"]) and not str(item).endswith((".py", ".pyc")):
                path = Path(dist.locate_file(item))
                if path.is_file():
                    licenses.append({"path":str(item),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        packages.append({"name":meta.get("Name"),"version":dist.version,
                         "license_expression":meta.get("License-Expression"),
                         "license_classifiers":[v for v in meta.get_all("Classifier",[]) if v.startswith("License ::")],
                         "license_files":licenses})
    result = {"head":git("rev-parse","HEAD").decode().strip(),
              "working_tree_clean":not bool(git("status","--porcelain").strip()),
              "current_files":current, "reachable_blobs_scanned":blobs, "findings":findings,
              "python_distributions":packages,
              "limits":"Pattern scan only; not proof of no secrets, no full legal or vulnerability audit; not publication approval."}
    (output/"audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"files":len(current),"reachable_blobs":blobs,"findings":findings,
                      "distributions":len(packages),"output":str(output/"audit.json")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    audit(args.repo,args.output)
