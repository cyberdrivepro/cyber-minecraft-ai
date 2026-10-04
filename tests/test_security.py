"""Tests for security sanitization and path traversal prevention."""
import pytest
from pathlib import Path
from core.security import validate_safe_path
from core.exceptions import SecurityError

def test_validate_safe_path_valid(tmp_path):
    safe_target = tmp_path / "user1" / "project1" / "data.json"
    safe_target.parent.mkdir(parents=True)
    safe_target.touch()

    res = validate_safe_path(tmp_path, safe_target)
    assert res == safe_target.resolve()

def test_validate_safe_path_traversal(tmp_path):
    traversal_target = tmp_path / ".." / "secret.txt"
    with pytest.raises(SecurityError):
        validate_safe_path(tmp_path, traversal_target)
