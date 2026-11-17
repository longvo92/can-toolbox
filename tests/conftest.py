"""Fixtures for the BLF -> MAT engine tests (synthesized DBC, Excel template, config, BLF)."""

from __future__ import annotations

from pathlib import Path

import pytest

_CONFIG_YAML = """version: 2
interfaces:
  - name: BSW_CanInp
    side: input
    elements:
      - element: Speed
        dtype: single
        can_signal: SpeedCAN
        formula: "/10"
        status_mapping: {10: 20, 30: 40}
      - element: Enable
        dtype: boolean
        value: true
  - name: BSW_CanOut
    side: output
    elements:
      - element: Request
        dtype: uint8
        can_signal: RequestCAN
"""


@pytest.fixture
def blf_runtime():
    """Load the converter's lazily imported numeric packages."""
    from can_toolbox.blf_mat import converter

    converter.load_runtime_dependencies()
    return converter


@pytest.fixture
def sample(tmp_path: Path, blf_runtime) -> dict[str, object]:
    import can

    from can_toolbox.blf_mat.excel_template import write_template

    dbc = tmp_path / "dbc"
    dbc.mkdir()
    (dbc / "sample.dbc").write_text(
        'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\n'
        "BO_ 256 Sample: 2 ECU\n"
        ' SG_ SpeedCAN : 0|8@1+ (1,0) [0|255] "" ECU\n'
        ' SG_ RequestCAN : 8|8@1+ (1,0) [0|255] "" ECU\n',
        encoding="ascii",
    )
    config = tmp_path / "mapping.yaml"
    config.write_text(_CONFIG_YAML, encoding="utf-8")
    excel = write_template(tmp_path / "template.xlsx")
    blf = tmp_path / "sample.blf"
    with can.BLFWriter(blf) as writer:
        writer.on_message_received(can.Message(timestamp=100.0, arbitration_id=999, is_extended_id=False, data=[0]))
        writer.on_message_received(
            can.Message(timestamp=100.5, arbitration_id=256, is_extended_id=False, data=[10, 2])
        )
        writer.on_message_received(
            can.Message(timestamp=101.0, arbitration_id=256, is_extended_id=False, data=[30, 3])
        )
    output = tmp_path / "output"
    # Every input the Export window offers, in Dataset format; MATLAB itself is mocked.
    options = {
        "dbc": str(dbc),
        "blf": str(blf),
        "output_folder": str(output),
        "config": str(config),
        "matlab": __file__,
        "output_format": "dataset",
    }
    return {
        "root": tmp_path,
        "blf": blf,
        "dbc": dbc,
        "output": output,
        "options": options,
        "config": config,
        "excel": excel,
    }
