#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check an actual release with production installer parsing, without a device."""
import argparse,importlib.util,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('release',type=Path);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install-to-emmc.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
d=json.loads((a.release/'manifest.json').read_text());f=a.release/d['compressed']['name']
m.validate_manifest(d,f);m.verify_source(f,d)
report={'result':'PASS','validation':['production validate_manifest','production verify_source: compressed hash, MBR, full raw hash, EOF'],'image':str(f),'raw_bytes':d['image']['bytes'],'raw_sha256':d['image']['sha256'],'devices_opened':False}
a.report.write_text(json.dumps(report,indent=2)+'\n')
