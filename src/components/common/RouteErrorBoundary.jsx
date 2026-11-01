import { Component } from 'react';

/** A page that fails to load or crashes shows this instead of a blank screen. */
export default class RouteErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('This page could not be shown.', error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="page-container" role="alert">
        <h1>This page couldn't load</h1>
        <p>Check your connection and try again.</p>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>Reload the page</button>
      </div>
    );
  }
}
