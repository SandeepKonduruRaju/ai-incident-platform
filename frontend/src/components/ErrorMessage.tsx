import { ApiError } from '../api/client';
import styles from './ErrorMessage.module.css';

/** Central error display: the API's message (ProblemDetail detail), retry hint for 429, and the request id. */
export function ErrorMessage({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError ? error : null;
  const message = apiError ? apiError.message : 'Something went wrong.';
  const title = apiError?.problem?.title;
  return (
    <div role="alert" className={styles.error}>
      {title && <strong>{title}. </strong>}
      {message}
      {apiError?.status === 429 && apiError.retryAfterSeconds !== undefined && (
        <> Try again in {apiError.retryAfterSeconds} s.</>
      )}
      {apiError?.requestId && <div className={styles.requestId}>Request id: <code>{apiError.requestId}</code></div>}
    </div>
  );
}
