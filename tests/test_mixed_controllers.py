from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
for path in (SRC, EXAMPLES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _shared import build_arm, resolve_yaml_steps  # noqa: E402
from omx_control import LazyRustypotController, OMXArm, degrees_to_radians  # noqa: E402


class FakeController:
    def __init__(self, present_position=None, controller_class: str | None = None) -> None:
        self.calls: list[tuple[str, int, float | int | None]] = []
        self.controller_class = controller_class
        self.present_position = 0.0 if present_position is None else present_position

    def ping(self, motor_id: int):
        self.calls.append(("ping", motor_id, None))

    def write_torque_enable(self, motor_id: int, value: bool):
        self.calls.append(("write_torque_enable", motor_id, value))

    def write_operating_mode(self, motor_id: int, value: int):
        self.calls.append(("write_operating_mode", motor_id, value))

    def write_goal_position(self, motor_id: int, angle_radians: float):
        self.calls.append(("write_goal_position", motor_id, angle_radians))

    def write_raw_goal_position(self, motor_id: int, value: int):
        self.calls.append(("write_raw_goal_position", motor_id, value))

    def read_present_position(self, motor_id: int) -> float:
        self.calls.append(("read_present_position", motor_id, None))
        return self.present_position

    def read_raw_present_position(self, motor_id: int) -> float:
        self.calls.append(("read_raw_present_position", motor_id, None))
        return self.present_position


class MixedControllerTests(unittest.TestCase):
    def test_examples_route_joints_to_matching_dynamixel_controllers(self) -> None:
        arm = build_arm(serial_port="/dev/null")

        self.assertIsInstance(arm.controller_for_joint("base"), LazyRustypotController)
        self.assertEqual(arm.controller_for_joint("base").controller_class, "Xl430PyController")
        self.assertEqual(arm.controller_for_joint("joint1").controller_class, "Xl430PyController")
        self.assertEqual(arm.controller_for_joint("joint2").controller_class, "Xl430PyController")
        self.assertEqual(arm.controller_for_joint("joint3").controller_class, "Xl330PyController")
        self.assertEqual(arm.controller_for_joint("joint4").controller_class, "Xl330PyController")
        self.assertEqual(arm.controller_for_joint("gripper").controller_class, "Xl330PyController")

    def test_build_arm_accepts_custom_joint_config(self) -> None:
        config_path = ROOT / "tests" / "fixtures" / "custom_joints.yaml"
        arm = build_arm(serial_port="/dev/null", joint_config_path=str(config_path))

        self.assertEqual(arm.joint("base").angle_range.start_degrees, 100.0)
        self.assertEqual(arm.joint("base").angle_range.end_degrees, 260.0)

    def test_example_steps_resolve_from_yaml_joint_config(self) -> None:
        config_path = ROOT / "tests" / "fixtures" / "custom_joints.yaml"
        arm = build_arm(serial_port="/dev/null", joint_config_path=str(config_path))

        self.assertEqual(
            resolve_yaml_steps(arm, "base", ["home", "max", "min"]),
            [("home", 180.0), ("max", 260.0), ("min", 100.0)],
        )

        self.assertEqual(
            resolve_yaml_steps(arm, "gripper", ["open", "close", "open"]),
            [("open", 250.0), ("close", 170.0), ("open", 250.0)],
        )

    def test_arm_uses_controller_configured_for_selected_joint(self) -> None:
        xl430 = FakeController()
        xl330 = FakeController()
        arm = OMXArm.with_default_joint_controllers(
            {
                "base": xl430,
                "joint1": xl430,
                "joint2": xl430,
                "joint3": xl330,
                "joint4": xl330,
                "gripper": xl330,
            }
        )

        arm.ping_joint("base")
        arm.ping_joint("joint3")

        self.assertEqual(xl430.calls, [("ping", 11, None)])
        self.assertEqual(xl330.calls, [("ping", 14, None)])

    def test_arm_enables_torque_on_selected_joint_controller(self) -> None:
        xl430 = FakeController()
        xl330 = FakeController()
        arm = OMXArm.with_default_joint_controllers(
            {
                "base": xl430,
                "joint1": xl430,
                "joint2": xl430,
                "joint3": xl330,
                "joint4": xl330,
                "gripper": xl330,
            }
        )

        arm.set_joint_torque("base", True)
        arm.set_joint_torque("joint3", True)

        self.assertEqual(xl430.calls, [("write_torque_enable", 11, True)])
        self.assertEqual(xl330.calls, [("write_torque_enable", 14, True)])

    def test_configure_position_mode_only_updates_xl330_joints(self) -> None:
        xl430 = FakeController(controller_class="Xl430PyController")
        xl330 = FakeController(controller_class="Xl330PyController")
        arm = OMXArm.with_default_joint_controllers(
            {
                "base": xl430,
                "joint1": xl430,
                "joint2": xl430,
                "joint3": xl330,
                "joint4": xl330,
                "gripper": xl330,
            }
        )

        arm.configure_joint_position_mode("base")
        arm.configure_joint_position_mode("joint3")

        self.assertEqual(xl430.calls, [])
        self.assertEqual(xl330.calls, [("write_torque_enable", 14, False), ("write_operating_mode", 14, 3)])

    def test_read_joint_position_accepts_scalar_rustypot_response(self) -> None:
        controller = FakeController(present_position=degrees_to_radians(123.0))
        arm = OMXArm.with_default_joints(controller)

        self.assertAlmostEqual(arm.read_joint_position("base"), 123.0)

    def test_read_joint_position_accepts_single_item_rustypot_response(self) -> None:
        controller = FakeController(present_position=[degrees_to_radians(123.0)])
        arm = OMXArm.with_default_joints(controller)

        self.assertAlmostEqual(arm.read_joint_position("base"), 123.0)

    def test_xl_controller_writes_raw_dynamixel_position(self) -> None:
        controller = FakeController(controller_class="Xl430PyController")
        arm = OMXArm.with_default_joints(controller)

        arm.move_joint("base", 180.0)

        self.assertEqual(controller.calls, [("write_goal_position", 11, 2048)])

    def test_xl330_controller_uses_raw_goal_position_write(self) -> None:
        controller = FakeController(controller_class="Xl330PyController")
        arm = OMXArm.with_default_joints(controller)

        arm.move_joint("joint3", 90.0)

        self.assertEqual(controller.calls, [("write_raw_goal_position", 14, 1024)])

    def test_xl_controller_reads_raw_dynamixel_position(self) -> None:
        controller = FakeController(present_position=[2048], controller_class="Xl430PyController")
        arm = OMXArm.with_default_joints(controller)

        self.assertAlmostEqual(arm.read_joint_position("base"), 180.0)

    def test_xl330_controller_uses_raw_present_position_read(self) -> None:
        controller = FakeController(present_position=[1024], controller_class="Xl330PyController")
        arm = OMXArm.with_default_joints(controller)

        self.assertAlmostEqual(arm.read_joint_position("joint3"), 90.0)
        self.assertEqual(controller.calls, [("read_raw_present_position", 14, None)])


if __name__ == "__main__":
    unittest.main()
