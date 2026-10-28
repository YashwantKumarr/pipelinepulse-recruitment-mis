from decimal import Decimal

import pytest

from app.services.finance import DEMO_LABEL, compute_draft_amount, parse_money, parse_percent


def test_draft_amount_uses_decimal_half_up_rounding():
    assert compute_draft_amount(Decimal("1234567.89"), Decimal("12.5")) == Decimal("154320.99")
    assert compute_draft_amount(Decimal("0.05"), Decimal("50")) == Decimal("0.03")


def test_exact_draft_amount():
    assert compute_draft_amount(Decimal("1200000.00"), Decimal("8.33")) == Decimal("99960.00")


@pytest.mark.parametrize("value", ["0", "-5", "10.123", "1e3", "abc", "", "1,000"])
def test_invalid_money_is_rejected(value):
    from app.errors import AppError

    with pytest.raises(AppError) as info:
        parse_money(value, "amount")
    assert info.value.status_code == 422


@pytest.mark.parametrize("value", ["0", "101", "-1", "abc", "8.333", "1e2"])
def test_invalid_percent_is_rejected(value):
    from app.errors import AppError

    with pytest.raises(AppError):
        parse_percent(value)


def _draft(client, candidate_id, job_id, ctc="1200000.00", percent="8.33"):
    return client.post(
        "/api/finance/placement-fee-drafts",
        json={"candidate_id": candidate_id, "job_id": job_id, "annual_ctc": ctc, "fee_percent": percent},
    )


@pytest.fixture
def ids(client, upload, make_job):
    candidate = upload("cv.txt", b"Python", name="Finance Demo").json()
    job = make_job()
    return candidate["id"], job["id"]


def test_fee_draft_is_labelled_demonstration_with_decimal_strings(client, ids):
    cid, jid = ids
    response = _draft(client, cid, jid)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["draft_amount"] == "99960.00"
    assert body["fee_percent"] == "8.33"
    assert body["annual_ctc"] == "1200000.00"
    assert body["status"] == "draft"
    assert body["label"] == DEMO_LABEL


def test_fee_percent_is_normalised(client, ids):
    cid, jid = ids
    assert _draft(client, cid, jid, percent="8.30").json()["fee_percent"] == "8.3"


def test_draft_requires_known_candidate_and_job(client, ids):
    cid, jid = ids
    assert _draft(client, 9999, jid).status_code == 404
    assert _draft(client, cid, 9999).status_code == 404


def test_payment_is_demo_labelled_and_limited_to_draft_amount(client, ids):
    cid, jid = ids
    draft = _draft(client, cid, jid, ctc="100000.00", percent="10").json()
    first = client.post(
        "/api/finance/payments", json={"draft_id": draft["id"], "amount": "6000.00", "status": "recorded"}
    )
    assert first.status_code == 201
    assert first.json()["is_demo"] is True
    assert first.json()["label"] == DEMO_LABEL

    over = client.post(
        "/api/finance/payments", json={"draft_id": draft["id"], "amount": "4000.01", "status": "pending"}
    )
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "payment_exceeds_draft"


def test_failed_payments_do_not_count_toward_the_limit(client, ids):
    cid, jid = ids
    draft = _draft(client, cid, jid, ctc="100000.00", percent="10").json()
    client.post(
        "/api/finance/payments", json={"draft_id": draft["id"], "amount": "9000.00", "status": "failed"}
    )
    response = client.post(
        "/api/finance/payments", json={"draft_id": draft["id"], "amount": "10000.00", "status": "recorded"}
    )
    assert response.status_code == 201


def test_payment_status_and_draft_reference_are_validated(client, ids):
    cid, jid = ids
    draft = _draft(client, cid, jid).json()
    assert (
        client.post(
            "/api/finance/payments", json={"draft_id": draft["id"], "amount": "1.00", "status": "settled"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/finance/payments", json={"draft_id": 9999, "amount": "1.00", "status": "pending"}
        ).status_code
        == 404
    )


def test_listing_endpoints_return_demo_records(client, ids):
    cid, jid = ids
    _draft(client, cid, jid)
    assert len(client.get("/api/finance/placement-fee-drafts").json()) == 1
    assert client.get("/api/finance/payments").json() == []
