"""Explicit build inputs authorize aliases; runtime only consumes saved evidence."""
import copy
import importlib

import pytest

from arm_kb_search import SearchResources, search
from arm_kb_search.names import NameIndex


def row(i, label, **values):
    return dict(chunk_uuid=str(i), doc_type="Ecosystem Dashboard", title=label,
                heading_path=["Catalog", label], original_text=label,
                search_text=label, url=f"https://example.org/{i}", **values)


def group(canonical="Maple Studio Editor", aliases=None, labels=None):
    return dict(canonical=canonical, aliases=aliases or ["MSE"],
                labels=labels or ["Maple Studio Editor (MSE)"],
                provenance="Explicit test catalog label")


def test_parenthetical_label_does_not_automatically_authorize_alias():
    index = NameIndex([row(0, "Maple Studio Editor (MSE)")])
    assert index.keys("mse maple_studio_editor") == frozenset()


def test_explicit_groups_build_against_original_unchanged_metadata(tmp_path):
    rows = [row(0, "Maple Studio Editor (MSE)"), row(1, "Other Editor")]
    original = copy.deepcopy(rows)
    artifact = tmp_path / "names.json"
    NameIndex.precompute(rows, artifact, aliases=[group()])
    index = NameIndex.load_precomputed(rows, artifact)
    assert rows == original
    for spelling in ["MSE", "mse", "maple_studio-editor", "Maple Studio Editor (MSE)"]:
        assert index.candidates(spelling) == [0]
    source = index.inventory["maplestudioeditor"].sources[0]
    assert source["label"] == "Maple Studio Editor (MSE)"
    assert source["chunk_uuid"] == "0"
    assert source["provenance"] == "Explicit test catalog label"


def test_startup_and_repeated_queries_never_call_offline_builder(tmp_path, monkeypatch):
    s = importlib.import_module("arm_kb_search.search")
    rows = [row(0, "Maple Studio Editor (MSE)"), row(1, "Other Editor")]
    path = tmp_path / "names.json"
    NameIndex.precompute(rows, path, aliases=[group()])

    def forbidden(*args, **kwargs):
        raise AssertionError("offline builder called at runtime")

    monkeypatch.setattr(NameIndex, "__init__", forbidden)
    with pytest.raises(FileNotFoundError):
        NameIndex.load_precomputed(rows, tmp_path / "missing.json")
    index = NameIndex.load_precomputed(rows, path)
    resources = SearchResources(rows, None, None, s.build_bm25_index(rows),
                                include_disclaimers=False, prepared_name_index=index)
    for query in ["mse", "maple_studio_editor", "MSE"]:
        assert search(query, resources, k=1)[0]["title"] == rows[0]["title"]
    # Library clients without an artifact keep ordinary retrieval, never build.
    plain = SearchResources(rows, None, None, None, include_disclaimers=False)
    assert plain._name_index is None


@pytest.mark.parametrize("text", [
    "mse2", "mse_tools", "mse.run", "mse()", "mse[0]", ".mse", "mse++", "mse#",
    "mse-v2", "mse::run", "éMSE", "αMaple Studio Editor",
    ".NET C++ C# svadd[_f32]_m svint32_t svuint32_t",
])
def test_aliases_do_not_override_protected_identifier_boundaries(text):
    index = NameIndex([row(0, "Maple Studio Editor (MSE)")], [group()])
    assert index.keys(text) == frozenset()
    assert index.project(text) == text


def test_reviewed_spellings_share_one_name_but_do_not_match_partial_products():
    rows = [row(0, "Scikit-learn"), row(1, "Scikit-learn Extra")]
    index = NameIndex(rows, [group("Scikit-learn", ["sklearn", "sk learn"], ["Scikit-learn"])])
    for query in ["scikit_learn", "sklearn", "sk learn", "SK-LEARN"]:
        assert index.keys(query) == {"scikitlearn"}
        assert index.candidates(query) == [0]
    assert index.keys("Scikit-learn Extra") == {"scikitlearnextra"}
    assert index.project("Scikit-learn Extra", {"scikitlearn"}) == "Scikit-learn Extra"
    assert index.keys("sklearn and sk learn") == {"scikitlearn"}


def test_repeated_sources_and_same_key_alias_keep_boundaries_and_filters():
    rows = [row(i, "Maple Studio") for i in range(105)]
    index = NameIndex(rows, [group("Maple Studio", ["maplestudio"], ["Maple Studio"])])
    assert index.keys("maple_studio") == {"maplestudio"}
    assert len(index.candidates("maplestudio")) == 100
    assert index.candidates("maplestudio", eligible_ids=[104], limit=1) == [104]
    assert len(index.inventory["maplestudio"].sources) >= 105


def test_complete_parenthetical_editions_mask_shorter_alias_names(tmp_path):
    rows = [row(0, "Maple Studio Editor (MSE)"),
            row(1, "Maple Studio Editor (Open Source)"), row(2, "Maple Studio")]
    path = tmp_path / "names.json"
    NameIndex.precompute(rows, path, [group()])
    index = NameIndex.load_precomputed(rows, path)
    assert index.candidates("mse") == [0]
    for text in ["Maple Studio Editor (Open Source)", "Maple-Studio_Editor (Open Source)"]:
        assert index.keys(text) == frozenset()
    assert index.project("Maple Studio Editor (MSE)", {"maplestudio"}) == "Maple Studio Editor (MSE)"


@pytest.mark.parametrize("labels,groups,query,reason", [
    (["Alpha Beta Compute", "Alternate Binary Compiler"],
     [group("Alpha Beta Compute", ["ABC"], ["Alpha Beta Compute"]),
      group("Alternate Binary Compiler", ["ABC"], ["Alternate Binary Compiler"])],
     "abc", "ambiguous_alias"),
    (["Maple Studio Editor (MSE)", "mse"], [group()], "mse", "alias_conflicts_with_canonical"),
    (["Maple Studio"], [group("Maple Studio", ["map lestudio"], ["Maple Studio"])],
     "map lestudio", "alias_conflicts_with_canonical_signature"),
    (["Maple Studio Editor (MSE)"], [group(aliases=["M SE", "MS E"])],
     "mse", "conflicting_alias_component_signatures"),
    (["AB C", "A BC"], [group("AB C", ["alphabet"], ["AB C"])],
     "alphabet abc", "conflicting_canonical_component_signatures"),
    (["Shared Product"], [group("Maple Studio", ["mstudio"], ["Shared Product"]),
                          group("Maple Editor", ["meditor"], ["Shared Product"])],
     "mstudio meditor", "conflicting_source_label_owners"),
    (["Shared Product", "shared  product"],
     [group("Maple Studio", ["mstudio"], ["Shared Product"]),
      group("Maple Editor", ["meditor"], ["shared  product"])],
     "mstudio meditor", "conflicting_source_label_owners"),
    (["AB C (ABC)", "A BC (ABC)"],
     [group("AB C", ["alpha"], ["AB C (ABC)"]), group("A BC", ["beta"], ["A BC (ABC)"])],
     "alpha beta abc", "conflicting_canonical_component_signatures"),
])
def test_conflicting_aliases_are_rejected_without_overwriting_identity(labels, groups, query, reason):
    index = NameIndex([row(i, label) for i, label in enumerate(labels)], groups)
    assert index.keys(query) == frozenset()
    assert reason in {item["reason"] for item in index.report()["aliases"]["rejected"]}


@pytest.mark.parametrize("changes", [
    {"canonical": "C++"}, {"canonical": ".NET"}, {"canonical": "Widget 2"},
    {"canonical": "Maple .NET"}, {"canonical": "Maple Studio " * 10},
    {"canonical": "one two three four five six seven eight nine"},
    {"aliases": []}, {"aliases": "MSE"}, {"aliases": [None]}, {"aliases": ["MS"]},
    {"aliases": [".mse"]}, {"aliases": ["mse++"]},
    {"labels": []}, {"labels": "Maple Studio"}, {"labels": [None]}, {"labels": [""]},
    {"provenance": ""}, {"provenance": None},
])
def test_malformed_alias_inputs_fail_before_writing_artifact(tmp_path, changes):
    aliases = {**group(), **changes}
    path = tmp_path / "names.json"
    with pytest.raises(ValueError, match="Alias"):
        NameIndex.precompute([row(0, "Maple Studio Editor (MSE)")], path, [aliases])
    assert not path.exists()


@pytest.mark.parametrize("groups", [None, {}, "mse", [None], ["mse"]])
def test_invalid_alias_group_containers_have_clear_errors(groups):
    with pytest.raises(ValueError, match="[Aa]lias"):
        NameIndex([row(0, "Maple Studio Editor (MSE)")], groups)


def test_missing_explicit_label_is_reported_without_guessing_from_prose():
    rows = [row(0, "Other Editor")]
    rows[0]["original_text"] = "Maple Studio Editor (MSE)"
    index = NameIndex(rows, [group()])
    assert index.keys("mse maple_studio_editor") == frozenset()
    assert index.report()["aliases"]["rejected"][0]["reason"] == "no_exact_source_label"


def test_unselected_rows_cannot_add_aliases_through_metadata():
    data = row(0, "Maple Studio Editor (MSE)", name_aliases=[group()])
    assert NameIndex([data]).keys("mse") == frozenset()


def test_alias_cannot_reclaim_a_key_excluded_by_conflicting_labels():
    rows = [row(0, "Alpha Beta Compute (ABC)"), row(1, "A BC"), row(2, "AB C")]
    index = NameIndex(rows, [group("Alpha Beta Compute", ["ABC"], ["Alpha Beta Compute (ABC)"])])
    assert index.keys("ABC A BC AB C") == frozenset()
    assert index.candidates("ABC") == []
    assert index.report()["aliases"]["rejected"][0]["reason"] == "alias_conflicts_with_canonical"


def test_full_label_unicode_boundary_does_not_consume_independent_alias():
    index = NameIndex([row(0, "Maple Studio Editor (MSE)")], [group()])
    text = "éMaple Studio Editor (MSE)"
    assert [(m.start, m.end) for m in index.match(text)] == [(22, 25)]
