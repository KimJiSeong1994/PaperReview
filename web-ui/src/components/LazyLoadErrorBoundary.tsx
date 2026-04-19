import { Component } from 'react';
import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class LazyLoadErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('LazyLoadErrorBoundary:', error, info);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div role="alert" aria-live="assertive" className="lazy-error">
          <p>컴포넌트를 불러올 수 없습니다.</p>
          <button onClick={this.handleRetry}>다시 시도</button>
        </div>
      );
    }
    return this.props.children;
  }
}
