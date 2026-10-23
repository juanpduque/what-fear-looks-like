"""export_supabase: static autopsy files become one row per film."""

from export_supabase import load_id_map, normalize_row, rows_from_maps


def test_load_id_map_reads_a_window_assignment(tmp_path):
    path = tmp_path / "lookup.js"
    path.write_text('/* n=1 */\nwindow.LOOKUP={"948":{"t":"Halloween"}};\n', encoding="utf-8")
    assert load_id_map(path) == {"948": {"t": "Halloween"}}


def test_load_id_map_reads_json(tmp_path):
    path = tmp_path / "omdb.json"
    path.write_text('{"948":[91,0,"R"]}', encoding="utf-8")
    assert load_id_map(path)["948"][0] == 91


def test_rows_merge_columns_and_skip_non_numeric_ids():
    rows = rows_from_maps(
        {
            "lookup": {"10": {"t": "A"}, "nope": {"t": "x"}},
            "omdb": {"10": [90, 0], "11": [80, 0]},
        }
    )
    assert rows == [
        {"id": 10, "lookup": {"t": "A"}, "omdb": [90, 0]},
        {"id": 11, "omdb": [80, 0]},
    ]


def test_normalize_row_gives_every_row_the_same_keys():
    a = normalize_row({"id": 1, "lookup": {"t": "A"}})
    b = normalize_row({"id": 2, "omdb": [80, 0]})
    assert a.keys() == b.keys()
    assert a["omdb"] is None and b["lookup"] is None


def test_limit_keeps_the_lowest_ids():
    rows = rows_from_maps({"lookup": {"3": {}, "1": {}, "2": {}}}, limit=2)
    assert [row["id"] for row in rows] == [1, 2]
