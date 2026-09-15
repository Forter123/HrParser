from app.auth import hash_password, verify_password


def test_hash_password_produces_verifiable_hash():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("secret123")
    assert verify_password("wrong", hashed) is False


def test_verify_password_handles_malformed_hash_gracefully():
    assert verify_password("secret123", "not-a-valid-bcrypt-hash") is False
