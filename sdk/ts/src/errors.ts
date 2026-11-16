/** JSON-RPC and Wysp contract error codes (see .kiro/steering/adapter-contract.md). */
export const ErrorCode = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
  NOT_SUPPORTED: -32010,
  ACTION_NOT_FOUND: -32011,
  TARGET_NOT_FOUND: -32012,
  PRECONDITION_FAILED: -32013,
  EXECUTION_FAILED: -32014,
  UNDO_UNAVAILABLE: -32015,
  TIMEOUT: -32016,
  BUSY: -32017,
  INCOMPATIBLE_VERSION: -32018,
  UNAUTHORIZED: -32019,
} as const;

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode];

/** An error that is sent back to the Core as a JSON-RPC error. Put details in `data`, never stack traces. */
export class WyspError extends Error {
  readonly code: number;
  readonly data?: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "WyspError";
    this.code = code;
    this.data = data;
  }

  toJSON(): { code: number; message: string; data?: unknown } {
    return this.data === undefined
      ? { code: this.code, message: this.message }
      : { code: this.code, message: this.message, data: this.data };
  }
}
