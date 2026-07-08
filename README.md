# OMX Control

Small Python helpers for the Robotis OMX arm built on top of the Python bindings from rustypot.

The package keeps the robot-specific movement limits in one place and exposes one safe command path per joint.

## Install

```bash
pip install -e .
```

## Joint map

Joint IDs, limits, and home angles are loaded from `src/omx_control/config/joints.yaml`.

| Joint | Motor ID | Controller | Safe range | Home |
| --- | --- | --- | --- | --- |
| gripper | 16 | `Xl330PyController` | 180° to 250° | 250° |
| base | 11 | `Xl430PyController` | 90° to 270° | 180° |
| joint1 | 12 | `Xl430PyController` | 78° to 260° | 78° |
| joint2 | 13 | `Xl430PyController` | 110° to 278° | 278° |
| joint3 | 14 | `Xl330PyController` | 90° to 266° | 266° |
| joint4 | 15 | `Xl330PyController` | 360° to 0° | 178° |

## Example usage

The examples select the matching rustypot controller for each joint and move only one joint at a time. Movement targets are read from the YAML config: each script visits that joint's `home_degrees`, `min_degrees`, and/or `max_degrees`.

Run them from the repository root:

```bash
.venv/bin/python examples/basics/test_base.py --serial-port /dev/cu.usbmodem1401 --timeout 1.0
.venv/bin/python examples/basics/test_joint1.py --serial-port /dev/cu.usbmodem1401 --timeout 1.0
```

Pass `--joint-config path/to/joints.yaml` to use different joint angle constraints without editing Python code.
The YAML format is:

```yaml
joints:
  - name: gripper
    motor_id: 16
    min_degrees: 170.0
    max_degrees: 250.0
    home_degrees: 170.0
    open_degrees: 250.0
    close_degrees: 170.0
```

Any extra `*_degrees` keys become named movement targets for examples, so the gripper example uses `open` and `close` instead of `min` and `max`.

Open the example files and edit the `build_arm(...)` call if you need to change the serial port, baudrate, timeout, controller class, or joint config path.
You can also set `OMX_SERIAL_PORT` instead of passing `--serial-port` every time.

If a motor times out, check the serial port, power, baudrate, and motor ID. The examples ping the selected motor, configure XL330 joints for position mode, and enable torque before moving it; pass `--skip-ping`, `--skip-position-mode-config`, or `--skip-torque-enable` only if your controller setup does not support those preflight steps.

Diagnostic scripts live in `examples/diagnosis/`, for example:

```bash
.venv/bin/python examples/diagnosis/diagnose_xl330.py --serial-port /dev/cu.usbmodem1401
.venv/bin/python examples/diagnosis/probe_xl330_motion.py --serial-port /dev/cu.usbmodem1401 --id 14 --delta 128
```

## React control app

Start the React app and robot API together:

```bash
cd robot-control
npm run dev
```

Open `http://127.0.0.1:5173/`. The launcher starts the API at `http://127.0.0.1:8765/` and the Vite frontend at `http://127.0.0.1:5173/`.

The launcher auto-detects `/dev/cu.usb*` ports. Set `OMX_SERIAL_PORT`, `OMX_API_HOST`, or `OMX_API_PORT` before `npm run dev` to override the defaults.

The app has a manual page for joint and gripper actuation, plus a teaching/playback page. Entering teaching mode releases servo torque before positions are captured.

## Notes

This package accepts degrees at the OMX layer. It converts to the controller-specific units before sending commands: raw Dynamixel position ticks for XL330/XL430 joints and radians for controllers that use angular values.
