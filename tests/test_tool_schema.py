import pytest

from himari.tool_schema import ToolArgumentError, validate_arguments

PARAMETERS = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
        "mode": {"type": "string", "enum": ["fast", "deep"]},
    },
    "required": ["name"],
}


def test_valid_arguments_are_returned_as_a_copy():
    arguments = {"name": "Chrome", "count": 2, "mode": "fast"}

    result = validate_arguments(PARAMETERS, arguments)

    assert result == arguments
    assert result is not arguments


def test_missing_required_argument_is_rejected():
    with pytest.raises(ToolArgumentError, match="Missing required argument"):
        validate_arguments(PARAMETERS, {"count": 2})


def test_unexpected_argument_is_rejected():
    with pytest.raises(ToolArgumentError, match="Unexpected argument"):
        validate_arguments(PARAMETERS, {"name": "Chrome", "path": "C:/"})


def test_wrong_type_is_rejected():
    with pytest.raises(ToolArgumentError, match="must be a integer"):
        validate_arguments(PARAMETERS, {"name": "Chrome", "count": "two"})
    with pytest.raises(ToolArgumentError, match="must be a string"):
        validate_arguments(PARAMETERS, {"name": 7})


def test_boolean_is_not_an_integer():
    with pytest.raises(ToolArgumentError):
        validate_arguments(PARAMETERS, {"name": "Chrome", "count": True})


def test_enum_values_are_enforced():
    with pytest.raises(ToolArgumentError, match="must be one of"):
        validate_arguments(PARAMETERS, {"name": "Chrome", "mode": "slow"})


def test_non_object_arguments_are_rejected():
    with pytest.raises(ToolArgumentError, match="must be an object"):
        validate_arguments(PARAMETERS, ["name"])


def test_tools_without_declared_properties_accept_named_arguments():
    assert validate_arguments({}, {"anything": 1}) == {"anything": 1}
