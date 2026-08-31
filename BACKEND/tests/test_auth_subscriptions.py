from app import auth, subscriptions


def test_otp_flow(tmp_path, monkeypatch):
    test_users = str(tmp_path / "test_users.json")
    monkeypatch.setattr(auth, "USERS_PATH", test_users)
    phone = "+919876543210"
    otp = auth.generate_otp(phone)
    assert len(otp) == 6
    assert otp.isdigit()

    # Wrong OTP fails
    assert not auth.verify_otp(phone, "000000" if otp != "000000" else "111111")

    # Re-generate and verify correctly
    otp2 = auth.generate_otp(phone)
    assert auth.verify_otp(phone, otp2)

    # Reusing used OTP fails
    assert not auth.verify_otp(phone, otp2)


def test_token_issuance_and_verification():
    phone = "+919876543210"
    token = auth.issue_token(phone)
    assert token is not None

    verified_phone = auth._verify_token(token)
    assert verified_phone == phone

    # Tampered token fails
    tampered = token[:-4] + "abcd"
    assert auth._verify_token(tampered) is None


def test_subscriptions_crud(tmp_path, monkeypatch):
    test_store = str(tmp_path / "test_subscriptions.json")
    monkeypatch.setattr(subscriptions, "STORE_PATH", test_store)

    sub = subscriptions.add_subscription(
        phone="+919876543210",
        lat=22.57,
        lon=88.36,
        lang="en",
        label="Home",
        cyclone_alerts=True,
    )
    assert sub["phone"] == "+919876543210"
    assert sub["lat"] == 22.57

    retrieved = subscriptions.get_subscription("+919876543210")
    assert retrieved is not None
    assert retrieved["label"] == "Home"

    all_subs = subscriptions.list_subscriptions()
    assert len(all_subs) == 1

    removed = subscriptions.remove_subscription("+919876543210")
    assert removed is True
    assert subscriptions.get_subscription("+919876543210") is None
