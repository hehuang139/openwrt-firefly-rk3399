#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify fixed source-kit inputs before extraction/building."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
data=json.loads((root/'source/provenance/build-inputs.json').read_text())
for item in data['files']:
    path=root/item['path']
    assert not path.is_symlink() and path.is_file(),str(path)
    assert path.stat().st_size==item['bytes'],str(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],str(path)
print(f"PASS: {len(data['files'])} fixed build inputs")
