/** Loads the page again after a failed request. */
export default function RetryButton() {
  return (
    <button type="button" className="btn btn-outline" onClick={() => window.location.reload()}>
      Try again
    </button>
  );
}
