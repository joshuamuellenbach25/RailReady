import { ShieldAlert } from "lucide-react";
import { useAuth } from "@/lib/auth";
import Calibration from "@/pages/Calibration";

/** Admin-only home for every technical detail (phase 8): calibration data, scores, provenance, hashes. */
export default function Diagnostics() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return (
      <div data-testid="diagnostics-forbidden" className="mx-auto mt-16 max-w-md rounded-xl border border-[#E3E7EA] bg-white p-8 text-center">
        <ShieldAlert aria-hidden className="mx-auto h-8 w-8 text-[#59636B]" />
        <h1 className="mt-3 text-xl font-semibold">This area is for administrators.</h1>
        <p className="mt-1 text-[15px] text-[#59636B]">Ask your office admin if you need something from here.</p>
      </div>
    );
  }
  return (
    <div data-testid="diagnostics-page" className="space-y-4">
      <p className="rounded-xl border border-[#E6D3A8] bg-[#FBF6EA] px-4 py-3 text-[15px] text-[#7A4A00]">
        Diagnostics - technical details for administrators. Elsewhere in RailReady, open &quot;Technical details (admin)&quot; on any item to see its records.
      </p>
      <Calibration />
    </div>
  );
}
