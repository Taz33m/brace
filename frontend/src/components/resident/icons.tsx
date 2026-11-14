/**
 * One authored icon set for the resident screens: 24px grid, 1.75 stroke, round joins.
 * Decorative by default (aria-hidden); pass a title only when the icon stands alone.
 */
import type { ReactNode, SVGProps } from "react";

type IconProps = Omit<SVGProps<SVGSVGElement>, "children"> & { size?: number; title?: string };

function Icon({ size = 24, title, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const IconBack = (p: IconProps) => <Icon {...p}><path d="M15 5l-7 7 7 7" /></Icon>;
export const IconChevron = (p: IconProps) => <Icon {...p}><path d="M9 5l7 7-7 7" /></Icon>;
export const IconCheck = (p: IconProps) => <Icon {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>;
export const IconClose = (p: IconProps) => <Icon {...p}><path d="M6 6l12 12M18 6L6 18" /></Icon>;
export const IconAlert = (p: IconProps) => <Icon {...p}><path d="M12 3.5L2.5 20h19L12 3.5z" /><path d="M12 10v4.5" /><path d="M12 17.25v.01" /></Icon>;
export const IconInfo = (p: IconProps) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5" /><path d="M12 7.75v.01" /></Icon>;
export const IconClock = (p: IconProps) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
export const IconRetry = (p: IconProps) => <Icon {...p}><path d="M4 12a8 8 0 0 1 13.66-5.66L20 8.5" /><path d="M20 4v4.5h-4.5" /><path d="M20 12a8 8 0 0 1-13.66 5.66L4 15.5" /><path d="M4 20v-4.5h4.5" /></Icon>;
export const IconWifiOff = (p: IconProps) => <Icon {...p}><path d="M3 3l18 18" /><path d="M8.5 16.5a5 5 0 0 1 7 0" /><path d="M5 13a10 10 0 0 1 4.2-2.5" /><path d="M14.8 10.5A10 10 0 0 1 19 13" /><path d="M2 9.5a15 15 0 0 1 4.5-2.9" /><path d="M10.5 5.6A15 15 0 0 1 22 9.5" /><path d="M12 20v.01" /></Icon>;
export const IconLock = (p: IconProps) => <Icon {...p}><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /></Icon>;

/* Report categories (contract: water | roof | smoke_or_fire | power_or_access | other). */
export const IconWater = (p: IconProps) => <Icon {...p}><path d="M12 3.5c3.5 4.3 6 7.6 6 10.5a6 6 0 0 1-12 0c0-2.9 2.5-6.2 6-10.5z" /><path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5" /></Icon>;
export const IconRoof = (p: IconProps) => <Icon {...p}><path d="M2.5 11.5L12 4l9.5 7.5" /><path d="M5 9.5V20h14V9.5" /><path d="M10 13.5l1.5 2-1 2.5" /></Icon>;
export const IconSmoke = (p: IconProps) => <Icon {...p}><path d="M12 21c-3.6 0-6-2.4-6-5.6 0-2.7 1.8-4.5 3.2-6 .3 1.6 1.1 2.6 2.1 3.1-.4-3.2.9-6.3 3.7-8.5.2 3 1.4 4.6 2.6 6.2 1.1 1.5 2.4 3 2.4 5.2 0 3.2-2.4 5.6-6 5.6z" /></Icon>;
export const IconPower = (p: IconProps) => <Icon {...p}><path d="M13 2.5L5 13.5h6l-1 8 8-11h-6l1-8z" /></Icon>;
export const IconOther = (p: IconProps) => <Icon {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="3" /><path d="M8 12h.01M12 12h.01M16 12h.01" strokeWidth={2.5} /></Icon>;

/* Support categories (contract: housing | access | communication | other). */
export const IconHousing = (p: IconProps) => <Icon {...p}><path d="M3 20.5h18" /><path d="M4.5 20.5V9.5L12 4l7.5 5.5v11" /><path d="M9.5 20.5v-6h5v6" /></Icon>;
export const IconAccess = (p: IconProps) => <Icon {...p}><circle cx="8" cy="12" r="3.5" /><path d="M11.5 12H21" /><path d="M17.5 12v3" /><path d="M20.5 12v2" /></Icon>;
export const IconChat = (p: IconProps) => <Icon {...p}><path d="M4 5.5h16v10H9l-5 4v-14z" /><path d="M8 9.5h8M8 12.5h5" /></Icon>;

/* Home actions + capture. */
export const IconReport = (p: IconProps) => <Icon {...p}><path d="M6 3.5h8.5L19 8v12.5H6v-17z" /><path d="M14 3.5V8.5h5" /><path d="M12.5 11v4" /><path d="M12.5 17.75v.01" /></Icon>;
export const IconSupport = (p: IconProps) => <Icon {...p}><path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" /></Icon>;
export const IconUpdates = (p: IconProps) => <Icon {...p}><path d="M6 9.5a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15.5 6 9.5z" /><path d="M10 20a2.2 2.2 0 0 0 4 0" /></Icon>;
export const IconCamera = (p: IconProps) => <Icon {...p}><path d="M3.5 8.5h3.2l1.6-2.5h7.4l1.6 2.5h3.2v11h-17v-11z" /><circle cx="12" cy="13.5" r="3.5" /></Icon>;
export const IconImage = (p: IconProps) => <Icon {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><circle cx="9" cy="9.5" r="1.5" /><path d="M20.5 15.5l-5-5-9 9" /></Icon>;
export const IconMic = (p: IconProps) => <Icon {...p}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0" /><path d="M12 17.5V21" /></Icon>;
export const IconStop = (p: IconProps) => <Icon {...p}><rect x="7" y="7" width="10" height="10" rx="1.5" /></Icon>;
export const IconPin = (p: IconProps) => <Icon {...p}><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></Icon>;
