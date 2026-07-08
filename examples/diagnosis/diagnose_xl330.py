from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omx_control import create_rustypot_controller  # noqa: E402


DEFAULT_SERIAL_PORT = "/dev/cu.usbmodem11401"
DEFAULT_BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
DEFAULT_IDS = (14, 15, 16)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--ids", type=int, nargs="+", default=list(DEFAULT_IDS))
    parser.add_argument("--scan", action="store_true", help="Ping IDs 0-252 and diagnose only responders.")
    return parser.parse_args()


def read_optional(controller, method_name: str, motor_id: int):
    if not hasattr(controller, method_name):
        return "not supported"

    try:
        return getattr(controller, method_name)(motor_id)
    except Exception as exc:  # pragma: no cover - hardware diagnostic
        return f"error: {exc}"


def main() -> int:
    args = parse_args()
    controller = create_rustypot_controller(
        controller_class="Xl330PyController",
        serial_port=args.serial_port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    )

    print(f"XL330 diagnostic on {args.serial_port} at {args.baudrate} baud, timeout {args.timeout}s")
    print("This script only reads registers; it does not command movement.")

    ids = args.ids
    if args.scan:
        ids = []
        print("Scanning XL330 IDs 0-252...")
        for motor_id in range(253):
            try:
                controller.ping(motor_id)
            except Exception:
                continue
            ids.append(motor_id)
        print(f"Responding IDs: {ids if ids else 'none'}")

    for motor_id in ids:
        print(f"\nID {motor_id}")
        print(f"  ping: {read_optional(controller, 'ping', motor_id)}")
        print(f"  model_number: {read_optional(controller, 'read_model_number', motor_id)}")
        print(f"  operating_mode: {read_optional(controller, 'read_operating_mode', motor_id)}")
        print(f"  torque_enable: {read_optional(controller, 'read_torque_enable', motor_id)}")
        print(f"  raw_torque_enable: {read_optional(controller, 'read_raw_torque_enable', motor_id)}")
        print(f"  present_position: {read_optional(controller, 'read_present_position', motor_id)}")
        print(f"  raw_present_position: {read_optional(controller, 'read_raw_present_position', motor_id)}")
        print(f"  goal_position: {read_optional(controller, 'read_goal_position', motor_id)}")
        print(f"  raw_goal_position: {read_optional(controller, 'read_raw_goal_position', motor_id)}")
        print(f"  profile_velocity: {read_optional(controller, 'read_profile_velocity', motor_id)}")
        print(f"  profile_acceleration: {read_optional(controller, 'read_profile_acceleration', motor_id)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
