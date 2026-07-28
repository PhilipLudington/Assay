export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export type LogContext = Record<string, string | number | boolean | null>;

export interface Logger {
  log(level: LogLevel, event: string, context?: LogContext): void;
  child(context: LogContext): Logger;
}

/**
 * Structured logging only — every call site names an event and passes a flat
 * context bag, so log lines stay greppable in production.
 */
export class ConsoleLogger implements Logger {
  constructor(
    private readonly sink: (line: string) => void,
    private readonly base: LogContext = {},
  ) {}

  log(level: LogLevel, event: string, context: LogContext = {}): void {
    this.sink(JSON.stringify({ level, event, ...this.base, ...context }));
  }

  child(context: LogContext): Logger {
    return new ConsoleLogger(this.sink, { ...this.base, ...context });
  }
}

/** Turns an unknown thrown value into something a log context can carry. */
export function describeError(error: unknown): LogContext {
  if (error instanceof Error) {
    return { error: error.name, message: error.message };
  }
  return { error: 'unknown', message: String(error) };
}
