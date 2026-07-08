from __future__ import annotations

from dataclasses import dataclass
import unittest

from robot_control_server.server import RobotRuntime, TeachPoint


@dataclass(frozen=True)
class FakeJoint:
    name: str
    motor_id: int
    angle_range: object


@dataclass(frozen=True)
class FakeAngleRange:
    start_degrees: float
    end_degrees: float


class FakeController:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class FakeArm:
    def __init__(self) -> None:
        self.xl430 = FakeController("xl430")
        self.xl330 = FakeController("xl330")
        self.joints = {
            "base": FakeJoint("base", 11, FakeAngleRange(90.0, 270.0)),
            "joint1": FakeJoint("joint1", 12, FakeAngleRange(78.0, 260.0)),
            "joint3": FakeJoint("joint3", 14, FakeAngleRange(90.0, 266.0)),
        }
        self.controllers_by_joint_name = {
            "base": self.xl430,
            "joint1": self.xl430,
            "joint3": self.xl330,
        }
        self.moves: list[tuple[str, float]] = []

    def controller_for_joint(self, joint_name: str) -> FakeController:
        return self.controllers_by_joint_name[joint_name]

    def move_joint(self, joint_name: str, angle: float) -> None:
        self.moves.append((joint_name, angle))

    def joint(self, joint_name: str) -> FakeJoint:
        return self.joints[joint_name]


def build_runtime_for_test(arm: FakeArm) -> RobotRuntime:
    return RobotRuntime(
        arm=arm,  # type: ignore[arg-type]
        serial_port="/dev/null",
        baudrate=1_000_000,
        timeout=1.0,
        controller_class_by_joint={
            "base": "Xl430PyController",
            "joint1": "Xl430PyController",
            "joint3": "Xl330PyController",
        },
    )


class RobotRuntimeTests(unittest.TestCase):
    def test_prepare_controller_for_joint_closes_inactive_controller_once(self) -> None:
        arm = FakeArm()
        runtime = build_runtime_for_test(arm)

        runtime.prepare_controller_for_joint("joint3")

        self.assertEqual(arm.xl430.close_count, 1)
        self.assertEqual(arm.xl330.close_count, 0)

    def test_sequence_payload_serializes_slotted_teach_points(self) -> None:
        runtime = build_runtime_for_test(FakeArm())
        runtime.sequence.append(TeachPoint(label="Pick", positions={"base": 180.0}, created_at=123.0))

        self.assertEqual(
            runtime.sequence_payload(),
            [{"label": "Pick", "positions": {"base": 180.0}, "created_at": 123.0}],
        )

    def test_move_to_positions_smooth_interpolates_large_moves(self) -> None:
        arm = FakeArm()
        runtime = build_runtime_for_test(arm)

        end_positions = runtime.move_to_positions_smooth(
            {"base": 100.0},
            {"base": 120.0},
            max_step_degrees=5.0,
            step_seconds=0.0,
        )

        self.assertGreater(len(arm.moves), 1)
        self.assertEqual(arm.moves[-1], ("base", 120.0))
        self.assertEqual(end_positions["base"], 120.0)

    def test_close_closes_each_unique_controller_once(self) -> None:
        arm = FakeArm()
        runtime = build_runtime_for_test(arm)

        runtime.close()

        self.assertEqual(arm.xl430.close_count, 1)
        self.assertEqual(arm.xl330.close_count, 1)

    def test_clamp_positions_caps_out_of_range_values(self) -> None:
        runtime = build_runtime_for_test(FakeArm())

        clamped = runtime.clamp_positions({"base": 400.0, "joint1": 12.0, "joint3": 150.0})

        self.assertEqual(clamped["base"], 270.0)
        self.assertEqual(clamped["joint1"], 78.0)
        self.assertEqual(clamped["joint3"], 150.0)

    def test_move_joint_positions_uses_clamped_values(self) -> None:
        arm = FakeArm()
        runtime = build_runtime_for_test(arm)

        runtime.move_joint_positions({"base": 999.0, "joint1": -20.0})

        self.assertEqual(arm.moves, [("base", 270.0), ("joint1", 78.0)])


if __name__ == "__main__":
    unittest.main()
