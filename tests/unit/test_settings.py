# Developed by ::> Gehan Fernando
"""Checks the allowed range of every knob."""

from dataclasses import replace

import pytest

from src import EffectConfig, InputValidationError


def test_default_config_is_valid() -> None:
    EffectConfig().validate()


# The very edges of every allowed range must still be accepted
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rotation_seconds", 2.0),
        ("rotation_seconds", 100.0),
        ("intensity", 0.0),
        ("intensity", 1.0),
        ("ambience", 0.0),
        ("ambience", 1.0),
        ("limiter_ceiling", 0.0625),
        ("limiter_ceiling", 1.0),
        ("quality", 0),
        ("quality", 9),
    ],
)
def test_boundary_values_are_accepted(field: str, value: float) -> None:
    replace(EffectConfig(), **{field: value}).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rotation_seconds", 1.0),
        ("rotation_seconds", 101.0),
        ("intensity", -0.1),
        ("intensity", 1.1),
        ("ambience", -0.1),
        ("ambience", 1.1),
        ("limiter_ceiling", 0.01),
        ("limiter_ceiling", 1.1),
        ("quality", -1),
        ("quality", 10),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(InputValidationError):
        replace(EffectConfig(), **{field: value}).validate()


def test_config_is_immutable() -> None:
    with pytest.raises(AttributeError):
        EffectConfig().intensity = 0.5  # type: ignore[misc]
