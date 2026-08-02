"""TEST_VECTORS.md sections 3, 6.3, 6.4 and 6.5 — systematic withdrawals."""

import random

import pytest

from calculators.errors import InvalidAmountError, InvalidRateError
from calculators.rates import monthly_rate
from calculators.swp import resolve_withdrawal, swp_projection

MONEY_TOLERANCE = 1e-4

# TEST_VECTORS.md section 3.1: P, years, R, W, FV, withdrawn, profit.
HEALTHY = {
    "W1": (1_000_000, 10, 9.0, 8_000, 849_614.446908, 960_000, 809_614.446908),
    "W2": (2_000_000, 5, 10.0, 20_000, 1_689_795.398569, 1_200_000, 889_795.398569),
}

# TEST_VECTORS.md sections 3.3 and 6.4: P, years, R, W, FV, depletion month,
# full withdrawals, final partial, actual withdrawn.
DEPLETING = {
    "W4": (
        500_000, 10, 8.0, 6_000,
        -1_283.140528, 120, 119, 4_716.859472, 718_716.859472,
    ),
    "W5": (
        300_000, 10, 8.0, 6_000,
        -433_068.139982, 61, 60, 3_150.662727, 363_150.662727,
    ),
}

# TEST_VECTORS.md section 6.3: P, years, W, FV, withdrawn, depletion month.
ZERO_RATE = {
    "W8a": (1_000_000, 5, 6_000, 640_000.0, 360_000, None),
    "W8b": (500_000, 10, 6_000, -220_000.0, 720_000, 84),
}


@pytest.mark.parametrize("case", HEALTHY)
def test_W1_W2_projection_matches_vectors(case):
    p, years, rate, w, fv, withdrawn, profit = HEALTHY[case]
    result = swp_projection(p, years, rate, w)

    assert result.final_balance == pytest.approx(fv, abs=MONEY_TOLERANCE)
    assert result.total_withdrawn == pytest.approx(withdrawn, abs=MONEY_TOLERANCE)
    assert result.total_profit == pytest.approx(profit, abs=MONEY_TOLERANCE)
    assert result.months == years * 12
    assert result.depleted is False
    assert result.depletion_month is None
    # Nothing was missed, so the physical and nominal totals agree.
    assert result.actual_withdrawn == pytest.approx(withdrawn, abs=MONEY_TOLERANCE)


@pytest.mark.parametrize("case", HEALTHY)
def test_W1_W2_cross_checked_by_simulation(case):
    """Independent oracle: drain the corpus one month at a time."""
    p, years, rate, w, fv, _withdrawn, _profit = HEALTHY[case]
    r = monthly_rate(rate)

    balance = float(p)
    for _ in range(years * 12):
        balance = balance * (1.0 + r) - w

    assert balance == pytest.approx(fv, abs=1e-6)


def test_W3_percent_of_lumpsum_resolves_to_the_same_computation_as_W1():
    """0.8% of ₹10,00,000 is ₹8,000 a month — one code path, not two."""
    resolved = resolve_withdrawal(1_000_000, percent=0.8)
    assert resolved == pytest.approx(8_000.0, abs=MONEY_TOLERANCE)

    from_percent = swp_projection(1_000_000, 10, 9.0, resolved)
    from_rupees = swp_projection(1_000_000, 10, 9.0, 8_000)

    assert from_percent == from_rupees
    assert from_percent.final_balance == pytest.approx(849_614.446908, abs=MONEY_TOLERANCE)
    assert from_percent.total_withdrawn == pytest.approx(960_000, abs=MONEY_TOLERANCE)
    assert from_percent.total_profit == pytest.approx(809_614.446908, abs=MONEY_TOLERANCE)


def test_resolve_withdrawal_requires_exactly_one_form():
    with pytest.raises(InvalidAmountError):
        resolve_withdrawal(1_000_000)
    with pytest.raises(InvalidAmountError):
        resolve_withdrawal(1_000_000, amount=8_000, percent=0.8)


@pytest.mark.parametrize("case", DEPLETING)
def test_W4_W5_depletion_is_detected_and_dated(case):
    p, years, rate, w, fv, month, _full, _partial, _actual = DEPLETING[case]
    result = swp_projection(p, years, rate, w)

    # The closed form is still reported as the spec defines it...
    assert result.final_balance == pytest.approx(fv, abs=MONEY_TOLERANCE)
    # ...but the projection knows it is not a balance anyone will ever hold.
    assert result.depleted is True
    assert result.depletion_month == month


@pytest.mark.parametrize("case", DEPLETING)
def test_W4_W5_actual_withdrawn_counts_only_real_withdrawals(case):
    """Section 6.4: full withdrawals taken, plus one final partial."""
    p, years, rate, w, _fv, month, full, partial, actual = DEPLETING[case]
    result = swp_projection(p, years, rate, w)

    assert result.actual_withdrawn == pytest.approx(actual, abs=MONEY_TOLERANCE)
    assert result.actual_withdrawn == pytest.approx(
        full * w + partial, abs=MONEY_TOLERANCE
    )
    assert full == month - 1
    # The spec's W x n overstates what could physically be withdrawn.
    assert result.actual_withdrawn < result.total_withdrawn


def test_W5_spec_profit_contradicts_what_the_saver_actually_received():
    """Guards the reason actual_withdrawn exists at all.

    W5 draws ₹3,63,150.66 out of a ₹3,00,000 corpus — ₹63,150.66 more than
    went in — while the spec's FV + W*n - P reports a *loss* of ₹13,068.14,
    because W*n bills 120 withdrawals against a plan that ended at 61. Both
    numbers describe the same plan and they disagree in sign. That is what
    the depleted flag exists to stop reaching a user.

    (An earlier revision of TEST_VECTORS.md section 3.3 narrated this profit
    as ₹2,86,932, which is FV + W*n with the - P dropped. The formula block in
    section 3 was taken as authoritative and the discrepancy raised rather
    than coded around; the section now carries a correction notice recording
    it. Nothing asserted below ever depended on the prose.)
    """
    result = swp_projection(300_000, 10, 8.0, 6_000)

    fv, withdrawn, actual, corpus = -433_068.139982, 720_000, 363_150.662727, 300_000

    assert result.depleted is True
    assert result.depletion_month == 61
    # Composed from the section 3/6.4 vectors, so no new constant is invented.
    assert result.total_profit == pytest.approx(
        fv + withdrawn - corpus, abs=MONEY_TOLERANCE
    )
    assert result.total_profit < 0 < actual - corpus
    assert result.actual_withdrawn > corpus


def test_W4_spec_profit_is_positive_on_a_corpus_that_ran_dry():
    """The same trap from the other side.

    W4 depletes exactly at the term end, so the spec's profit happens to be
    right — ₹2,18,716.86, matching actual_withdrawn - P. What it is paired
    with is a final balance of ₹-1,283.14. A layer that prints FV verbatim
    still tells the user their portfolio ended below zero.
    """
    result = swp_projection(500_000, 10, 8.0, 6_000)
    fv, withdrawn, corpus = -1_283.140528, 720_000, 500_000

    assert result.final_balance < 0
    assert result.total_profit == pytest.approx(
        fv + withdrawn - corpus, abs=MONEY_TOLERANCE
    )
    assert result.total_profit == pytest.approx(
        result.actual_withdrawn - corpus, abs=MONEY_TOLERANCE
    )


def test_W6_zero_withdrawal_is_pure_growth():
    result = swp_projection(1_000_000, 10, 9.0, 0)
    r = monthly_rate(9.0)

    assert result.final_balance == pytest.approx(
        1_000_000 * (1.0 + r) ** 120, abs=MONEY_TOLERANCE
    )
    assert result.total_withdrawn == 0
    assert result.actual_withdrawn == 0
    assert result.depleted is False


@pytest.mark.parametrize("bad", [1_000_001, 2_000_000])
def test_W7_withdrawal_larger_than_the_corpus_is_rejected(bad):
    with pytest.raises(InvalidAmountError) as exc:
        swp_projection(1_000_000, 10, 9.0, bad)
    assert exc.value.field == "monthly withdrawal"


@pytest.mark.parametrize("case", ZERO_RATE)
def test_W8_zero_rate_degenerates_to_principal_minus_withdrawals(case):
    p, years, w, fv, withdrawn, month = ZERO_RATE[case]
    result = swp_projection(p, years, 0, w)

    assert result.final_balance == pytest.approx(fv, abs=MONEY_TOLERANCE)
    assert result.total_withdrawn == pytest.approx(withdrawn, abs=MONEY_TOLERANCE)
    assert result.depletion_month == month
    assert result.depleted is (month is not None)


@pytest.mark.parametrize("case", ZERO_RATE)
def test_W8_zero_rate_profit_is_exactly_zero(case):
    """Section 6.3's standalone invariant: no growth, no profit. Ever."""
    p, years, w, _fv, _withdrawn, _month = ZERO_RATE[case]
    assert swp_projection(p, years, 0, w).total_profit == 0.0


@pytest.mark.parametrize(
    "p, years, w",
    [(1_000_000, 10, 8_000), (500_000, 3, 1), (250_000, 40, 250_000), (10_000, 1, 0)],
)
def test_W8_zero_rate_profit_invariant_holds_for_arbitrary_inputs(p, years, w):
    assert swp_projection(p, years, 0, w).total_profit == 0.0


def test_W8_zero_rate_depletion_withdraws_exactly_the_corpus():
    """At R = 0 there is nothing but the corpus to withdraw."""
    result = swp_projection(500_000, 10, 0, 6_000)
    assert result.actual_withdrawn == pytest.approx(500_000, abs=MONEY_TOLERANCE)


@pytest.mark.parametrize("bad", [0, -1, -1_000_000])
def test_W9_non_positive_lumpsum_is_rejected(bad):
    with pytest.raises(InvalidAmountError) as exc:
        swp_projection(bad, 10, 9.0, 8_000)
    assert exc.value.field == "lumpsum amount"


@pytest.mark.parametrize("bad", [100.1, 150, -0.5])
def test_W10_percent_outside_zero_to_hundred_is_rejected(bad):
    with pytest.raises(InvalidRateError) as exc:
        resolve_withdrawal(1_000_000, percent=bad)
    assert exc.value.field == "withdrawal percentage"


def test_monotonicity_a_non_negative_final_balance_never_dipped():
    """Section 6.5 — the property that lets depletion simulation be skipped.

    Sampled rather than exhaustive; the full 400,000-scenario sweep and the
    fixed-point argument live in TEST_VECTORS.md section 6.5.
    """
    rng = random.Random(20260801)

    for _ in range(2_000):
        p = rng.uniform(10_000, 5_000_000)
        rate = rng.uniform(0, 100)
        years = rng.randint(1, 40)
        w = rng.uniform(0, p / 2)

        result = swp_projection(p, years, rate, w)
        if result.depleted:
            continue

        r = result.monthly_rate
        balance = p
        for _ in range(result.months):
            balance = balance * (1.0 + r) - w
            assert balance >= -MONEY_TOLERANCE, (
                "a non-negative closed-form FV concealed an intermediate "
                f"dip: P={p} R={rate} years={years} W={w}"
            )
