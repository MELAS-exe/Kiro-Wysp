import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** A render error must not leave a blank page: say what happened and offer a reload. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Panel render error", error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" style={{ padding: 24 }}>
        <p>
          <strong>The Panel hit an error and stopped drawing.</strong>
        </p>
        <p className="muted">{this.state.error.message}</p>
        <button className="primary" onClick={() => location.reload()}>
          Reload the Panel
        </button>
      </div>
    );
  }
}
