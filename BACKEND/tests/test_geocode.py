import pytest
from app import geocode


@pytest.mark.asyncio
async def test_resolve_digha():
    res = await geocode.resolve_location("digha")
    assert res is not None
    assert "Digha" in res["name"]
    # Must resolve to West Bengal (not Dighwāra in Bihar)
    assert res.get("admin1") in ("West Bengal", "WB") or "Bengal" in str(res.get("admin1"))
    assert 21.0 <= res["latitude"] <= 22.5
    assert 87.0 <= res["longitude"] <= 88.0


@pytest.mark.asyncio
async def test_resolve_kalighat():
    res = await geocode.resolve_location("kalighat")
    assert res is not None
    assert "Kalighat" in res["name"]
    # Must resolve to Kolkata / West Bengal (not Kālīghāti in Rajasthan)
    assert res.get("admin1") in ("West Bengal", "Kolkata") or res.get("admin2") in ("Kolkata", "West Bengal")
    assert 22.0 <= res["latitude"] <= 23.0
    assert 88.0 <= res["longitude"] <= 89.0


@pytest.mark.asyncio
async def test_resolve_dakshineswar():
    res = await geocode.resolve_location("dakshineswar")
    assert res is not None
    assert "Dakshineswar" in res["name"]
    assert 22.5 <= res["latitude"] <= 22.8
    assert 88.2 <= res["longitude"] <= 88.5


@pytest.mark.asyncio
async def test_resolve_dighwara():
    res = await geocode.resolve_location("dighwara")
    assert res is not None
    assert "Bihar" in str(res.get("admin1")) or 25.0 <= res["latitude"] <= 26.5


@pytest.mark.asyncio
async def test_resolve_bandra():
    res = await geocode.resolve_location("bandra")
    assert res is not None
    assert "Maharashtra" in str(res.get("admin1")) or "Mumbai" in str(res.get("admin2")) or (18.5 <= res["latitude"] <= 19.5)


@pytest.mark.asyncio
async def test_resolve_aliases():
    res_wb = await geocode.resolve_location("west bengal")
    assert res_wb is not None
    assert "Kolkata" in res_wb["name"] or "Bengal" in str(res_wb.get("admin1")) or "West Bengal" in res_wb["name"]

    res_delhi = await geocode.resolve_location("ncr")
    assert res_delhi is not None
    assert "Delhi" in res_delhi["name"] or "Delhi" in str(res_delhi.get("admin1"))


@pytest.mark.asyncio
async def test_resolve_kathmandu():
    res = await geocode.resolve_location("kathmandu")
    assert res is not None
    assert "Kathmandu" in res["name"]
    assert res.get("country") == "Nepal"
    assert 27.0 <= res["latitude"] <= 28.5
    assert 85.0 <= res["longitude"] <= 86.0


@pytest.mark.asyncio
async def test_resolve_international():
    res_tokyo = await geocode.resolve_location("tokyo")
    assert res_tokyo is not None
    assert "Tokyo" in res_tokyo["name"]
    assert res_tokyo.get("country") == "Japan"

    res_dhaka = await geocode.resolve_location("dhaka")
    assert res_dhaka is not None
    assert "Dhaka" in res_dhaka["name"]
    assert res_dhaka.get("country") == "Bangladesh"


@pytest.mark.asyncio
async def test_resolve_rajarhat_and_chinar_park():
    # Multi-part with Kolkata qualifier
    res_rk = await geocode.resolve_location("rajarhat, kolkata")
    assert res_rk is not None
    assert "Bengal" in str(res_rk.get("admin1")) or "Kolkata" in str(res_rk.get("admin2"))
    assert 22.4 <= res_rk["latitude"] <= 22.8
    assert 88.3 <= res_rk["longitude"] <= 88.6

    res_cpk = await geocode.resolve_location("chinar park, kolkata")
    assert res_cpk is not None
    assert "Bengal" in str(res_cpk.get("admin1")) or "Kolkata" in str(res_cpk.get("admin2")) or "Bidhannagar" in str(res_cpk.get("admin2"))
    assert 22.4 <= res_cpk["latitude"] <= 22.8
    assert 88.3 <= res_cpk["longitude"] <= 88.6

    # Standalone names
    res_r = await geocode.resolve_location("rajarhat")
    assert res_r is not None
    assert "Bengal" in str(res_r.get("admin1")) or 22.4 <= res_r["latitude"] <= 22.8

    res_cp = await geocode.resolve_location("chinar park")
    assert res_cp is not None
    assert "Bengal" in str(res_cp.get("admin1")) or "Kolkata" in str(res_cp.get("admin2")) or (22.4 <= res_cp["latitude"] <= 22.8)


@pytest.mark.asyncio
async def test_resolve_empty():
    assert await geocode.resolve_location("") is None
    assert await geocode.resolve_location("   ") is None
    assert await geocode.resolve_location(None) is None
