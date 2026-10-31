import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <main data-testid="not-found-page" className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-[#59636B]">This address does not match any RailReady page.</p>
      <Link data-testid="not-found-home-link" to="/" className="mt-4 inline-block font-bold text-[#B32624] underline">Back to start</Link>
    </main>
  );
}
