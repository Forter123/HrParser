def test_login_page_accessible(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_login_success_redirects_to_feed(client, make_user):
    user = make_user()
    resp = client.post(
        "/login", data={"email": user.email, "password": "secret123"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_wrong_password_rejected(client, make_user):
    user = make_user()
    resp = client.post(
        "/login", data={"email": user.email, "password": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 400


def test_login_unknown_email_rejected(client):
    resp = client.post(
        "/login", data={"email": "nobody@example.com", "password": "x"}, follow_redirects=False
    )
    assert resp.status_code == 400


def test_protected_route_requires_auth(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_protected_route_after_login(logged_in_client):
    client, _ = logged_in_client
    resp = client.get("/")
    assert resp.status_code == 200


def test_session_persists_across_requests(logged_in_client):
    client, _ = logged_in_client
    resp1 = client.get("/searches")
    resp2 = client.get("/")
    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_logout_clears_session(logged_in_client):
    client, _ = logged_in_client
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 303
