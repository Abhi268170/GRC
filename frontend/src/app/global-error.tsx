"use client";

// Shown when the root layout itself fails, so it can't rely on the app's styles or providers.
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh", margin: 0 }}>
        <div style={{ textAlign: "center", padding: 24 }}>
          <h1 style={{ fontSize: 24, marginBottom: 8 }}>Something went wrong</h1>
          <p style={{ color: "#666", marginBottom: 16 }}>The app couldn&apos;t start. Trying again usually helps.</p>
          <button onClick={() => reset()} style={{ padding: "8px 16px", borderRadius: 999, border: "1px solid #999", background: "none", cursor: "pointer" }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
