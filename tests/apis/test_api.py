def test_importing_api():
    from lab_data.apis import api_entry_point

    assert api_entry_point.prefix == 'newapi'
    assert api_entry_point.name == 'NewAPI'
