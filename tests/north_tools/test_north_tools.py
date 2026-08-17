def test_importing_north_tool():
    # This will raise an exception if pydantic model validation fails.
    from lab_data.north_tools import north_entry_point

    assert north_entry_point.id_url_safe == 'lab-data-lab-analysis'
    assert north_entry_point.north_tool.display_name == 'Lab Analysis'