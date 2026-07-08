from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import sleep


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omx_control import create_rustypot_controller  # noqa: E402


DEFAULT_SERIAL_PORT = "/dev/cu.usbmodem11401"
DEFAULT_BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
POSITION_MODE = 3
TICKS_PER_REVOLUTION = 4096


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--delta", type=int, default=128, help="Raw tick offset to command from the current position.")
    parser.add_argument("--settle-seconds", type=float, default=1.0)
    parser.add_argument("--profile-velocity", type=int, default=50)
    parser.add_argument("--profile-acceleration", type=int, default=10)
    parser.add_argument("--restore-start", action="store_true")
    return parser.parse_args()


def read_position(controller, motor_id: int):
    try:
        return controller.read_raw_present_position(motor_id)
    except AttributeError:
        return controller.read_present_position(motor_id)


def unwrap_position(value) -> int:
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError(f"Expected one position value, got {value!r}")
        value = value[0]
    return int(value)


def main() -> int:
    args = parse_args()
    controller = create_rustypot_controller(
        controller_class="Xl330PyController",
        serial_port=args.serial_port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    )

    motor_id = args.id
    print(f"Probing XL330 ID {motor_id} on {args.serial_port} at {args.baudrate} baud")
    print("This script commands a small raw position move.")

    print(f"ping: {controller.ping(motor_id)}")
    print(f"model_number: {controller.read_model_number(motor_id)}")

    print("torque off")
    controller.write_torque_enable(motor_id, False)

    print(f"write operating mode: {POSITION_MODE}")
    controller.write_operating_mode(motor_id, POSITION_MODE)

    print(f"write profile acceleration: {args.profile_acceleration}")
    controller.write_profile_acceleration(motor_id, args.profile_acceleration)
    print(f"write profile velocity: {args.profile_velocity}")
    controller.write_profile_velocity(motor_id, args.profile_velocity)

    print("torque on")
    controller.write_torque_enable(motor_id, True)

    start = unwrap_position(read_position(controller, motor_id))
    target = (start + args.delta) % TICKS_PER_REVOLUTION
    print(f"start raw position: {start}")
    print(f"target raw position: {target}")

    print("write_raw_goal_position")
    controller.write_raw_goal_position(motor_id, target)
    print(f"read_raw_goal_position: {controller.read_raw_goal_position(motor_id)}")

    sleep(args.settle_seconds)
    after = unwrap_position(read_position(controller, motor_id))
    print(f"after raw position: {after}")
    print(f"raw position delta: {after - start}")

    if args.restore_start:
        print(f"restore raw position: {start}")
        controller.write_raw_goal_position(motor_id, start)
        sleep(args.settle_seconds)
        print(f"restored raw position: {unwrap_position(read_position(controller, motor_id))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
