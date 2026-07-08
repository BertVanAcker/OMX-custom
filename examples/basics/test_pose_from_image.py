from __future__ import annotations

from pathlib import Path
import sys


EXAMPLES = Path(__file__).resolve().parents[1]
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

from _shared import build_arm, controller_classes_from_args, parse_arm_args  # noqa: E402


REQUESTED_POSE_DEGREES = {
    "gripper": 254.6,
    "base": 176.0,
    "joint1": 127.5,
    "joint2": 152.3,
    "joint3": 275.4,
    "joint4": 179.2,
}


def _normalize_degrees(angle: float) -> float:
    return angle % 360.0


def _circular_distance(a: float, b: float) -> float:
    diff = abs(_normalize_degrees(a) - _normalize_degrees(b))
    return min(diff, 360.0 - diff)


def _project_angle(joint_name: str, requested: float, start: float, end: float) -> float:
    start_n = _normalize_degrees(start)
    end_n = _normalize_degrees(end)
    requested_n = _normalize_degrees(requested)

    if start_n <= end_n:
        return max(start_n, min(end_n, requested_n))

    # Wrapped range (for example 300..60): inside if >= start OR <= end.
    if requested_n >= start_n or requested_n <= end_n:
        return requested_n

    return start_n if _circular_distance(requested_n, start_n) <= _circular_distance(requested_n, end_n) else end_n


def main() -> int:
    args = parse_arm_args()
    controller_class_by_joint = controller_classes_from_args(args)

    arm = build_arm(
        serial_port=args.serial_port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        controller_class_by_joint=controller_class_by_joint,
        joint_config_path=args.joint_config,
    )

    ordered_joints = ["base", "joint1", "joint2", "joint3", "joint4", "gripper"]

    for joint_name in ordered_joints:
        arm.ping_joint(joint_name)
        arm.configure_joint_position_mode(joint_name)
        arm.set_joint_torque(joint_name, True)

    safe_pose: dict[str, float] = {}
    for joint_name in ordered_joints:
        requested = REQUESTED_POSE_DEGREES[joint_name]
        joint = arm.joint(joint_name)
        start = joint.angle_range.start_degrees
        end = joint.angle_range.end_degrees
        target = _project_angle(joint_name, requested, start, end)
        safe_pose[joint_name] = target
        if abs(target - requested) > 1e-9:
            print(
                f"Adjusted {joint_name} from {requested:.1f} deg to {target:.1f} deg "
                f"to fit range {start}..{end}"
            )

    # Direct per-joint commands (no run_example helper).
    arm.move_joint("base", safe_pose["base"])
    arm.move_joint("joint1", safe_pose["joint1"])
    arm.move_joint("joint2", safe_pose["joint2"])
    arm.move_joint("joint3", safe_pose["joint3"])
    arm.move_joint("joint4", safe_pose["joint4"])
    arm.move_joint("gripper", safe_pose["gripper"])

    print("Target pose command sent.")
    for joint_name in ordered_joints:
        present = arm.read_joint_position(joint_name)
        print(f"  {joint_name}: {present:.1f} deg")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
