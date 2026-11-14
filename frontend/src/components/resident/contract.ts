/**
 * Resident-facing slice of the lead's frozen wire contract (v1).
 *
 * Type-only re-export so this folder never owns a copy of the contract. When Person 2 installs
 * `frontend/src/recovery/contracts.ts`, change the path below to "../../recovery/contracts".
 */
export type * from "../../../../docs/recovery-handoffs/shared-contract";
