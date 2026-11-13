from himari.region_select import (
    describe_region,
    fit_rect,
    map_selection,
    normalized_rect,
)


def test_normalized_rect_handles_reversed_drags():
    assert normalized_rect(30, 40, 10, 20) == (10, 20, 20, 20)
    assert normalized_rect(5, 5, 5, 5) == (5, 5, 0, 0)


def test_fit_rect_keeps_aspect_and_centers():
    x, y, width, height = fit_rect(1000, 500, 800, 600)

    assert (width, height) == (667, 500)
    assert x == (1000 - 667) // 2
    assert y == 0


def test_map_selection_translates_to_physical_desktop_pixels():
    monitor = {"left": 1920, "top": 0, "width": 1920, "height": 1080}

    region = map_selection(
        selection=(100, 50, 200, 100),
        display=(100, 50, 200, 100),
        image_size=(400, 200),
        monitor_box=monitor,
    )

    assert region == {
        "left": 1920,
        "top": 0,
        "width": 400,
        "height": 200,
    }


def test_map_selection_accounts_for_letterbox_offsets():
    monitor = {"left": 0, "top": 0, "width": 100, "height": 100}

    region = map_selection(
        selection=(30, 0, 20, 20),
        display=(20, 0, 60, 100),
        image_size=(60, 100),
        monitor_box=monitor,
    )

    assert region == {"left": 10, "top": 0, "width": 20, "height": 20}


def test_map_selection_rejects_clicks_and_tiny_drags():
    monitor = {"left": 0, "top": 0, "width": 100, "height": 100}

    assert map_selection((10, 10, 0, 0), (0, 0, 100, 100), (100, 100), monitor) is None
    assert map_selection((10, 10, 4, 4), (0, 0, 100, 100), (100, 100), monitor) is None
    assert map_selection((0, 0, 10, 10), (0, 0, 0, 0), (100, 100), monitor) is None


def test_describe_region_reports_size_and_position():
    assert describe_region(None) == "No custom region selected"
    described = describe_region({"left": 10, "top": 20, "width": 30, "height": 40})
    assert "30 × 40" in described
    assert "(10, 20)" in described
