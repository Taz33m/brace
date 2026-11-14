// Generic, domain-free primitives for the Brace recovery workspace.
// Importing this barrel loads the scoped styles once; every style lives under `.brace-recovery`.
import "./recovery-ui.css";

export { Panel } from "./Panel";
export type { PanelProps } from "./Panel";
export { SegmentedControl } from "./SegmentedControl";
export type { SegmentedControlProps, SegmentedOption } from "./SegmentedControl";
export { Tabs, TabPanel, tabId, tabPanelId } from "./Tabs";
export type { TabsProps, TabPanelProps, TabItem } from "./Tabs";
export { StatusMark } from "./StatusMark";
export type { StatusMarkProps, StatusTone, StatusShape, ToneMark } from "./StatusMark";
export { EvidenceBadge } from "./EvidenceBadge";
export type { EvidenceBadgeProps } from "./EvidenceBadge";
export { RangeTrack, RangeRow, RangeList, rangeDomain } from "./RangeDisplay";
export type { RangeTrackProps, RangeRowProps } from "./RangeDisplay";
export { EmptyState } from "./EmptyState";
export type { EmptyStateProps } from "./EmptyState";
export { ChangedBanner } from "./ChangedBanner";
export type { ChangedBannerProps, ChangedTone } from "./ChangedBanner";
export { InlineError } from "./InlineError";
export type { InlineErrorProps } from "./InlineError";
export { Button } from "./Button";
export type { ButtonProps, ButtonVariant } from "./Button";
export { FixtureBanner } from "./FixtureBanner";
