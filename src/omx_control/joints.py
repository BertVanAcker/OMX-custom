from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from .constraints import AngleRange, JointSpec


DEFAULT_JOINT_CONFIG = resources.files("omx_control").joinpath("config/joints.yaml")


def _parse_scalar(value: str) -> str | int | float:
    value = value.strip()
    if not value:
        return ""

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value.strip("\"'")


def _load_yaml_without_dependency(path: str | Path) -> dict[str, Any]:
    joints: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    with Path(path).open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue

            stripped = line.strip()
            if stripped == "joints:":
                continue

            if stripped.startswith("- "):
                if current is not None:
                    joints.append(current)
                current = {}
                stripped = stripped[2:].strip()
                if not stripped:
                    continue

            if ":" not in stripped:
                raise ValueError(f"Unsupported YAML line in {path}: {raw_line.rstrip()!r}")

            if current is None:
                raise ValueError(f"Expected a joint list item before {raw_line.rstrip()!r}")

            key, value = stripped.split(":", 1)
            current[key.strip()] = _parse_scalar(value)

    if current is not None:
        joints.append(current)

    return {"joints": joints}


def _load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return _load_yaml_without_dependency(path)

    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in joint config {path}")
    return data


def _joint_from_config(entry: dict[str, Any]) -> JointSpec:
    try:
        name = str(entry["name"])
        motor_id = int(entry["motor_id"])
        min_degrees = float(entry["min_degrees"])
        max_degrees = float(entry["max_degrees"])
        home_degrees = float(entry["home_degrees"])
    except KeyError as exc:
        raise ValueError(f"Missing required joint config key: {exc.args[0]}") from exc

    joint = JointSpec(
        name=name,
        motor_id=motor_id,
        angle_range=AngleRange(min_degrees, max_degrees),
        home_degrees=home_degrees,
    )
    joint.validate_home()
    return joint


def load_joint_specs(config_path: str | Path | None = None) -> tuple[JointSpec, ...]:
    path = Path(config_path) if config_path is not None else Path(str(DEFAULT_JOINT_CONFIG))
    data = _load_yaml(path)
    raw_joints = data.get("joints")
    if not isinstance(raw_joints, list):
        raise ValueError(f"Expected 'joints' list in joint config {path}")

    joints = tuple(_joint_from_config(entry) for entry in raw_joints)
    if not joints:
        raise ValueError(f"Joint config {path} does not define any joints")

    names = [joint.name for joint in joints]
    if len(names) != len(set(names)):
        raise ValueError(f"Joint config {path} contains duplicate joint names")

    return joints


DEFAULT_JOINTS = load_joint_specs()
_JOINTS_BY_NAME = {joint.name: joint for joint in DEFAULT_JOINTS}

GRIPPER = _JOINTS_BY_NAME["gripper"]
BASE = _JOINTS_BY_NAME["base"]
JOINT1 = _JOINTS_BY_NAME["joint1"]
JOINT2 = _JOINTS_BY_NAME["joint2"]
JOINT3 = _JOINTS_BY_NAME["joint3"]
JOINT4 = _JOINTS_BY_NAME["joint4"]
