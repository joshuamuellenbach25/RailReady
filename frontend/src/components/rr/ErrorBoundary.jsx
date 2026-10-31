import { Component } from "react";

export class ErrorBoundary extends Component {
  constructor(p) {
    super(p);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div data-testid="route-error-boundary" role="alert" className="m-6 rounded-lg border border-red-700 bg-white p-6">
        <h1 className="text-xl font-semibold text-red-700">This page failed to render</h1>
        <p className="mt-2 font-mono text-sm text-[#59636B]">{String(this.state.error?.message || this.state.error)}</p>
        <button data-testid="route-error-retry" className="mt-4 min-h-[44px] rounded-md border border-[#C5CCD2] bg-[#F3F4F4] px-4 font-bold"
          onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
