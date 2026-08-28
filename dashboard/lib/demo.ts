export type DemoProfile = "mac" | "pi";

export type DemoNode = {
  name: string;
  role: string;
  status: "online" | "standby" | "offline";
  detail: string;
};

export type DemoService = {
  name: string;
  capability: string;
  status: "healthy" | "ready" | "observing";
};

export type DemoScenario = {
  id: DemoProfile;
  label: string;
  profile: "standard" | "pi-hardware";
  headline: string;
  summary: string;
  nodes: DemoNode[];
  services: DemoService[];
  telemetryTitle: string;
  telemetryDetail: string;
  prerequisites: string[];
  environment: string;
  launch: string;
  verify: string;
  warning?: string;
};

export type DemoModule = {
  title: string;
  label: string;
  summary: string;
  flow: string;
  add: string;
  files: string[];
};

export const demoScenarios: Record<DemoProfile, DemoScenario> = {
  mac: {
    id: "mac",
    label: "Mac Standard",
    profile: "standard",
    headline: "Portable Control Plane on your Mac",
    summary: "Runs the core platform locally, while the Mac Node reports capabilities and accepts allowlisted commands.",
    nodes: [
      { name: "Zachary's MacBook Pro", role: "Control Plane + Mac Node", status: "online", detail: "Dashboard, API, MQTT, PostgreSQL, and Mac capabilities" },
      { name: "Home Pi", role: "Remote hardware", status: "standby", detail: "Pi-only services remain deliberately stopped" },
    ],
    services: [
      { name: "Control Plane", capability: "Desired State + API", status: "healthy" },
      { name: "Mac Node", capability: "Notifications + local AI", status: "healthy" },
      { name: "LM Studio", capability: "Text generation", status: "ready" },
    ],
    telemetryTitle: "Hardware boundary",
    telemetryDetail: "Arduino and webcam services are intentionally absent from the standard profile.",
    prerequisites: ["Docker Desktop running", "A private Tailnet connection", "Mac Node MQTT credential in Keychain"],
    environment: "HOMEPLATFORM_NODE_ID=macbook\nHOMEPLATFORM_NODE_NAME=Zachary's MacBook Pro\nHOMEPLATFORM_HARDWARE_PROFILE=standard\nMQTT_BIND_IP=127.0.0.1",
    launch: "docker compose --env-file .env.mac up -d --build",
    verify: "tailscale serve --bg 3000\ntailscale serve status",
  },
  pi: {
    id: "pi",
    label: "Pi Hardware",
    profile: "pi-hardware",
    headline: "Home Control Plane with attached hardware",
    summary: "Adds the kiosk controller, private webcam ingress, and media monitoring to the same core platform.",
    nodes: [
      { name: "Home Pi", role: "Control Plane + kiosk", status: "online", detail: "Owns the Arduino, webcam, and hardware services" },
      { name: "MacBook", role: "Remote node", status: "online", detail: "Reports Mac capabilities over authenticated MQTT" },
    ],
    services: [
      { name: "Kiosk Controller", capability: "Arduino LEDs + joystick", status: "healthy" },
      { name: "go2rtc", capability: "Private Brio stream", status: "healthy" },
      { name: "Media Controller", capability: "Stream health", status: "observing" },
    ],
    telemetryTitle: "Physical services",
    telemetryDetail: "The kiosk and webcam are detected through the Control Plane; the Demo Lab never drives physical inputs.",
    prerequisites: ["Raspberry Pi with Docker", "Arduino path configured", "Logitech Brio path configured", "A private Tailnet connection"],
    environment: "HOMEPLATFORM_NODE_ID=pi-control-plane\nHOMEPLATFORM_NODE_NAME=Home Pi\nHOMEPLATFORM_HARDWARE_PROFILE=pi-hardware",
    launch: "docker compose --profile pi-hardware up -d --build",
    verify: "tailscale serve --bg 3000\ntailscale serve status",
    warning: "Enable this profile only on the Pi. It requests Linux USB serial and video devices.",
  },
};

export const demoModules: DemoModule[] = [
  { title: "Control Plane", label: "Core", summary: "Owns versioned Desired State, durable history, alerts, and the browser-facing API.", flow: "YAML configuration → validation → PostgreSQL + retained MQTT → Dashboard read model", add: "Add a typed configuration record, validate it at startup, then project its actual state into the snapshot.", files: ["config/*.yaml", "control-plane/app/configuration.py", "control-plane/app/core.py"] },
  { title: "Mac Node", label: "Node", summary: "Reports local capabilities and executes a small, durable allowlist of macOS commands.", flow: "Mac probe → MQTT actual state → Control Plane projection → command result", add: "Add a capability report and one explicitly allowlisted command handler; preserve idempotent command results.", files: ["nodes/mac/homeplatform_node/service.py", "config/nodes.yaml", "deploy/mac/INSTALL.md"] },
  { title: "Pi Hardware", label: "Hardware", summary: "Keeps Arduino and USB-video access behind an explicit Pi-only Compose profile.", flow: "Pi hardware profile → controller → MQTT events + alert LEDs → Dashboard telemetry", add: "Create a controller that owns one hardware boundary, declare its device in configuration, and add it only to the Pi profile.", files: ["docker-compose.yml", "control-plane/devices/kiosk/service.py", "config/devices.yaml"] },
  { title: "Home Assistant", label: "Integration", summary: "Executes narrow, configured actions through a stored integration credential rather than the browser.", flow: "Dashboard action → API validation → Home Assistant client → configured entity", add: "Declare the integration and a device target, then expose only the specific validated actions the integration supports.", files: ["config/integrations.yaml", "config/devices.yaml", "control-plane/app/home_assistant.py"] },
  { title: "Automations", label: "Workflow", summary: "Runs durable staged work and returns its progress to the Dashboard.", flow: "Manual or scheduled trigger → Automation Run → stages → live snapshot", add: "Define a configuration entry, give every stage observable status, and make retries safe to repeat.", files: ["config/automations.yaml", "control-plane/app/automation_controller.py", "control-plane/app/models.py"] },
  { title: "Private Media", label: "Service", summary: "Makes webcam health visible without exposing the stream through the Dashboard or public internet.", flow: "go2rtc private ingress → media controller health → service provider record → telemetry", add: "Monitor the service through an internal API, report capabilities over MQTT, and keep its ports private.", files: ["infrastructure/go2rtc/go2rtc.yaml", "control-plane/app/media_controller.py", "config/services.yaml"] },
];
