from portolan.schema import infer, infer_many, infer_scalar_from_strings, merge


def test_required_is_intersection_of_samples():
    schema = infer_many([{"a": 1, "b": "x"}, {"a": 2}])
    assert schema["required"] == ["a"]
    assert set(schema["properties"]) == {"a", "b"}


def test_int_and_float_widen_to_number():
    assert merge(infer(1), infer(1.5))["type"] == "number"


def test_string_formats():
    assert infer("2026-11-01")["format"] == "date"
    assert infer("2c1d5539-0b6e-4a8a-9f3e-6a1f0d6c2b11")["format"] == "uuid"
    assert infer("a@b.co")["format"] == "email"
    assert "format" not in merge(infer("2026-11-01"), infer("hello"))


def test_nullable_field_keeps_both_types():
    assert set(infer_many([{"x": None}, {"x": "y"}])["properties"]["x"]["type"]) == {"null", "string"}


def test_arrays_merge_item_schemas():
    schema = infer([{"id": 1}, {"id": 2, "name": "n"}])
    assert schema["items"]["required"] == ["id"]


def test_query_strings_recover_scalars():
    assert infer_scalar_from_strings(["1", "2"]) == {"type": "integer"}
    assert infer_scalar_from_strings(["true", "False"]) == {"type": "boolean"}
    assert infer_scalar_from_strings(["1", "two"]) == {"type": "string"}
