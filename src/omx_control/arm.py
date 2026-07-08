from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .constraints import JointSpec, degrees_to_radians, radians_to_degrees
from .joints import DEFAULT_JOINTS


DYNAMIXEL_POSITION_MAX = 4095
DYNAMIXEL_DEGREES_MAX = 360.0
XL_CONTROLLER_CLASSES = {"Xl330PyController", "Xl430PyController"}
XL330_CONTROLLER_CLASS = "Xl330PyController"
POSITION_CONTROL_MODE = 3


class RustypotController(Protocol):
    def ping(self, motor_id: int):
        ...

    def write_torque_enable(self, motor_id: int, value: bool | int):
        ...

    def write_operating_mode(self, motor_id: int, value: int):
        ...

    def write_goal_position(self, motor_id: int, value: float | int):
        ...

    def write_raw_goal_position(self, motor_id: int, value: int):
        ...

    def read_present_position(self, motor_id: int) -> float | int | Sequence[float | int]:
        ...

    def read_raw_present_position(self, motor_id: int) -> float | int | Sequence[float | int]:
        ...


def _single_position_value(value: float | int | Sequence[float | int]) -> float:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"Expected a numeric position, got {value!r}")

    if isinstance(value, Sequence):
        if len(value) != 1:
            raise ValueError(f"Expected one position value, got {len(value)} values")
        return float(value[0])

    return float(value)


def _degrees_to_dynamixel_position(angle_degrees: float) -> int:
    if angle_degrees >= DYNAMIXEL_DEGREES_MAX:
        return DYNAMIXEL_POSITION_MAX
    normalized = angle_degrees % DYNAMIXEL_DEGREES_MAX
    position = round(normalized * (DYNAMIXEL_POSITION_MAX + 1) / DYNAMIXEL_DEGREES_MAX)
    return max(0, min(DYNAMIXEL_POSITION_MAX, position))


def _dynamixel_position_to_degrees(position: float) -> float:
    return position * DYNAMIXEL_DEGREES_MAX / (DYNAMIXEL_POSITION_MAX + 1)


def _uses_dynamixel_position_units(controller: RustypotController) -> bool:
    return getattr(controller, "controller_class", None) in XL_CONTROLLER_CLASSES


def _is_xl330_controller(controller: RustypotController) -> bool:
    return getattr(controller, "controller_class", None) == XL330_CONTROLLER_CLASS


@dataclass(slots=True)
class OMXArm:
    controllers_by_joint_name: dict[str, RustypotController]
    joints: dict[str, JointSpec]

    @classmethod
    def with_default_joints(
        cls,
        controller: RustypotController,
        joints: Sequence[JointSpec] = DEFAULT_JOINTS,
    ) -> "OMXArm":
        return cls(
            controllers_by_joint_name={joint.name: controller for joint in joints},
            joints={joint.name: joint for joint in joints},
        )

    @classmethod
    def with_default_joint_controllers(
        cls,
        controllers_by_joint_name: dict[str, RustypotController],
        joints: Sequence[JointSpec] = DEFAULT_JOINTS,
    ) -> "OMXArm":
        return cls(
            controllers_by_joint_name=controllers_by_joint_name,
            joints={joint.name: joint for joint in joints},
        )

    def joint(self, joint_name: str) -> JointSpec:
        try:
            return self.joints[joint_name]
        except KeyError as exc:
            available = ", ".join(sorted(self.joints))
            raise KeyError(f"Unknown joint {joint_name!r}. Available joints: {available}") from exc

    def controller_for_joint(self, joint_name: str) -> RustypotController:
        self.joint(joint_name)
        try:
            return self.controllers_by_joint_name[joint_name]
        except KeyError as exc:
            available = ", ".join(sorted(self.controllers_by_joint_name))
            raise KeyError(f"No controller configured for joint {joint_name!r}. Configured joints: {available}") from exc

    def move_joint(self, joint_name: str, angle_degrees: float):
        joint = self.joint(joint_name)
        joint.validate(angle_degrees)
        controller = self.controller_for_joint(joint_name)
        if _is_xl330_controller(controller):
            value = _degrees_to_dynamixel_position(angle_degrees)
            return controller.write_raw_goal_position(joint.motor_id, value)

        if _uses_dynamixel_position_units(controller):
            value = _degrees_to_dynamixel_position(angle_degrees)
        else:
            value = degrees_to_radians(angle_degrees)
        return controller.write_goal_position(joint.motor_id, value)

    def move_joint_home(self, joint_name: str):
        joint = self.joint(joint_name)
        return self.move_joint(joint_name, joint.home_degrees)

    def ping_joint(self, joint_name: str):
        joint = self.joint(joint_name)
        return self.controller_for_joint(joint_name).ping(joint.motor_id)

    def set_joint_torque(self, joint_name: str, enabled: bool):
        joint = self.joint(joint_name)
        return self.controller_for_joint(joint_name).write_torque_enable(joint.motor_id, enabled)

    def configure_joint_position_mode(self, joint_name: str):
        joint = self.joint(joint_name)
        controller = self.controller_for_joint(joint_name)
        if not _is_xl330_controller(controller):
            return None

        controller.write_torque_enable(joint.motor_id, False)
        return controller.write_operating_mode(joint.motor_id, POSITION_CONTROL_MODE)

    def read_joint_position(self, joint_name: str) -> float:
        joint = self.joint(joint_name)
        controller = self.controller_for_joint(joint_name)
        if _is_xl330_controller(controller):
            position = _single_position_value(controller.read_raw_present_position(joint.motor_id))
            return _dynamixel_position_to_degrees(position)

        position = _single_position_value(controller.read_present_position(joint.motor_id))
        if _uses_dynamixel_position_units(controller):
            return _dynamixel_position_to_degrees(position)
        return radians_to_degrees(position)

    def run_joint_sequence(
        self,
        joint_name: str,
        positions_degrees: list[float],
        settle_seconds: float = 0.75,
    ) -> None:
        for position in positions_degrees:
            self.move_joint(joint_name, position)
            if settle_seconds > 0.0:
                time.sleep(settle_seconds)
