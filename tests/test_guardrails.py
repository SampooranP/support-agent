from agent.guardrails import RateLimiter, foreign_personal_data, redact, unconfirmed_claims

MAYA = ("maya.chen@example.com", "206-555-0117")


def test_own_and_support_contact_details_are_allowed():
    text = "We'll email maya.chen@example.com or call 206-555-0117. Reach us at support@lumenandpine.example or 1-800-555-0142."
    assert foreign_personal_data(text, *MAYA) == []


def test_other_customers_details_are_flagged():
    text = "That order belongs to priya.n@example.com, phone (512) 555-0148."
    assert sorted(foreign_personal_data(text, *MAYA)) == ["(512) 555-0148", "priya.n@example.com"]


def test_phone_formats_match_regardless_of_punctuation():
    assert foreign_personal_data("Call +1 206 555 0117", *MAYA) == []  # Maya's own number
    assert foreign_personal_data("Call 512.555.0148", *MAYA) == ["512.555.0148"]


def test_order_numbers_and_prices_are_not_phone_numbers():
    assert foreign_personal_data("Order #1042 for $301.32, tracking 1Z999AA10123456784", *MAYA) == []


def test_redact_replaces_every_occurrence():
    assert redact("a@x.com and a@x.com", ["a@x.com"]) == "[redacted] and [redacted]"


def test_completed_refund_claims_are_detected():
    for text in [
        "Your refund is approved and done.",
        "The refund has been issued to your card.",
        "**$301.32** has gone back to your original payment method.",
        "I've processed your refund.",
    ]:
        assert unconfirmed_claims(text, set()) == ["issue_refund"], text


def test_pending_refund_language_is_not_a_claim():
    for text in [
        "I've sent your refund request to a supervisor for review.",
        "Your refund request has been sent for review.",
        "Once the refund is approved, it usually appears within 5-10 business days.",
        "A supervisor needs to approve the refund first.",
    ]:
        assert unconfirmed_claims(text, set()) == [], text


def test_negated_and_unrelated_phrasing_is_not_a_claim():
    # Both were flagged by an earlier version of the patterns during a scenario run.
    for text in [
        "A supervisor turned it down for now, so no refund has been issued yet.",
        "If you have an order confirmation email for #1045, please check which email address it was sent to.",
        "Nothing has been refunded, and the refund hasn't been processed.",
        # Quoted from the refund policy in a baseline eval run.
        "Once approved, the refund is issued to your original payment method.",
        "If approved, the refund is processed within 2 business days.",
        # Agent replies flagged in the baseline runs: the condition comes after the claim.
        "**Timing**\nThe refund is processed once the tent reaches us.",
        "The refund is issued once the tent arrives back with us, not before.",
    ]:
        assert unconfirmed_claims(text, set()) == [], text
    # A negation in an earlier sentence doesn't hide a real claim in the next one.
    assert unconfirmed_claims("That wasn't ideal. Your refund has been issued.", set()) == ["issue_refund"]
    assert unconfirmed_claims("Your refund has been issued, once again sorry.", set()) == ["issue_refund"]


def test_claims_backed_by_an_executed_action_are_fine():
    assert unconfirmed_claims("The refund has been issued.", {"issue_refund"}) == []


def test_email_claims():
    assert unconfirmed_claims("I've sent you an email with the return label.", set()) == ["send_email"]
    assert unconfirmed_claims("I'll send you an email once it's approved.", set()) == []


def test_rate_limiter_window():
    limiter = RateLimiter(limit=2, window_s=10)
    assert limiter.allow("c", now=0) and limiter.allow("c", now=1)
    assert not limiter.allow("c", now=2)
    assert limiter.allow("other", now=2)  # limits are per key
    assert limiter.allow("c", now=11.5)  # the first hit has left the window


def test_rate_limiter_prunes_idle_keys():
    limiter = RateLimiter(limit=1, window_s=10)
    limiter.allow("old", now=0)
    limiter.prune(now=100)
    assert "old" not in limiter._hits
