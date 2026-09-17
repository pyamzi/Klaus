from klausplus import keys


def test_mint_shape_and_uniqueness():
    a, b = keys.mint(), keys.mint()
    assert a != b and a.startswith("kp_") and len(a) == 35 and keys.looks_like_key(a)


def test_hash_is_sha256_hex_and_stable():
    h = keys.hash_key("kp_" + "0" * 32)
    assert len(h) == 64 and h == keys.hash_key("kp_" + "0" * 32)


def test_looks_like_key_rejects_junk():
    assert not keys.looks_like_key("sk-abc") and not keys.looks_like_key("kp_xyz") and not keys.looks_like_key("")
