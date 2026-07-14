import { useTranslation } from "react-i18next";
import SmartToolPage from "./SmartToolPage";
import { FaultAnalysisJobList, type FaultAnalysisJob } from "../components/agentplayground/faultanalysis/FaultAnalysisJobList";
import { FaultAnalysisWorkspace } from "../components/agentplayground/faultanalysis/FaultAnalysisWorkspace";

export default function FaultAnalysisPage() {
  const { t } = useTranslation();

  return (
    <SmartToolPage<FaultAnalysisJob>
      title={t("nav.faultAnalysis", "故障分析")}
      showSidebar={false}
      JobListComponent={FaultAnalysisJobList}
      WorkspaceComponent={FaultAnalysisWorkspace}
    />
  );
}
