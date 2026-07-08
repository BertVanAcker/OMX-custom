from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omx_control import OMXArm, create_lazy_rustypot_controller, load_joint_specs  # noqa: E402


DEFAULT_SERIAL_PORT = "/dev/cu.usbmodem1401"
DEFAULT_BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
XL430_CONTROLLER_CLASS = "Xl430PyController"
XL330_CONTROLLER_CLASS = "Xl330PyController"
DEFAULT_CONTROLLER_CLASS_BY_JOINT = {
    "base": XL430_CONTROLLER_CLASS,
    "joint1": XL430_CONTROLLER_CLASS,
    "joint2": XL430_CONTROLLER_CLASS,
    "joint3": XL330_CONTROLLER_CLASS,
    "joint4": XL330_CONTROLLER_CLASS,
    "gripper": XL330_CONTROLLER_CLASS,
}


def parse_arm_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--serial-port",
        default=os.environ.get("OMX_SERIAL_PORT", DEFAULT_SERIAL_PORT),
        help=f"Serial device path. Defaults to OMX_SERIAL_PORT or {DEFAULT_SERIAL_PORT}.",
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--joint-config",
        default=None,
        help="Path to a YAML file defining joint IDs and angle limits. Defaults to the packaged joints.yaml.",
    )
    parser.add_argument("--xl430-controller-class", default=XL430_CONTROLLER_CLASS)
    parser.add_argument("--xl330-controller-class", default=XL330_CONTROLLER_CLASS)
    parser.add_argument("--controller-class", default=None, help="Override the controller class for every joint.")
    parser.add_argument("--settle-seconds", type=float, default=0.75)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--skip-ping", action="store_true")
    parser.add_argument("--skip-position-mode-config", action="store_true")
    parser.add_argument("--skip-torque-enable", action="store_true")
    return parser.parse_args()


def available_serial_ports() -> list[str]:
    patterns = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/tty.usb*", "/dev/cu.usb*")
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(str(path) for path in Path("/").glob(pattern.removeprefix("/")))
    return sorted(set(ports))


def build_arm(
    serial_port: str = DEFAULT_SERIAL_PORT,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    controller_class_by_joint: dict[str, str] | None = None,
    joint_config_path: str | None = None,
) -> OMXArm:
    if not Path(serial_port).exists():
        candidates = available_serial_ports()
        candidate_text = ", ".join(candidates) if candidates else "none found"
        raise FileNotFoundError(
            f"Serial port {serial_port!r} does not exist. "
            f"Pass --serial-port with the correct device path. "
            f"Available USB-like ports: {candidate_text}"
        )

    joints = load_joint_specs(joint_config_path)
    joint_names = {joint.name for joint in joints}
    controller_class_by_joint = controller_class_by_joint or {
        joint_name: controller_class
        for joint_name, controller_class in DEFAULT_CONTROLLER_CLASS_BY_JOINT.items()
        if joint_name in joint_names
    }

    missing_controller_joints = sorted(joint_names - set(controller_class_by_joint))
    if missing_controller_joints:
        missing = ", ".join(missing_controller_joints)
        raise ValueError(f"No controller class configured for joint(s): {missing}")

    controllers_by_class = {
        controller_class: create_lazy_rustypot_controller(
            controller_class=controller_class,
            serial_port=serial_port,
            baudrate=baudrate,
            timeout=timeout,
        )
        for controller_class in sorted(set(controller_class_by_joint.values()))
    }
    controllers_by_joint_name = {
        joint_name: controllers_by_class[controller_class]
        for joint_name, controller_class in controller_class_by_joint.items()
        if joint_name in joint_names
    }
    return OMXArm.with_default_joint_controllers(controllers_by_joint_name, joints=joints)


def controller_classes_from_args(args: argparse.Namespace) -> dict[str, str]:
    if args.controller_class:
        return {joint_name: args.controller_class for joint_name in DEFAULT_CONTROLLER_CLASS_BY_JOINT}

    return {
        "base": args.xl430_controller_class,
        "joint1": args.xl430_controller_class,
        "joint2": args.xl430_controller_class,
        "joint3": args.xl330_controller_class,
        "joint4": args.xl330_controller_class,
        "gripper": args.xl330_controller_class,
    }


def run_isolated_joint_sequence(
    arm: OMXArm,
    joint_name: str,
    steps: Iterable[tuple[str, float]],
    *,
    settle_seconds: float = 0.75,
    retries: int = 2,
) -> None:
    joint = arm.joint(joint_name)
    print(f"Testing {joint.name} on motor ID {joint.motor_id}")
    print(f"Allowed range: {joint.angle_range.start_degrees} to {joint.angle_range.end_degrees} degrees")
    print(f"Home: {joint.home_degrees} degrees")

    for label, angle in steps:
        print(f"Moving to {label} ({angle} degrees)")

        attempts = max(1, retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                arm.move_joint(joint_name, angle)
                break
            except RuntimeError as exc:
                if attempt >= attempts:
                    raise RuntimeError(
                        f"Timed out moving {joint.name} motor ID {joint.motor_id} "
                        f"to {angle} degrees after {attempts} attempt(s): {exc}"
                    ) from exc
                print(f"  move attempt {attempt} failed: {exc}; retrying")

        if settle_seconds > 0.0:
            from time import sleep

            sleep(settle_seconds)

        try:
            present = arm.read_joint_position(joint_name)
            print(f"  present position: {present:.1f} degrees")
        except Exception as exc:  # pragma: no cover - hardware/runtime dependent
            print(f"  present position unavailable: {exc}")


def resolve_yaml_steps(arm: OMXArm, joint_name: str, step_names: Sequence[str]) -> list[tuple[str, float]]:
    joint = arm.joint(joint_name)
    values = {
        "home": joint.home_degrees,
        "min": joint.angle_range.start_degrees,
        "max": joint.angle_range.end_degrees,
        **joint.named_positions,
    }

    steps: list[tuple[str, float]] = []
    for step_name in step_names:
        try:
            steps.append((step_name, values[step_name]))
        except KeyError as exc:
            available = ", ".join(sorted(values))
            raise ValueError(f"Unknown YAML-derived step {step_name!r}. Available steps: {available}") from exc
    return steps


def run_example(joint_name: str, step_names: Sequence[str]) -> int:
    args = parse_arm_args()
    controller_class_by_joint = controller_classes_from_args(args)
    try:
        arm = build_arm(
            serial_port=args.serial_port,
            baudrate=args.baudrate,
            timeout=args.timeout,
            controller_class_by_joint=controller_class_by_joint,
            joint_config_path=args.joint_config,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    joint = arm.joint(joint_name)
    try:
        steps = resolve_yaml_steps(arm, joint_name, step_names)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    controller_class = controller_class_by_joint[joint_name]

    def _busy_hint(exc: BaseException) -> str:
        if isinstance(exc, OSError) and exc.errno in {errno.EBUSY, errno.EACCES, errno.EPERM}:
            return (
                f"Error: serial device {args.serial_port} is busy or inaccessible: {exc}. "
                "Stop the robot-control app/API (npm run dev or robot_control_server/server.py) and retry."
            )
        return f"Error: {exc}"

    print(f"Using {controller_class} for {joint.name} motor ID {joint.motor_id}")
    if not args.skip_ping:
        try:
            arm.ping_joint(joint_name)
        except (RuntimeError, OSError) as exc:
            if isinstance(exc, OSError):
                print(_busy_hint(exc), file=sys.stderr)
                return 3
            print(
                f"Error: motor ID {joint.motor_id} did not respond on {args.serial_port} "
                f"at {args.baudrate} baud within {args.timeout}s using {controller_class}: {exc}",
                file=sys.stderr,
            )
            return 3

    if not args.skip_position_mode_config:
        try:
            configured = arm.configure_joint_position_mode(joint_name)
            if configured is not None:
                print(f"Configured {joint.name} motor ID {joint.motor_id} for position mode")
        except (RuntimeError, OSError) as exc:
            if isinstance(exc, OSError):
                print(_busy_hint(exc), file=sys.stderr)
                return 3
            print(
                f"Error: could not configure position mode for motor ID {joint.motor_id} on "
                f"{args.serial_port} using {controller_class}: {exc}",
                file=sys.stderr,
            )
            return 3

    if not args.skip_torque_enable:
        try:
            print(f"Enabling torque for {joint.name} motor ID {joint.motor_id}")
            arm.set_joint_torque(joint_name, True)
        except (RuntimeError, OSError) as exc:
            if isinstance(exc, OSError):
                print(_busy_hint(exc), file=sys.stderr)
                return 3
            print(
                f"Error: could not enable torque for motor ID {joint.motor_id} on {args.serial_port} "
                f"using {controller_class}: {exc}",
                file=sys.stderr,
            )
            return 3

    try:
        run_isolated_joint_sequence(
            arm,
            joint_name,
            steps,
            settle_seconds=args.settle_seconds,
            retries=args.retries,
        )
    except (RuntimeError, OSError) as exc:
        if isinstance(exc, OSError):
            print(_busy_hint(exc), file=sys.stderr)
            return 3
        print(
            f"Error: {exc}\n"
            f"Port: {args.serial_port}, baudrate: {args.baudrate}, timeout: {args.timeout}s, "
            f"controller: {controller_class}",
            file=sys.stderr,
        )
        return 3

    return 0
