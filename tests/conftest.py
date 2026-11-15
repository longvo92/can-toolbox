"""Fixtures for the BLF -> MAT engine tests (synthesized DBC, Excel, TXT, YAML and BLF)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def blf_runtime():
    """Load the converter's lazily imported numeric packages."""
    from can_toolbox.blf_mat import converter

    converter.load_runtime_dependencies()
    return converter


@pytest.fixture
def sample(tmp_path: Path, blf_runtime) -> dict[str, object]:
    import can
    import pandas as pd

    dbc = tmp_path / "dbc"
    dbc.mkdir()
    (dbc / "sample.dbc").write_text(
        'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\n'
        "BO_ 256 Sample: 2 ECU\n"
        ' SG_ SpeedCAN : 0|8@1+ (1,0) [0|255] "" ECU\n'
        ' SG_ RequestCAN : 8|8@1+ (1,0) [0|255] "" ECU\n',
        encoding="ascii",
    )
    excel = tmp_path / "interfaces.xlsx"
    with pd.ExcelWriter(excel, engine="openpyxl") as writer:
        pd.DataFrame(
            {"Interface": ["BSW_CanInp"], "Data Element": ["Speed"], "CAN Signal": ["SpeedCAN"]}
        ).to_excel(writer, sheet_name="SWC_INF", index=False)
        pd.DataFrame(
            {"Interface": ["BSW_CanOut"], "Data Element": ["Request"], "CAN Signal": ["RequestCAN"]}
        ).to_excel(writer, sheet_name="SWC_OUTF", index=False)
    schema = tmp_path / "schema.txt"
    schema.write_text(
        "BSW_CanInp.Speed : single\nBSW_CanInp.Enable : boolean\nBSW_CanOut.Request : uint8\n",
        encoding="utf-8",
    )
    config = tmp_path / "mapping.yaml"
    config.write_text(
        "input_mappings:\n  - interface: BSW_CanInp\n    element: Speed\n    can_signal: SpeedCAN\n"
        "    status_mapping: {10: 20, 30: 40}\n    formula: /10\n"
        "input_forces:\n  - interface: BSW_CanInp\n    element: Enable\n    value: true\n",
        encoding="utf-8",
    )
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
    # Every input the GUI offers, in Dataset format; MATLAB itself is mocked by the tests.
    options = {
        "excel": str(excel),
        "dbc": str(dbc),
        "schema": (str(schema),),
        "blf": str(blf),
        "output_folder": str(output),
        "config": str(config),
        "matlab": __file__,
        "output_format": "dataset",
    }
    return {
        "root": tmp_path,
        "blf": blf,
        "output": output,
        "options": options,
        "schema": schema,
        "config": config,
    }
