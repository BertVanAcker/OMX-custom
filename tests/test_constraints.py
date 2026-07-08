from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omx_control.constraints import AngleRange, degrees_to_radians, normalize_degrees, radians_to_degrees
from omx_control.joints import BASE, DEFAULT_JOINTS, JOINT2, JOINT3, JOINT4, load_joint_specs


class AngleRangeTests(unittest.TestCase):
    def test_non_wrapped_range(self) -> None:
        angle_range = AngleRange(90.0, 270.0)
        self.assertTrue(angle_range.contains(90.0))
        self.assertTrue(angle_range.contains(180.0))
        self.assertTrue(angle_range.contains(270.0))
        self.assertFalse(angle_range.contains(80.0))

    def test_wrapped_range(self) -> None:
        angle_range = AngleRange(278.0, 90.0)
        self.assertTrue(angle_range.contains(278.0))
        self.assertTrue(angle_range.contains(10.0))
        self.assertTrue(angle_range.contains(90.0))
        self.assertFalse(angle_range.contains(180.0))

    def test_full_circle_range(self) -> None:
        angle_range = AngleRange(360.0, 0.0)
        self.assertTrue(angle_range.contains(0.0))
        self.assertTrue(angle_range.contains(90.0))
        self.assertTrue(angle_range.contains(359.0))


class JointSpecTests(unittest.TestCase):
    def test_default_joints_load_from_yaml(self) -> None:
        self.assertEqual([joint.name for joint in DEFAULT_JOINTS], ["gripper", "base", "joint1", "joint2", "joint3", "joint4"])
        self.assertEqual(BASE.motor_id, 11)
        self.assertEqual(BASE.angle_range.start_degrees, 90.0)
        self.assertEqual(BASE.angle_range.end_degrees, 270.0)

    def test_gripper_named_positions_load_from_yaml(self) -> None:
        gripper = DEFAULT_JOINTS[0]

        self.assertEqual(gripper.name, "gripper")
        self.assertEqual(gripper.named_positions["open"], 250.0)
        self.assertEqual(gripper.named_positions["close"], 170.0)

    def test_home_values_are_valid(self) -> None:
        for joint in (BASE, JOINT2, JOINT3, JOINT4):
            joint.validate_home()

    def test_joint2_accepts_midrange_manual_position(self) -> None:
        JOINT2.validate(170.0)

    def test_joint3_accepts_midrange_manual_position(self) -> None:
        JOINT3.validate(170.0)

    def test_validates_invalid_angles(self) -> None:
        with self.assertRaises(ValueError):
            BASE.validate(30.0)

    def test_loads_custom_yaml_constraints(self) -> None:
        config_path = ROOT / "tests" / "fixtures" / "custom_joints.yaml"
        joints = {joint.name: joint for joint in load_joint_specs(config_path)}

        self.assertEqual(joints["base"].angle_range.start_degrees, 100.0)
        self.assertEqual(joints["base"].angle_range.end_degrees, 260.0)
        with self.assertRaises(ValueError):
            joints["base"].validate(90.0)


class ConversionTests(unittest.TestCase):
    def test_degree_radian_round_trip(self) -> None:
        self.assertAlmostEqual(radians_to_degrees(degrees_to_radians(123.0)), 123.0)

    def test_normalize(self) -> None:
        self.assertEqual(normalize_degrees(360.0), 0.0)
        self.assertEqual(normalize_degrees(-90.0), 270.0)


if __name__ == "__main__":
    unittest.main()
