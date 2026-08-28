export type NodeRecord = {
  id: string;
  name: string;
  status: string;
  health: string;
  actual_state: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  last_seen_at: string | null;
};

export type ProviderRecord = {
  id: string;
  node_id: string;
  service_id: string;
  health: string;
  capabilities: Record<string, unknown>;
  details: Record<string, unknown>;
  last_seen_at: string | null;
};

export type AlertRecord = {
  id: string;
  kind: string;
  severity: string;
  status: string;
  title: string;
  detail: string;
  dismissible: boolean;
  created_at: string;
};

export type AutomationStage = { name: string; position: number; status: string; detail: string };
export type AutomationRun = {
  id: string;
  automation_id: string;
  trigger: string;
  status: string;
  current_stage: string | null;
  stages: AutomationStage[];
};

export type Snapshot = {
  runtime?: {
    node_id: string;
    node_name: string;
    hardware_profile: "standard" | "pi-hardware";
  };
  nodes: NodeRecord[];
  providers: ProviderRecord[];
  alerts: AlertRecord[];
  runs: AutomationRun[];
  led: Record<string, { mode: string; intervalMs: number }>;
};
