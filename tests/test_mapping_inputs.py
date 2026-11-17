"""The definitions a conversion accepts: DBCs, the mapping config and the Excel template."""

from __future__ import annotations

import can
import pytest
from scipy.io import loadmat

from can_toolbox.blf_mat import converter as core
from can_toolbox.blf_mat import options as blf_options
from can_toolbox.blf_mat.config import ConfigError, load_config, parse_document, write_config
from can_toolbox.blf_mat.excel_template import read_template, write_template
from can_toolbox.blf_mat.options import ConversionOptions, OptionError, run_conversion

pytestmark = pytest.mark.usefixtures("blf_runtime")


def run(**fields):
    return run_conversion(ConversionOptions(**fields))


def basic(sample, **extra):
    return {"blf": str(sample["blf"]), "output_folder": str(sample["output"]), **extra}


def with_dbc(sample, **extra):
    return basic(sample, dbc=str(sample["dbc"]), **extra)


def scenario(sample, name):
    return loadmat(sample["output"] / name, simplify_cells=True)["Scenario"]


# -- logs and DBCs -------------------------------------------------------------------


def test_blf_only_exports_frames_and_defaults_output(sample):
    run(blf=str(sample["blf"]))
    content = loadmat(sample["root"] / "mat_output/sample.mat", simplify_cells=True)["Frames"]
    assert content["ID"].tolist() == [999, 256, 256]
    assert content["Time"].tolist() == [0, 0.5, 1]
    with can.BLFReader(sample["blf"]) as reader:
        expected_timestamps = [frame.timestamp for frame in reader]
    assert content["Timestamp"].tolist() == expected_timestamps
    assert content["Data"].shape == (3, 64)
    assert content["Length"].tolist() == [1, 2, 2]


def test_blf_plus_dbc_infers_messages_without_zero_insertion(sample):
    run(**with_dbc(sample))
    decoded = scenario(sample, "sample_signals.mat")
    assert decoded["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]
    assert decoded["Sample"]["SpeedCAN"]["Time"].tolist() == [0.5, 1]
    assert decoded["Sample"]["RequestCAN"]["Data"].tolist() == [2, 3]


@pytest.mark.parametrize("single_file", [False, True])
def test_dbc_source_accepts_file_or_recursive_folder(sample, single_file):
    folder = sample["dbc"]
    nested = folder / "nested"
    nested.mkdir()
    source = (folder / "sample.dbc").rename(nested / "sample.DBC")
    run(**basic(sample, dbc=str(source if single_file else folder)))
    assert scenario(sample, "sample_signals.mat")["Sample"]["SpeedCAN"]["Data"].tolist() == [10, 30]


def test_several_dbc_sources_are_merged(sample, tmp_path):
    second = tmp_path / "extra.dbc"
    second.write_text(
        'VERSION ""\nNS_ :\nBS_:\nBU_: ECU\nBO_ 999 Other: 1 ECU\n'
        ' SG_ Flag : 0|8@1+ (1,0) [0|255] "" ECU\n',
        encoding="ascii",
    )
    run(**basic(sample, dbcs=(str(sample["dbc"]), str(second))))
    decoded = scenario(sample, "sample_signals.mat")
    assert "Sample" in decoded and "Other" in decoded


def test_missing_dbc_source_is_reported(sample):
    with pytest.raises(OptionError, match="does not exist"):
        run(**basic(sample, dbc=str(sample["root"] / "nope")))


# -- the mapping config, in three syntaxes --------------------------------------------


def test_yaml_json_and_txt_describe_the_same_mapping(sample, tmp_path):
    yaml_config = load_config(sample["config"])
    results = {}
    for suffix in (".yaml", ".json", ".txt"):
        target = tmp_path / f"mapping{suffix}"
        write_config(target, yaml_config)
        reread = load_config(target)
        assert reread.interfaces == yaml_config.interfaces
        assert reread.mappings == yaml_config.mappings
        assert reread.forces == yaml_config.forces
        results[suffix] = reread
    assert results[".json"].interfaces == results[".txt"].interfaces


@pytest.mark.parametrize("suffix", [".yaml", ".json", ".txt"])
def test_every_syntax_converts_to_the_same_mat(sample, tmp_path, suffix):
    target = tmp_path / f"mapping{suffix}"
    write_config(target, load_config(sample["config"]))
    run(**with_dbc(sample, config=str(target), output_format="mat"))
    decoded = scenario(sample, "sample_input.mat")
    # CAN 10/30 -> status 20/40 -> formula /10 -> single
    assert decoded["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]
    assert decoded["BSW_CanInp"]["Enable"]["Data"].tolist() == [1, 1]
    assert scenario(sample, "sample_output.mat")["BSW_CanOut"]["Request"]["Data"].tolist() == [2, 3]


def test_legacy_config_without_a_version_still_loads(sample):
    sample["config"].write_text(
        "input_mappings:\n  - interface: Inputs\n    element: Speed\n    can_signal: SpeedCAN\n"
        "input_forces:\n  - interface: Inputs\n    element: Enable\n    value: 7\n",
        encoding="utf-8",
    )
    config = load_config(sample["config"])
    assert config.is_legacy and not config.has_interfaces
    assert config.mappings[0].can_signal == "SpeedCAN" and config.forces[0].value == 7


def test_a_legacy_config_is_upgraded_in_place(sample, tmp_path):
    sample["config"].write_text(
        "input_mappings:\n  - interface: Inputs\n    element: Speed\n    can_signal: SpeedCAN\n"
        "    formula: '*2'\n",
        encoding="utf-8",
    )
    upgraded = write_config(tmp_path / "upgraded.yaml", load_config(sample["config"]))
    config = load_config(upgraded)
    assert config.version == 2 and not config.is_legacy
    assert [bus["name"] for bus in config.interfaces["input"]] == ["Inputs"]
    assert config.mappings[0].formula == "*2"


def test_unsupported_config_suffix_is_refused(sample, tmp_path):
    other = tmp_path / "mapping.ini"
    other.write_text("[input]\n", encoding="utf-8")
    with pytest.raises(OptionError, match="must have one of these extensions"):
        run(**basic(sample, config=str(other)))


def test_txt_reports_the_line_that_is_wrong(tmp_path):
    bad = tmp_path / "mapping.txt"
    bad.write_text("[input]\nBus.Value: single\n    nonsense = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping.txt:3: unknown option"):
        load_config(bad)


def test_formulas_are_validated_when_the_config_is_read(tmp_path):
    bad = tmp_path / "mapping.yaml"
    bad.write_text(
        "version: 2\ninterfaces:\n  - name: Bus\n    side: input\n    elements:\n"
        "      - element: Value\n        dtype: single\n        can_signal: CAN\n"
        "        formula: \"__import__('os')\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Invalid signal formula"):
        load_config(bad)


def test_force_without_definitions_still_reaches_the_mat(sample):
    sample["config"].write_text(
        "input_forces:\n- {interface: Inputs, element: Enable, value: 7}\n", encoding="utf-8"
    )
    run(**basic(sample, config=str(sample["config"])))
    assert scenario(sample, "sample_input.mat")["Inputs"]["Enable"]["Data"].tolist() == [7, 7]
    assert (sample["output"] / "sample.mat").is_file()


def test_default_config_beside_the_application_is_loaded(sample, monkeypatch):
    sample["config"].write_text(
        "input_forces:\n- {interface: Inputs, element: Enable, value: 5}\n", encoding="utf-8"
    )
    monkeypatch.setattr(blf_options, "application_directory", lambda: sample["root"])
    sample["config"].rename(sample["root"] / "signal_mapping.yaml")
    run(**basic(sample))
    assert scenario(sample, "sample_input.mat")["Inputs"]["Enable"]["Data"].tolist() == [5, 5]


# -- the Excel template ---------------------------------------------------------------


def test_template_round_trip(tmp_path):
    path = write_template(tmp_path / "template.xlsx")
    document = read_template(path)
    config = parse_document(document, source=path)
    assert [bus["name"] for bus in config.interfaces["input"]] == ["VehicleInputs"]
    assert [bus["name"] for bus in config.interfaces["output"]] == ["VehicleOutputs"]
    assert config.mappings[0].can_signal == "VehicleSpeedCAN"
    assert config.mappings[0].formula == "/10"


def test_template_drives_a_conversion(sample, tmp_path):
    from tests.workbooks import table, write_workbook

    excel = write_workbook(tmp_path / "filled.xlsx", {
        "Inputs": table({
            "Interface": ["BSW_CanInp"], "Data Element": ["Speed"], "CAN Signal": ["SpeedCAN"],
            "Datatype": ["single"], "Formula": ["/10"], "Status Mapping": ["10:20, 30:40"],
            "Enabled": ["TRUE"],
        }),
        "Outputs": table({
            "Interface": ["BSW_CanOut"], "Data Element": ["Request"], "CAN Signal": ["RequestCAN"],
            "Datatype": ["uint8"], "Formula": [""], "Status Mapping": [""], "Enabled": ["TRUE"],
        }),
    })
    run(**with_dbc(sample, excel=str(excel), config="", output_format="mat"))
    assert scenario(sample, "sample_input.mat")["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]
    assert scenario(sample, "sample_output.mat")["BSW_CanOut"]["Request"]["Data"].tolist() == [2, 3]


def test_disabled_rows_and_skip_keywords_drop_elements(sample, tmp_path):
    from tests.workbooks import table, write_workbook

    excel = write_workbook(tmp_path / "filtered.xlsx", {
        "Inputs": table({
            "Interface": ["Bus", "Bus", "Bus"],
            "Data Element": ["Kept", "Disabled", "Obsolete"],
            "CAN Signal": ["SpeedCAN", "SpeedCAN", "SpeedCAN"],
            "Datatype": ["single", "single", "single"],
            "Formula": ["", "", ""],
            "Status Mapping": ["", "", ""],
            "Enabled": ["TRUE", "FALSE", "TRUE"],
        }),
    })
    config = tmp_path / "skip.yaml"
    config.write_text("version: 2\nexcel_skip_keywords: ['obsolete']\n", encoding="utf-8")
    run(**with_dbc(sample, excel=str(excel), config=str(config), output_format="mat"))
    inputs = scenario(sample, "sample_input.mat")["Bus"]
    assert set(inputs) == {"Kept"}


def test_a_workbook_without_the_fixed_columns_is_refused(sample, tmp_path):
    from tests.workbooks import table, write_workbook

    excel = write_workbook(tmp_path / "free.xlsx", {
        "Inputs": table({"Group": ["Bus"], "Wire label": ["SpeedCAN"], "Target name": ["Speed"]}),
    })
    with pytest.raises(ConfigError, match="must be Interface, Data Element"):
        run(**with_dbc(sample, excel=str(excel), config=""))


def test_a_workbook_without_template_sheets_is_refused(sample, tmp_path):
    from tests.workbooks import table, write_workbook

    excel = write_workbook(tmp_path / "other.xlsx", {"Sheet1": table({"Interface": ["Bus"]})})
    with pytest.raises(ConfigError, match="needs an 'Inputs' or an 'Outputs' sheet"):
        run(**with_dbc(sample, excel=str(excel), config=""))


def test_the_config_wins_over_the_template(sample, tmp_path):
    from tests.workbooks import table, write_workbook

    excel = write_workbook(tmp_path / "both.xlsx", {
        "Inputs": table({
            "Interface": ["BSW_CanInp"], "Data Element": ["Speed"], "CAN Signal": ["RequestCAN"],
            "Datatype": ["single"], "Formula": [""], "Status Mapping": [""], "Enabled": ["TRUE"],
        }),
    })
    run(**with_dbc(sample, excel=str(excel), config=str(sample["config"]), output_format="mat"))
    # The config keeps SpeedCAN with its status mapping and formula.
    assert scenario(sample, "sample_input.mat")["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]


# -- MATLAB -----------------------------------------------------------------------------


def test_dataset_single_side_and_missing_matlab(sample, monkeypatch):
    captured = []

    def package(executable, script, cwd):
        captured.append(script.read_text())
        (sample["output"] / "sample_signals.mat").touch()

    monkeypatch.setattr(core, "run_matlab_batch", package)
    run(**with_dbc(sample, output_format="dataset", matlab=__file__))
    assert "if isempty(jobs{k,side}), continue; end" in captured[0]

    def missing(*args):
        raise OptionError("MATLAB unavailable")

    monkeypatch.setattr(blf_options, "find_matlab_executable", missing)
    with pytest.raises(OptionError, match="MATLAB unavailable"):
        run(**with_dbc(sample, output_format="dataset"))


def test_dataset_without_definitions_is_refused(sample, monkeypatch):
    monkeypatch.setattr(core, "run_matlab_batch", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="Dataset export needs signal definitions"):
        run(**basic(sample, output_format="dataset", matlab=__file__))


def test_mapped_standard_mat_does_not_launch_matlab(sample, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("MATLAB should not run")

    monkeypatch.setattr(core, "run_matlab_batch", forbidden)
    run(**{**sample["options"], "output_format": "mat"})
    assert scenario(sample, "sample_input.mat")["BSW_CanInp"]["Speed"]["Data"].tolist() == [0, 2, 4]


def test_txt_keeps_excel_skip_keywords(tmp_path):
    """A TXT round trip that dropped the filter would quietly re-add skipped rows."""
    source = tmp_path / "mapping.yaml"
    source.write_text(
        "version: 2\nexcel_skip_keywords: [obsolete, draft]\n"
        "interfaces:\n  - name: Bus\n    side: input\n    elements:\n"
        "      - element: Speed\n        dtype: single\n        can_signal: SpeedCAN\n",
        encoding="utf-8",
    )
    written = write_config(tmp_path / "mapping.txt", load_config(source))
    reread = load_config(written)
    assert reread.excel_skip_keywords == ("obsolete", "draft")
    assert [bus["name"] for bus in reread.interfaces["input"]] == ["Bus"]


def test_options_section_rejects_other_keys(tmp_path):
    bad = tmp_path / "mapping.txt"
    bad.write_text("[options]\n    nonsense = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"unknown option 'nonsense' in \[options\]"):
        load_config(bad)
