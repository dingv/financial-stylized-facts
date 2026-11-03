import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts import AnalysisConfig,analyze_csv
from financial_stylized_facts.demo import synthetic_prices,activity_prices,run_demo


def test_packaged_generator_preserves_seeded_process_and_distinct_paths():
    frame=synthetic_prices(seed=23,n=600)
    assert len(frame)==5*601 and frame.asset_id.nunique()==5
    pd.testing.assert_frame_equal(frame,synthetic_prices(seed=23,n=600))
    gaussian=frame[frame.asset_id=="Gaussian iid"].price.to_numpy()
    np.testing.assert_allclose(np.diff(np.log(gaussian)),np.random.default_rng(23).normal(size=600)*.001,atol=1e-14)
    assert frame.groupby("asset_id").session_id.nunique().eq(1).all()


def test_activity_construction_has_opposite_time_direction_and_aligned_volume():
    data=activity_prices(seed=23,n_blocks=300)
    forward=data[data.path_id=="Coarse leads fine"]
    backward=data[data.path_id=="Time reversed"]
    r=np.diff(np.log(forward.price.to_numpy()))
    np.testing.assert_allclose(np.diff(np.log(backward.price.to_numpy())),r[::-1],atol=1e-14)
    np.testing.assert_allclose(backward.volume.to_numpy()[1:],forward.volume.to_numpy()[1:][::-1])
    blocks=r.reshape(-1,2)
    coarse=np.abs(blocks.sum(axis=1))
    fine=np.abs(blocks).mean(axis=1)
    np.testing.assert_allclose(fine[1:],.001+coarse[:-1],atol=1e-14)


@pytest.mark.parametrize("kwargs",[{"observations":10},{"observations":10001},{"kind":"activity","observations":513},
                                  {"seed":-1},{"kind":"unknown"}])
def test_demo_rejects_invalid_settings_before_writing(tmp_path,kwargs):
    output=tmp_path/"demo"
    with pytest.raises(ValueError):
        run_demo(output,**kwargs)
    assert not output.exists()


def test_public_api_rejects_existing_output_without_changing_input(tmp_path):
    source=tmp_path/"prices.csv"
    source.write_text("timestamp,price\n2024-01-01T00:00:00Z,100\n")
    output=tmp_path/"existing"
    output.mkdir()
    before=source.read_bytes()
    with pytest.raises(FileExistsError):
        analyze_csv(source,output,AnalysisConfig())
    assert source.read_bytes()==before and not list(output.iterdir())


def test_packaged_demo_cli_is_self_contained_and_no_overwrite(tmp_path):
    output=tmp_path/"demo"
    command=[sys.executable,"-m","financial_stylized_facts","demo","--kind","activity",
             "--observations","512","--output",str(output)]
    proc=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert (output/"report/index.html").exists()
    manifest=json.loads((output/"demo.json").read_text())
    results=json.loads((output/"report/results.json").read_text())
    assert manifest["generator"]["observations_per_path"]==512
    assert manifest["canonical_sha256"]==results["provenance"]["input_sha256"]
    assert len(results["groups"])==2
    assert all(g["volume_volatility"]["status"]=="computed" for g in results["groups"])
    snapshot={str(p.relative_to(output)):p.read_bytes() for p in output.rglob("*") if p.is_file()}
    duplicate=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True)
    assert duplicate.returncode==2 and "Traceback" not in duplicate.stderr
    assert {str(p.relative_to(output)):p.read_bytes() for p in output.rglob("*") if p.is_file()}==snapshot
