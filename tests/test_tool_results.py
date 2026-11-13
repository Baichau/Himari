from himari.tool_results import classify_result


def test_successful_values_classify_as_success():
    assert classify_result("Chrome is open.") == (True, "")
    assert classify_result({"ok": True}) == (True, "")
    assert classify_result([1, 2]) == (True, "")
    assert classify_result(0) == (True, "")


def test_obvious_failures_classify_as_failures():
    assert classify_result(None) == (False, "The tool returned no result.")
    assert classify_result("") == (False, "The tool returned an empty result.")
    assert classify_result({"ok": False, "error": "boom"}) == (False, "boom")
    assert classify_result("Denied: no") == (False, "Denied: no")
    assert classify_result("Tool error: boom") == (False, "Tool error: boom")
    assert classify_result("Permission denied: C:/x") == (
        False,
        "Permission denied: C:/x",
    )
    assert classify_result("Invalid arguments: name") == (
        False,
        "Invalid arguments: name",
    )
    assert classify_result("Unknown tool: foo")[0] is False
    assert classify_result("outside the configured allowed folders")[0] is False
    assert classify_result("Failed to open Chrome: boom")[0] is False
    assert classify_result("Failed: boom")[0] is False
    assert classify_result("Could not find 'Chrome'.")[0] is False
    assert classify_result("Unable to reach the service.")[0] is False
    assert classify_result("Cannot write to that folder.")[0] is False
