import { AudioWaveform, type LucideIcon } from "lucide-react";

export interface AgentPlaygroundAppDefinition {
  id: string;
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
}

export const AGENT_PLAYGROUND_APPS: AgentPlaygroundAppDefinition[] = [
  {
    id: "wave-record-parser",
    titleKey: "agentPlayground.apps.waveRecordParser.title",
    descriptionKey: "agentPlayground.apps.waveRecordParser.description",
    icon: AudioWaveform,
  },
];

export function getAgentPlaygroundApp(appId: string | undefined) {
  if (!appId) {
    return null;
  }
  return AGENT_PLAYGROUND_APPS.find((app) => app.id === appId) ?? null;
}
