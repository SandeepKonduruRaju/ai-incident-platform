import json

from app.synthetic import EVIDENCE_TYPES, SCENARIOS, TENANTS, generate, main


def test_same_seed_gives_identical_files(tmp_path):
    main(["--seed", "42", "--out", str(tmp_path / "a")])
    main(["--seed", "42", "--out", str(tmp_path / "b")])

    for name in (*EVIDENCE_TYPES, "golden"):
        assert (tmp_path / "a" / f"{name}.json").read_bytes() == (tmp_path / "b" / f"{name}.json").read_bytes()


def test_different_seed_gives_different_data():
    assert generate(1)["logs"] != generate(2)["logs"]


def test_both_tenants_present_in_every_type():
    dataset = generate()
    for kind in EVIDENCE_TYPES:
        assert {item["tenant_id"] for item in dataset[kind]} == set(TENANTS), kind


def test_every_scenario_has_all_four_evidence_types_per_tenant():
    golden = generate()["golden"]
    assert set(golden) == set(SCENARIOS)
    for scenario in SCENARIOS:
        for tenant in TENANTS:
            for kind in EVIDENCE_TYPES:
                assert golden[scenario][tenant][kind], f"{scenario}/{tenant} has no {kind}"


def test_golden_ids_exist_and_belong_to_their_tenant():
    dataset = generate()
    by_id = {item["source_id"]: item for kind in EVIDENCE_TYPES for item in dataset[kind]}
    for _scenario, tenants in dataset["golden"].items():
        for tenant, kinds in tenants.items():
            for kind, ids in kinds.items():
                for source_id in ids:
                    assert source_id in by_id, source_id
                    assert by_id[source_id]["tenant_id"] == tenant
                    assert by_id[source_id]["source_type"] == kind.removesuffix("s")  # "runbooks" -> "runbook"


def test_source_ids_are_unique():
    dataset = generate()
    ids = [item["source_id"] for kind in EVIDENCE_TYPES for item in dataset[kind]]
    assert len(ids) == len(set(ids))


def test_signal_logs_are_errors_or_warnings_and_noise_exists():
    dataset = generate()
    golden_logs = {i for tenants in dataset["golden"].values() for kinds in tenants.values() for i in kinds["logs"]}
    signal = [log for log in dataset["logs"] if log["source_id"] in golden_logs]
    noise = [log for log in dataset["logs"] if log["source_id"] not in golden_logs]
    assert {log["level"] for log in signal} <= {"ERROR", "WARN"}
    assert len(noise) > len(signal)
    assert {"INFO", "WARN"} <= {log["level"] for log in noise}


def test_tenants_differ_in_details():
    dataset = generate()
    runbooks = {item["source_id"]: item for item in dataset["runbooks"]}
    for scenario in SCENARIOS:
        assert runbooks[f"RB-acme-{scenario}"]["content"] != runbooks[f"RB-globex-{scenario}"]["content"]


def test_runbooks_are_markdown_with_sections():
    for runbook in generate()["runbooks"]:
        assert runbook["content"].startswith("# ")
        assert runbook["content"].count("\n## ") >= 2


def test_output_is_valid_json(tmp_path):
    main(["--out", str(tmp_path)])
    golden = json.loads((tmp_path / "golden.json").read_text(encoding="utf-8"))
    assert golden["db_pool_exhausted"]["acme"]["runbooks"] == ["RB-acme-db_pool_exhausted"]
