"""Tests for security utility functions."""

import pytest
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_and_verify():
    pw = "supersecretpassword"
    hashed = get_password_hash(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


def test_create_and_decode_token():
    token = create_access_token(data={"sub": "admin"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "admin"


def test_decode_invalid_token():
    result = decode_access_token("not.a.real.token")
    assert result is None


def test_decode_tampered_token():
    token = create_access_token(data={"sub": "admin"})
    tampered = token + "x"
    result = decode_access_token(tampered)
    assert result is None
