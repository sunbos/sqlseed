"""Test resource wrappers must keep failures bounded and release only what they own."""

from __future__ import annotations

import sys
import threading

import pytest

from .component_test_support import acquired_with_timeout, bounded_process


def test_timed_acquisition_failure_does_not_release_an_unowned_slot() -> None:
    # Bounded capacity zero also raises if cleanup releases an unowned slot.
    semaphore = threading.BoundedSemaphore(0)
    with (
        pytest.raises(AssertionError, match="not released within 0 seconds"),
        acquired_with_timeout(semaphore, timeout=0),
    ):
        pytest.fail("unavailable semaphore must not enter the protected body")


def test_timed_acquisition_releases_once_when_the_protected_assertion_fails() -> None:
    semaphore = threading.BoundedSemaphore(1)
    with pytest.raises(ValueError, match="protected failure"), acquired_with_timeout(semaphore, timeout=0):
        with pytest.raises(AssertionError, match="not released"), acquired_with_timeout(semaphore, timeout=0):
            pytest.fail("the outer scope must retain the only slot")
        raise ValueError("protected failure")
    with (
        acquired_with_timeout(semaphore, timeout=0),
        pytest.raises(AssertionError, match="not released"),
        acquired_with_timeout(semaphore, timeout=0),
    ):
        pytest.fail("cleanup must restore exactly one slot")


def test_bounded_process_reaps_the_real_child_when_the_test_body_fails() -> None:
    with (
        pytest.raises(ValueError, match="parent failure"),
        bounded_process([sys.executable, "-c", "import time; time.sleep(30)"]) as process,
    ):
        raise ValueError("parent failure")
    assert process.poll() is not None
