import { withBasePath } from "./basePath";

export const BRAND_NAME = "皖电智尊保";
export const BRAND_THEME_STORAGE_KEY = "wave-parser-theme";
const BRAND_ASSET_VERSION = "20260430a";
const brandAsset = (path: string) => `${withBasePath(path)}?v=${BRAND_ASSET_VERSION}`;

export const BRAND_ASSETS = {
  icon: brandAsset("/icon.png"),
  logo: brandAsset("/logo.png"),
  logoLarge: brandAsset("/brand/ai-logo-big.png"),
  logoSmall: brandAsset("/brand/ai-logo.png"),
  sidebarLogo: brandAsset("/brand/logo-side.png"),
  sidebarExpand: brandAsset("/brand/show-side.png"),
  sidebarCollapse: brandAsset("/brand/hidden-dark-side.png"),
  background: brandAsset("/brand/background.png"),
  tipsBackground: brandAsset("/brand/tips-bg.png"),
  askIcon: brandAsset("/brand/chat-ask-icon.png"),
  robot: brandAsset("/brand/chat-robot-icon.png"),
  followUps: brandAsset("/brand/followUps.png"),
  font: brandAsset("/assets/fonts/syhtjzt.otf"),
} as const;
