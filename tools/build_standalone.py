"""Generate a single-file tester from the exact integration API and sensor paths."""

from __future__ import annotations

import argparse
import ast
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "aesl_smart_meter"
TARGET = ROOT / "tools" / "maha_vidyut_test.py"
CONSTANTS = {
    "BASE_URL",
    "ACCOUNT_SERVICE",
    "DASHBOARD_SERVICE",
    "PAYMENT_SERVICE",
    "REQUEST_PUBLIC_KEY",
    "RESPONSE_KEY_B64",
    "RESPONSE_IV_B64",
}
HEADER = '''"""Standalone MahaVidyut tester: Python 3.10+, no Home Assistant required.

Install: python -m pip install aiohttp==3.13.3 cryptography==46.0.5 certifi==2026.7.22
Run:     python maha_vidyut_test.py --report maha-report.json
Probe:   python maha_vidyut_test.py --probe-only

Generated with tools/build_standalone.py from the integration's API and sensor
paths. Passwords, tokens, consumer IDs and raw responses are never reported.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import re
import secrets
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Any

import aiohttp
import certifi
from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
'''


def render():
    api_source = (COMPONENT / "api.py").read_text()
    const_source = (COMPONENT / "const.py").read_text()
    sensor_source = (COMPONENT / "sensor.py").read_text()
    protocol_digest = hashlib.sha256((api_source + const_source).encode()).hexdigest()
    sensor_digest = hashlib.sha256(sensor_source.encode()).hexdigest()
    constant_nodes = [
        node
        for node in ast.parse(const_source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id in CONSTANTS
            for target in node.targets
        )
    ]
    api_nodes = [
        node
        for node in ast.parse(api_source).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    source_parts = [
        ast.get_source_segment(const_source, node) for node in constant_nodes
    ]
    api_lines = api_source.splitlines(keepends=True)
    source_parts += [
        "".join(
            api_lines[
                min(
                    [node.lineno]
                    + [item.lineno for item in getattr(node, "decorator_list", [])]
                )
                - 1 : node.end_lineno
            ]
        ).rstrip()
        for node in api_nodes
    ]
    metrics = []
    for node in ast.parse(sensor_source).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DESCRIPTIONS"
        ):
            for call in node.value.elts:
                fields = {keyword.arg: keyword.value for keyword in call.keywords}
                metric = {
                    name: ast.literal_eval(fields[name])
                    for name in (
                        "key",
                        "source",
                        "path",
                        "fallback_source",
                        "fallback_path",
                    )
                    if name in fields
                }
                metric["numeric"] = (
                    "native_unit_of_measurement" in fields or "state_class" in fields
                )
                metric["unit"] = (
                    ast.literal_eval(fields["native_unit_of_measurement"])
                    if "native_unit_of_measurement" in fields
                    else None
                )
                metrics.append(metric)
    digest_block = f'\nPROTOCOL_SOURCE_SHA256 = "{protocol_digest}"\nSENSOR_SOURCE_SHA256 = "{sensor_digest}"\n'
    metrics_block = (
        "\nMETRICS = (\n"
        + "\n".join(f"    {metric!r}," for metric in metrics)
        + "\n)\n"
    )
    runner = (ROOT / "tools" / "standalone_runner.py.in").read_text()
    source = (
        HEADER
        + digest_block
        + "\n\n"
        + "\n\n\n".join(source_parts)
        + "\n"
        + metrics_block
        + "\n"
        + runner
    )
    return subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(TARGET), "-"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed script matches its source.",
    )
    args = parser.parse_args()
    source = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != source:
            parser.exit(
                1, "Standalone script is stale; run python tools/build_standalone.py\n"
            )
    else:
        TARGET.write_text(source)


if __name__ == "__main__":
    main()
