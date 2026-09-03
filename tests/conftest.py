"""Shared fixtures for the SimulateCraft test suite."""

from __future__ import annotations

import pytest

from helpers import RunnerFactory
from simulatecraft.core import EventBus


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def make_runner() -> RunnerFactory:
    return RunnerFactory()
