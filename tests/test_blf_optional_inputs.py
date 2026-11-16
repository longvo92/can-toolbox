from __future__ import annotations

import can
import pytest
from scipy.io import loadmat

from can_toolbox.blf_mat import converter as core
from can_toolbox.blf_mat import mapping
from can_toolbox.blf_mat import options as blf_options
from can_toolbox.blf_mat.options import ConversionOptions, OptionError, run_conversion
from tests.workbooks import table, write_workbook

pytestmark = pytest.mark.usefixtures("blf_runtime")


def run(**fields):
    return run_conversion(ConversionOptions(**fields))


def basic(sample, **extra):
    return {"blf": str(sample["blf"]), "output_folder": str(sample["output"]), **extra}


def with_dbc(sample, **extra):
    return basic(sample, dbc=str(sample["root"] / "dbc"), **extra)


def test_blf_only_exports_frames_and_defaults_output(sample):
    run(blf=str(sample["blf"]))
    content = loadmat(sample["root"] / "mat_output/sample.mat", simplify_cells=True)["Frames"]
    assert content["ID"].tolist() == [999, 256, 256]
    assert content["Time"].tolist() == [0, 0.5, 1]
    with can.BLFReader(sample["blf"]) as reader:
        expected_timestamps = [frame.timestamp for frame in reader]
    assert content["Timestamp"].tolist() == expected_timestamps
    assert content["Data"].shape == (3, 64)
    assert content["Data"][1, :2].tolist() == [10, 2]
    assert content["Length"].tolist() == [1, 2, 2]


def test_blf_plus_dbc_infers_messages_without_zero_insertion(sample):
    run(**with_dbc(sample))
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]
    assert scenario["Sample"]["SpeedCAN"]["Time"].tolist() == [0.5, 1]
    assert scenario["Sample"]["RequestCAN"]["Data"].tolist() == [2, 3]


@pytest.mark.parametrize("single_file", [False, True])
def test_dbc_source_accepts_file_or_recursive_folder(sample, single_file):
    folder = sample["root"] / "dbc"
    source = folder / "sample.dbc"
    nested = folder / "nested"
    nested.mkdir()
    source = source.rename(nested / "sample.DBC")
    run(**basic(sample, dbc=str(source if single_file else folder)))
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]


def test_single_dbc_does_not_load_neighboring_files(sample):
    folder = sample["root"] / "dbc"
    source = folder / "sample.dbc"
    (folder / "other.dbc").write_text(
        source.read_text()
        .replace("Sample:", "Other:")
        .replace("SpeedCAN", "OtherSpeed")
        .replace("RequestCAN", "OtherRequest")
    )
    run(**basic(sample, dbc=str(source)))
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert list(scenario) == ["Sample"]


@pytest.mark.parametrize("name", ["missing.dbc", "schema.txt"])
def test_invalid_dbc_source_is_rejected(sample, name):
    with pytest.raises(OptionError, match="DBC file or folder"):
        run(**basic(sample, dbc=str(sample["root"] / name)))


def test_schema_without_excel_maps_element_names(sample):
    sample["schema"].write_text("Vehicle.SpeedCAN : single\n", encoding="utf-8")
    run(**with_dbc(sample, schema=(str(sample["schema"]),)))
    signal = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"][
        "Vehicle"
    ]["SpeedCAN"]
    assert signal["Data"].dtype.name == "float32"
    assert signal["Data"].tolist() == [0, 10, 30]


@pytest.mark.parametrize("dbc", [False, True])
def test_txt_workflow_without_workbook_or_matlab(sample, monkeypatch, dbc):
    (sample["root"] / "interfaces.xlsx").unlink()
    sample["schema"].write_text("Vehicle.SpeedCAN : single\n", encoding="utf-8")
    second = sample["root"] / "outputs.txt"
    second.write_text("ControllerOutputs.RequestCAN : uint8\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("TXT workflow must not read Excel or launch MATLAB")

    monkeypatch.setattr(mapping, "Workbook", forbidden)
    monkeypatch.setattr(core, "run_matlab_batch", forbidden)
    fields = with_dbc(sample) if dbc else basic(sample)
    run(**fields, schema=(str(sample["schema"]), str(second)))
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert set(scenario) == {"Vehicle"}
    speed = scenario["Vehicle"]["SpeedCAN"]
    assert speed["Data"].dtype.name == "float32"
    assert speed["Data"].tolist() == ([0, 10, 30] if dbc else [0, 0])
    output = loadmat(sample["output"] / "sample_output.mat", simplify_cells=True)["Scenario"]
    assert set(output) == {"ControllerOutputs"}
    assert output["ControllerOutputs"]["RequestCAN"]["Data"].tolist() == (
        [2, 3] if dbc else [0, 0]
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_txt_sides_keep_shared_bus_elements_separate(sample, legacy):
    sample["schema"].write_text("Shared.SpeedCAN : single\n")
    output_schema = sample["root"] / "second.txt"
    output_schema.write_text("Shared.RequestCAN : uint8\n")
    fields = (
        {"schema": (str(sample["schema"]), str(output_schema))}
        if legacy
        else {"input_schema": str(sample["schema"]), "output_schema": str(output_schema)}
    )
    run(**with_dbc(sample, **fields))
    inputs = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    outputs = loadmat(sample["output"] / "sample_output.mat", simplify_cells=True)["Scenario"]
    assert set(inputs["Shared"]) == {"SpeedCAN"}
    assert set(outputs["Shared"]) == {"RequestCAN"}
    assert inputs["Shared"]["SpeedCAN"]["Data"].tolist() == [0, 10, 30]
    assert outputs["Shared"]["RequestCAN"]["Data"].tolist() == [2, 3]


def test_same_txt_target_can_have_independent_side_datatypes(sample):
    sample["schema"].write_text("Shared.SpeedCAN : single\n")
    output_schema = sample["root"] / "second.txt"
    output_schema.write_text("Shared.SpeedCAN : uint8\n")
    run(**with_dbc(sample, input_schema=str(sample["schema"]), output_schema=str(output_schema)))
    inputs = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    outputs = loadmat(sample["output"] / "sample_output.mat", simplify_cells=True)["Scenario"]
    assert inputs["Shared"]["SpeedCAN"]["Data"].dtype.name == "float32"
    assert outputs["Shared"]["SpeedCAN"]["Data"].dtype.name == "uint8"


def test_txt_output_only(sample):
    sample["schema"].write_text("Vehicle.SpeedCAN : single\n")
    run(**with_dbc(sample, output_schema=str(sample["schema"])))
    assert not (sample["output"] / "sample_input.mat").exists()
    output = loadmat(sample["output"] / "sample_output.mat", simplify_cells=True)["Scenario"]
    assert output["Vehicle"]["SpeedCAN"]["Data"].tolist() == [10, 30]


def test_txt_sides_keep_yaml_input_mappings_and_forces(sample):
    sample["schema"].write_text("Shared.Speed : single\nShared.Enable : boolean\n")
    output_schema = sample["root"] / "output.txt"
    output_schema.write_text("Shared.RequestCAN : uint8\n")
    sample["config"].write_text(
        "input_mappings:\n- {interface: Shared, element: Speed, can_signal: SpeedCAN}\n"
        "input_forces:\n- {interface: Shared, element: Enable, value: true}\n"
    )
    run(
        **with_dbc(
            sample,
            input_schema=str(sample["schema"]),
            output_schema=str(output_schema),
            config=str(sample["config"]),
        )
    )
    inputs = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert inputs["Shared"]["Speed"]["Data"].tolist() == [0, 10, 30]
    assert inputs["Shared"]["Enable"]["Data"].tolist() == [1, 1]
    assert set(inputs["Shared"]) == {"Speed", "Enable"}


def test_explicit_txt_sides_with_excel(sample):
    sample["schema"].write_text("Shared.Speed : single\n")
    output_schema = sample["root"] / "output.txt"
    output_schema.write_text("Shared.Speed : uint8\n")
    excel = write_workbook(sample["root"] / "sides.xlsx", {
        sheet: table({"Interface": ["Shared"], "Data Element": ["Speed"], "CAN Signal": [source]})
        for sheet, source in (("SWC_INF", "SpeedCAN"), ("SWC_OUTF", "RequestCAN"))
    })
    run(
        **with_dbc(
            sample, excel=str(excel), input_schema=str(sample["schema"]), output_schema=str(output_schema)
        )
    )
    inputs = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    outputs = loadmat(sample["output"] / "sample_output.mat", simplify_cells=True)["Scenario"]
    assert inputs["Shared"]["Speed"]["Data"].tolist() == [0, 10, 30]
    assert outputs["Shared"]["Speed"]["Data"].tolist() == [2, 3]
    assert outputs["Shared"]["Speed"]["Data"].dtype.name == "uint8"


def test_txt_dataset_packaging_receives_separate_scenarios(sample, monkeypatch):
    sample["schema"].write_text("Shared.SpeedCAN : single\n")
    output_schema = sample["root"] / "output.txt"
    output_schema.write_text("Shared.RequestCAN : uint8\n")
    captured = []

    def package(executable, script, cwd):
        raw = loadmat(next(cwd.glob("raw_*.mat")), simplify_cells=True)
        captured.append(raw)
        for side in ("input", "output"):
            (sample["output"] / f"sample_{side}.mat").touch()

    monkeypatch.setattr(core, "run_matlab_batch", package)
    run(
        **with_dbc(
            sample,
            schema=(str(sample["schema"]), str(output_schema)),
            output_format="dataset",
            matlab=__file__,
        )
    )
    assert len(captured) == 1
    assert set(captured[0]["RawInputScenario"]["Shared"]) == {"SpeedCAN"}
    assert set(captured[0]["RawOutputScenario"]["Shared"]) == {"RequestCAN"}


@pytest.mark.parametrize("mixed", [False, True])
def test_ambiguous_txt_options_rejected(sample, mixed):
    schema = str(sample["schema"])
    fields = {"schema": (schema,), "input_schema": schema} if mixed else {"schema": (schema,) * 3}
    with pytest.raises(OptionError):
        run(**basic(sample, **fields))


def test_force_without_excel_schema_or_dbc(sample):
    sample["config"].write_text(
        "input_forces:\n- {interface: Inputs, element: Enable, value: 7}\n", encoding="utf-8"
    )
    run(**basic(sample, config=str(sample["config"])))
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert scenario["Inputs"]["Enable"]["Data"].tolist() == [7, 7]
    assert (sample["output"] / "sample.mat").is_file()


def custom_excel(sample, rows=None):
    rows = rows or [
        ["Group", "Wire label", "Target name", "Storage"],
        ["Vehicle", "SpeedCAN", "Speed", "single"],
    ]
    return write_workbook(
        sample["root"] / "custom.xlsx",
        {"Notes": [["Notes only"]], "Any Project": rows},
        start_rows={"Any Project": 3},
    )


@pytest.mark.parametrize(
    "columns", [["Target name", "Wire label", "Group", "Storage"], ["3", "2", "1", "4"]]
)
def test_custom_sheets_headers_and_columns_without_schema(sample, columns):
    excel = custom_excel(sample)
    fields = with_dbc(sample, excel=str(excel), input_sheets=("Any Project",), header_row=4)
    for name, value in zip(("element", "can", "interface", "dtype"), columns):
        fields[f"{name}_column"] = value
    run(**fields)
    signal = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"][
        "Vehicle"
    ]["Speed"]
    assert signal["Data"].dtype.name == "float32"
    assert signal["Data"].tolist() == [0, 10, 30]


def test_auto_detect_generic_sheets_skips_notes(sample):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element", "Type"], ["Vehicle", "SpeedCAN", "Speed", "single"]],
    )
    run(**with_dbc(sample, excel=str(excel)))
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert "Vehicle" in scenario
    assert not (sample["output"] / "sample_output.mat").exists()


def test_output_only_sheet_and_unknown_sheet_errors(sample):
    excel = custom_excel(
        sample,
        [["Interface", "CAN Signal", "Data Element"], ["Controller", "RequestCAN", "Request"]],
    )
    run(**with_dbc(sample, excel=str(excel), output_sheets=("Any Project",)))
    assert (sample["output"] / "sample_output.mat").is_file()
    assert not (sample["output"] / "sample_input.mat").exists()
    with pytest.raises(RuntimeError, match="Sheet 'Missing' was not found"):
        run(**with_dbc(sample, excel=str(excel), input_sheets=("Missing",)))


def test_multiple_input_sheets(sample):
    excel = write_workbook(sample["root"] / "multi.xlsx", {
        sheet: table({"Bus": [bus], "CAN Signal": [source]})
        for sheet, bus, source in (("A", "Vehicle", "SpeedCAN"), ("B", "Controller", "RequestCAN"))
    })
    run(**with_dbc(sample, excel=str(excel), input_sheets=("A", "B")))
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert list(scenario) == ["Vehicle", "Controller"]


@pytest.mark.parametrize("explicit", [False, True])
def test_excel_keywords_filter_all_cells_on_both_sides(sample, explicit, capsys):
    rows = [
        ["Interface", "Data Element", "CAN Signal", "Type", "Notes"],
        ["Vehicle", "Speed", "SpeedCAN", "single", ""],
        ["", "Speed", "RequestCAN", "single", "Marked OBSOLETE today"],
        ["", "Ignored", "SpeedCAN", "invalid", "literal [skip] marker"],
        ["", "Kept", "RequestCAN", "uint8", "skipping is not a literal marker"],
        ["", "ObsoleteTarget", "SpeedCAN", "single", ""],
        ["", "BadSource", "ObsoleteCAN", "single", ""],
        ["ObsoleteBus", "BadBus", "SpeedCAN", "single", ""],
        ["Other", "BadType", "SpeedCAN", "obsolete_type", ""],
        ["", "Inherited", "RequestCAN", "uint8", ""],
    ]
    excel = write_workbook(sample["root"] / "filtered.xlsx", {"SWC_INF": rows, "SWC_OUTF": rows})
    sample["config"].write_text('excel_skip_keywords: [" ObSoLeTe ", "[skip]"]\n')
    fields = with_dbc(sample, excel=str(excel), config=str(sample["config"]))
    if explicit:
        fields.update(input_sheets=("SWC_INF",), output_sheets=("SWC_OUTF",), header_row=1)
    run(**fields)
    for side in ("input", "output"):
        scenario = loadmat(sample["output"] / f"sample_{side}.mat", simplify_cells=True)["Scenario"]
        assert set(scenario) == {"Vehicle", "Other"}
        assert set(scenario["Vehicle"]) == {"Speed", "Kept"}
        assert scenario["Vehicle"]["Speed"]["Data"].tolist() == (
            [0, 10, 30] if side == "input" else [10, 30]
        )
        # Blank interface cells keep the workbook's group even after an excluded row.
        assert set(scenario["Other"]) == {"Inherited"}
    assert capsys.readouterr().out.count("skipped 6 row(s) matching excel_skip_keywords") == 2


@pytest.mark.parametrize("setting", ["{}", "excel_skip_keywords: []"])
def test_excel_keywords_disabled_by_default(sample, setting):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element"], ["Vehicle", "SpeedCAN", "ObsoleteSpeed"]],
    )
    sample["config"].write_text(setting)
    run(**with_dbc(sample, excel=str(excel), config=str(sample["config"])))
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert "ObsoleteSpeed" in scenario["Vehicle"]


def test_excel_keywords_all_rows_excluded_fail_clearly(sample):
    excel = custom_excel(
        sample,
        [["Bus", "CAN Signal", "Data Element"], ["Vehicle", "SpeedCAN", "ObsoleteSpeed"]],
    )
    sample["config"].write_text("excel_skip_keywords: [obsolete]\n")
    with pytest.raises(RuntimeError, match="No mapping rows were resolved"):
        run(**with_dbc(sample, excel=str(excel), config=str(sample["config"])))
    assert not list(sample["output"].glob("*.mat"))


@pytest.mark.parametrize("value", ['"obsolete"', "null", "[1]", "[true]", '[""]', '["  "]', "{}"])
def test_invalid_excel_keywords_config_rejected(sample, value):
    sample["config"].write_text(f"excel_skip_keywords: {value}\n")
    with pytest.raises(RuntimeError, match="'excel_skip_keywords' must"):
        run(**basic(sample, config=str(sample["config"])))
    assert not list(sample["output"].glob("*.mat"))


def test_same_signal_name_from_different_messages_is_independent(sample):
    dbc = sample["root"] / "dbc/sample.dbc"
    with dbc.open("a") as stream:
        stream.write('BO_ 257 Second: 1 ECU\n SG_ SpeedCAN : 0|8@1+ (1,0) [0|255] "" ECU\n')
    with can.BLFWriter(sample["blf"]) as writer:
        writer.on_message_received(
            can.Message(timestamp=1, arbitration_id=256, is_extended_id=False, data=[10, 2])
        )
        writer.on_message_received(
            can.Message(timestamp=2, arbitration_id=257, is_extended_id=False, data=[99])
        )
    run(**with_dbc(sample))
    scenario = loadmat(sample["output"] / "sample_signals.mat", simplify_cells=True)["Scenario"]
    assert scenario["Sample"]["SpeedCAN"]["Data"] == 10
    assert scenario["Second"]["SpeedCAN"]["Data"] == 99


def test_missing_dbc_preserves_fd_and_extended_frame_metadata(sample):
    with can.BLFWriter(sample["blf"]) as writer:
        writer.on_message_received(
            can.Message(
                timestamp=1,
                arbitration_id=0x123456,
                is_extended_id=True,
                is_fd=True,
                bitrate_switch=True,
                data=list(range(64)),
            )
        )
    run(**basic(sample))
    frame = loadmat(sample["output"] / "sample.mat", simplify_cells=True)["Frames"]
    assert frame["Extended"] == 1 and frame["FD"] == 1 and frame["BRS"] == 1
    assert frame["Length"] == 64
    assert frame["Data"].tolist() == list(range(64))


def test_dataset_single_side_and_missing_matlab(sample, monkeypatch):
    captured = []

    def package(executable, script, cwd):
        captured.append(script.read_text())
        (sample["output"] / "sample_signals.mat").touch()

    monkeypatch.setattr(core, "run_matlab_batch", package)
    run(**with_dbc(sample, output_format="dataset", matlab=__file__))
    assert "if isempty(jobs{k,side}), continue; end" in captured[0]
    assert ", '';" in captured[0]

    def missing(*args):
        raise OptionError("MATLAB unavailable")

    monkeypatch.setattr(blf_options, "find_matlab_executable", missing)
    with pytest.raises(OptionError, match="MATLAB unavailable"):
        run(**with_dbc(sample, output_format="dataset"))


def test_mapped_standard_mat_does_not_launch_matlab(sample, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("MATLAB should not run")

    monkeypatch.setattr(core, "run_matlab_batch", forbidden)
    run(**{**sample["options"], "output_format": "mat"})
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert scenario["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]


@pytest.mark.parametrize("extra", [{"header_row": 0}, {"can_column": "2"}, {"input_sheets": ("A",)}])
def test_excel_options_need_workbook(sample, extra):
    with pytest.raises(OptionError, match="need an Excel workbook"):
        run(**basic(sample, **extra))


def test_header_row_must_be_positive(sample):
    with pytest.raises(OptionError, match="at least 1"):
        run(**basic(sample, excel=str(sample["root"] / "interfaces.xlsx"), header_row=0))


def test_default_config_beside_the_application_is_loaded(sample, monkeypatch):
    sample["config"].write_text("input_forces:\n- {interface: Inputs, element: Enable, value: 5}\n")
    monkeypatch.setattr(blf_options, "application_directory", lambda: sample["root"])
    sample["config"].rename(sample["root"] / "signal_mapping.yaml")
    paths = run(**basic(sample))
    assert paths.mapping_config == sample["root"] / "signal_mapping.yaml"
    scenario = loadmat(sample["output"] / "sample_input.mat", simplify_cells=True)["Scenario"]
    assert scenario["Inputs"]["Enable"]["Data"].tolist() == [5, 5]


def test_missing_blf_is_an_option_error(sample):
    with pytest.raises(OptionError, match="Select a BLF"):
        run(blf="")
    with pytest.raises(OptionError, match="No .blf files"):
        run(blf=str(sample["root"] / "dbc"))


def test_workbook_grid_matches_the_former_pandas_reader(tmp_path):
    from openpyxl import Workbook as OpenpyxlWorkbook

    path = tmp_path / "grid.xlsx"
    book = OpenpyxlWorkbook()
    sheet = book.active
    sheet.title = "Map"
    sheet["B3"], sheet["C3"], sheet["D3"] = "Interface", "CAN Signal", "Type"
    sheet["B4"], sheet["C4"], sheet["D4"] = "NA", " N/A ", 2.0
    sheet["C5"], sheet["F5"] = 2.5, "far"
    sheet["C6"] = "=1+1"  # no cached value: read as blank
    sheet.merge_cells("B7:C7")
    sheet["B7"] = "merged"
    book.create_sheet("Empty")
    book.save(path)
    with mapping.Workbook(path) as workbook:
        assert workbook.sheet_names == ["Map", "Empty"]
        assert workbook.grid("Empty") == []
        grid = workbook.grid("Map")
    assert len(grid) == 7 and {len(row) for row in grid} == {6}
    assert grid[0] == [None] * 6
    assert grid[2][1:4] == ["Interface", "CAN Signal", "Type"]
    # Exact NA texts become blank, padded ones are kept; integral floats become int.
    assert grid[3][1:4] == [None, " N/A ", 2]
    assert isinstance(grid[3][3], int)
    assert grid[4][2:] == [2.5, None, None, "far"]
    assert grid[5][2] is None
    assert grid[6][1:3] == ["merged", None]
