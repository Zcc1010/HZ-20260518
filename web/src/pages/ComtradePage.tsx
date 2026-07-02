import { useEffect, useRef } from "react";

export default function ComtradePage() {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const sendConfig = () => {
      fetch("/protection/api/providers/comtrade-config")
        .then((res) => res.json())
        .then((config) => {
          if (config.api_key) {
            iframe.contentWindow?.postMessage(
              { type: "nanobot-llm-config", config },
              "*"
            );
          }
        })
        .catch(() => {});
    };

    iframe.addEventListener("load", sendConfig);
    return () => iframe.removeEventListener("load", sendConfig);
  }, []);

  return (
    <iframe
      ref={iframeRef}
      src="/protection/comtrade-app/index.html"
      style={{ width: "100%", height: "100vh", border: "none" }}
      title="故障录波简报生成器"
    />
  );
}
