def test_fixtures_work(two_users, admin):
    a, pa, b, pb = two_users
    assert a.get("/api/status").status_code == 200
    assert admin.get("/api/admin/overview").status_code == 200
