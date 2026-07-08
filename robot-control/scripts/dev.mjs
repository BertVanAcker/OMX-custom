import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import http from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = dirname(fileURLToPath(import.meta.url));
const robotControlDir = resolve(appDir, "..");
const repoRoot = resolve(robotControlDir, "..");

const python = existsSync(resolve(repoRoot, ".venv/bin/python"))
  ? resolve(repoRoot, ".venv/bin/python")
  : "python3";

function findSerialPort() {
  if (process.env.OMX_SERIAL_PORT) {
    return process.env.OMX_SERIAL_PORT;
  }

  try {
    const candidates = readdirSync("/dev")
      .filter((name) => name.startsWith("cu.usb") || name.startsWith("tty.usb"))
      .map((name) => `/dev/${name}`)
      .sort();
    return candidates.find((name) => name.startsWith("/dev/cu.")) || candidates[0] || "/dev/cu.usbmodem11401";
  } catch {
    return "/dev/cu.usbmodem11401";
  }
}

const serialPort = findSerialPort();
const apiPort = process.env.OMX_API_PORT || "8765";
const apiHost = process.env.OMX_API_HOST || "127.0.0.1";
const uiPort = process.env.OMX_UI_PORT || "5173";

const children = [];
let shuttingDown = false;

function checkApiAvailable(host, port) {
  return new Promise((resolveCheck) => {
    const request = http.get(
      {
        host,
        port,
        path: "/api/config",
        timeout: 600
      },
      (response) => {
        let data = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          data += chunk;
        });
        response.on("end", () => {
          if (response.statusCode !== 200) {
            resolveCheck({ available: false });
            return;
          }
          try {
            resolveCheck({ available: true, config: JSON.parse(data) });
          } catch {
            resolveCheck({ available: true });
          }
        });
      }
    );

    request.on("error", () => resolveCheck({ available: false }));
    request.on("timeout", () => {
      request.destroy();
      resolveCheck({ available: false });
    });
  });
}

function start(name, command, args, options) {
  const child = spawn(command, args, {
    stdio: "inherit",
    ...options
  });
  children.push({ name, child });

  child.on("exit", (code, signal) => {
    if (!shuttingDown && code !== 0) {
      console.error(`${name} exited with ${signal || code}`);
      shutdown(code || 1);
    }
  });

  return child;
}

function shutdown(code = 0) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const { child } of children) {
    if (!child.killed) {
      child.kill("SIGTERM");
    }
  }
  setTimeout(() => process.exit(code), 250);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

const apiStatus = await checkApiAvailable(apiHost, apiPort);
if (apiStatus.available) {
  const runningSerialPort = apiStatus.config?.serialPort;
  if (runningSerialPort && runningSerialPort !== serialPort) {
    console.error(`Robot API is already running on http://${apiHost}:${apiPort}, but it uses ${runningSerialPort}.`);
    console.error(`This launch wants to use ${serialPort}.`);
  } else {
    console.error(`Robot API is already running on http://${apiHost}:${apiPort}.`);
  }
  console.error("Stop the existing API process first so the server lifecycle stays tied to this app launch.");
  process.exit(2);
} else {
  console.log(`Starting robot API on http://${apiHost}:${apiPort}`);
  console.log(`Using serial port ${serialPort}`);
  start(
    "robot-api",
    python,
    [
      "robot_control_server/server.py",
      "--host",
      apiHost,
      "--port",
      apiPort,
      "--serial-port",
      serialPort
    ],
    { cwd: repoRoot }
  );
}

console.log(`Starting React app on http://127.0.0.1:${uiPort}`);
start("vite", "npm", ["run", "dev:ui", "--", "--port", uiPort, "--strictPort", "false"], {
  cwd: robotControlDir,
  env: {
    ...process.env,
    OMX_API_HOST: apiHost,
    OMX_API_PORT: apiPort
  }
});
