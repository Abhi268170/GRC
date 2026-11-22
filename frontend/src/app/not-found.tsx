import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="display text-4xl">Page not found</h1>
      <p className="text-sm text-muted-foreground">The address may be wrong, or the page may have moved.</p>
      <Link href="/" className="text-sm font-medium underline underline-offset-4">Go to the start page</Link>
    </div>
  );
}
