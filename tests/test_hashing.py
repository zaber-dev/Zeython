import pytest

from zeython.hashing import hash_password, verify_password


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_is_salted_and_nondeterministic() -> None:
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_hash_encodes_algorithm_and_iterations() -> None:
    hashed = hash_password("password", iterations=1000)
    algorithm, iterations, _salt, _digest = hashed.split("$")
    assert algorithm == "pbkdf2_sha256"
    assert iterations == "1000"


def test_verify_rejects_malformed_hash() -> None:
    assert not verify_password("password", "not-a-real-hash")
    assert not verify_password("password", "")
    assert not verify_password("password", "pbkdf2_sha256$notanumber$c2FsdA==$aGFzaA==")


def test_hash_password_rejects_empty_password() -> None:
    with pytest.raises(ValueError):
        hash_password("")
