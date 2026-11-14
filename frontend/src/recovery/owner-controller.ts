import type { CaseEvent, CommandResult, OwnerCaseView, OwnerCommand } from "../../../docs/recovery-handoffs/shared-contract";

type Connection = "connected" | "reconnecting" | "expired";
type OwnerTransport = {
  get_case(case_id: string): Promise<OwnerCaseView>;
  command(case_id: string, command: OwnerCommand, idempotency_key: string): Promise<CommandResult>;
  subscribe_case(case_id: string, args: {
    after: number;
    on_event: (event: CaseEvent) => void;
    on_connection: (state: Connection) => void;
  }): () => void;
};

export interface OwnerCaseState {
  case_id: string | null;
  snapshot: OwnerCaseView | null;
  state: "loading" | "ready" | "error";
  error: string | null;
  busy: boolean;
  connection: Connection;
}

const message = (error: unknown) => error instanceof Error ? error.message : "This update could not be completed. Try again.";

/** Owns request races and confirmed state; components retain only interaction state. */
export class OwnerCaseController {
  private generation = 0;
  private unsubscribe: (() => void) | null = null;
  private last_command: { signature: string; key: string } | null = null;
  private disposed = false;
  private value: OwnerCaseState = {
    case_id: null, snapshot: null, state: "loading", error: null, busy: false, connection: "reconnecting",
  };

  constructor(private readonly transport: OwnerTransport,
              private readonly changed: (state: OwnerCaseState) => void,
              private readonly make_key: () => string = () => crypto.randomUUID()) {}

  get state(): OwnerCaseState { return this.value; }

  private update(patch: Partial<OwnerCaseState>) {
    if (this.disposed) return;
    this.value = { ...this.value, ...patch };
    this.changed(this.value);
  }

  async open(case_id: string): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.disposed = false;
    const generation = ++this.generation;
    this.last_command = null;
    this.update({ case_id, snapshot: null, state: "loading", error: null, busy: false, connection: "reconnecting" });
    try {
      const snapshot = await this.transport.get_case(case_id);
      if (generation !== this.generation || this.disposed) return;
      this.accept(case_id, snapshot);
      // One refresh loop per open case; bursts coalesce while a request is pending.
      let refreshing = false, dirty = false;
      const refresh = async () => {
        dirty = true;
        if (refreshing) return;
        refreshing = true;
        try {
          while (dirty && generation === this.generation && !this.disposed) {
            dirty = false;
            try {
              const next = await this.transport.get_case(case_id);
              if (generation === this.generation && !this.disposed) this.accept(case_id, next);
            } catch (error) {
              if (generation === this.generation) this.update({ error: message(error) });
            }
          }
        } finally { refreshing = false; }
      };
      this.unsubscribe = this.transport.subscribe_case(case_id, {
        after: snapshot.event_cursor,
        on_event: (event) => {
          if (generation === this.generation && event.case_id === case_id) void refresh();
        },
        on_connection: (connection) => {
          if (generation === this.generation) this.update({ connection,
            ...(connection === "expired" ? { error: "Your session expired. Sign in again." } : {}) });
        },
      });
    } catch (error) {
      if (generation === this.generation) this.update({ state: "error", error: message(error) });
    }
  }

  private accept(case_id: string, snapshot: OwnerCaseView) {
    if (snapshot.case.case_id !== case_id) throw new Error("The server returned a different case. Reload before continuing.");
    const current = this.value.snapshot;
    if (current && snapshot.case.case_revision < current.case.case_revision) return;
    this.update({ snapshot, state: "ready", error: null });
  }

  async command(command: OwnerCommand): Promise<CommandResult> {
    const case_id = this.value.case_id;
    if (!case_id || !this.value.snapshot || this.disposed) throw new Error("Load a case before applying an update.");
    if (this.value.busy) throw new Error("An update is already in progress.");
    const generation = this.generation;
    const signature = JSON.stringify([case_id, command]);
    const key = this.last_command?.signature === signature ? this.last_command.key : this.make_key();
    this.last_command = { signature, key };
    this.update({ busy: true, error: null });
    try {
      const receipt = await this.transport.command(case_id, command, key);
      if (generation === this.generation && !this.disposed) {
        this.last_command = null;
        // A failed refresh must not turn a confirmed command into a failed mutation.
        try {
          const snapshot = await this.transport.get_case(case_id);
          if (generation === this.generation && !this.disposed) this.accept(case_id, snapshot);
        } catch (error) {
          if (generation === this.generation) this.update({ error: `Update saved. ${message(error)}` });
        }
      }
      return receipt;
    } catch (error) {
      if (generation === this.generation) this.update({ error: message(error) });
      throw error;
    } finally {
      if (generation === this.generation) this.update({ busy: false });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.generation++;
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.last_command = null;
  }
}
