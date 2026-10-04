"""Tests for StorageManager, versioning, and project persistence."""
import pytest
from pathlib import Path
from storage.storage_manager import StorageManager

def test_storage_manager_spec_and_versions(tmp_path):
    sm = StorageManager(base_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    user_id = "test_user_123"
    project_id = "plasma_sword"

    # Save v1
    v1_data = {"project_name": "Plasma Sword", "damage": 18}
    sm.save_project_spec(user_id, project_id, version=1, spec_data=v1_data)

    # Save v2
    v2_data = {"project_name": "Plasma Sword", "damage": 30}
    sm.save_project_spec(user_id, project_id, version=2, spec_data=v2_data)

    # Verify both versions exist
    fetched_v1 = sm.get_project_spec(user_id, project_id, version=1)
    fetched_v2 = sm.get_project_spec(user_id, project_id, version=2)
    latest = sm.get_project_spec(user_id, project_id)

    assert fetched_v1["damage"] == 18
    assert fetched_v2["damage"] == 30
    assert latest["damage"] == 30
