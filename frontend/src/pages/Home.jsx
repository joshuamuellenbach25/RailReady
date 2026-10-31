import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errText } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Public entry page (phase 4). Text-led, plain business styling. Palette: #FFFFFF / #F3F4F4 / text #202428 / dark #22272B / action #B32624 (10.4:1 on white).
const FIELD_APP = process.env.REACT_APP_FIELD_APP_URL || "http://localhost:8081";
const WRAP = "mx-auto w-full max-w-[1160px] px-5 md:px-6";
const BTN = "rr-focus inline-flex min-h-[48px] items-center justify-center rounded-[3px] border px-5 text-[16px] font-bold transition-colors disabled:cursor-wait disabled:opacity-60";
const RED = `${BTN} border-[#B32624] bg-[#B32624] text-white hover:bg-[#8F1E1C] hover:border-[#8F1E1C]`;
const OUT = `${BTN} border-[#22272B] bg-white text-[#202428] hover:bg-[#F3F4F4]`;
// Business contact details come from configuration only; empty rows (and the whole block when both are empty) are omitted.
const CONTACT = [["Email", (process.env.REACT_APP_CONTACT_EMAIL || "").trim(), "email"], ["Phone", (process.env.REACT_APP_CONTACT_PHONE || "").trim(), "phone"]].filter(([, v]) => v);
const NAV = [["#how", "How it works"], ["#handles", "Workflow"], ["#example", "Example job"], ...(CONTACT.length ? [["#contact", "Contact"]] : [])];

const COLUMNS = [
  ["Capture on site", ["Take photos, dictate voice notes and add typed notes as you inspect.", "Note any areas you couldn’t inspect.", "Tag findings with their track location."]],
  ["Review and estimate", ["AI flags possible issues and missing details.", "Build an estimate from confirmed findings and your pricing.", "Send a proposal for customer approval."]],
  ["Plan the repair", ["Turn accepted proposals into work orders.", "Schedule the crew and coordinate site access."]],
];
const STEPS = [
  ["Inspect the track", "Capture photos, dictate voice notes and add typed notes."],
  ["Review findings", "Check AI suggestions, confirm findings and fill in missing details."],
  ["Build the estimate", "Turn confirmed findings into a complete estimate with scope, quantities and pricing."],
  ["Send the proposal", "The customer can review the work, approve it or request changes."],
  ["Plan the work", "Use the accepted proposal to prepare the work order, schedule and site access."],
];
const CAPTURE = [
  ["Photos and video", "Capture what you see on the track."],
  ["Voice notes", "Dictate naturally as you inspect."],
  ["Typed notes", "Add measurements or anything else you prefer to write down."],
  ["Location tags", "Pin findings to their track location so crews can find them."],
  ["Site details", "Add conditions and other context about the inspection."],
];
const REVIEW = [
  "Never miss a detail with AI-assisted inspections.",
  "Create a complete estimate from confirmed findings.",
  "Send a proposal for customer approval.",
  "Turn accepted work into a work order.",
];
const SHEET = [
  ["Crosstie 7x9x8 ft 6 in hardwood, grade 5", "8 each", "$1,016.00"],
  ["Tie replacement labor", "8 each", "$1,320.00"],
  ["Material handling", "8 each", "$140.00"],
  ["Hi-rail equipment day", "1 day", "$950.00"],
  ["Mobilization", "1 each", "$600.00"],
];

function StartDemo({ label, testid, className }) {
  const { startDemo } = useAuth();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await startDemo();
      nav("/office/jobs");
    } catch (e) {
      setErr(e?.status === 429 ? "Too many workspaces were opened from this network. Wait a minute, then try again." : e?.status >= 500 ? "The workspace did not open. Nothing was changed. Try again in a minute." : errText(e));
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex flex-col gap-2">
      <button type="button" data-testid={testid} onClick={go} disabled={busy} aria-busy={busy || undefined} className={className}>{busy ? "Opening..." : label}</button>
      {err ? <span role="alert" data-testid={`${testid}-error`} className="text-[15px] font-bold text-[#B32624]">{err}</span> : null}
    </span>
  );
}

const H2 = ({ id, children }) => <h2 id={id} className="text-[28px] font-bold leading-tight text-[#202428] md:text-[32px]">{children}</h2>;

export default function Home() {
  const { user } = useAuth();
  return (
    <div data-testid="landing-page" className="min-h-screen bg-white font-[Arial,Helvetica,sans-serif] text-[16px] leading-[1.5] text-[#202428] md:text-[18px]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:p-2">Skip to content</a>
      <header className="border-b border-[#D5D8DA] bg-white">
        <div className={`${WRAP} flex flex-wrap items-center gap-x-8 gap-y-2 py-3`}>
          <Link to="/" data-testid="home-brand" className="rr-focus text-[20px] font-bold tracking-tight">RailReady</Link>
          <nav aria-label="Main" className="order-3 flex w-full flex-wrap gap-x-5 gap-y-1 md:order-none md:w-auto">
            {NAV.map(([h, l]) => <a key={h} href={h} data-testid={`home-nav-${h.slice(1)}`} className="rr-focus inline-flex min-h-[44px] items-center text-[16px] underline-offset-4 hover:underline">{l}</a>)}
          </nav>
          <Link to="/login" data-testid="staff-signin-link" className={`${OUT} ml-auto min-h-[44px] px-4 text-[15px]`}>Sign in</Link>
        </div>
      </header>
      <main id="main">
        <section aria-labelledby="hero-h" className="py-12 md:py-16">
          <div className={WRAP}>
            <h1 id="hero-h" data-testid="landing-title" className="max-w-[880px] text-[36px] font-bold leading-[1.12] md:text-[52px]">Your next estimate starts on site.</h1>
            <p data-testid="landing-one-liner" className="mt-5 max-w-[760px] text-[18px] md:text-[20px]">
              Bring field photos, voice notes and typed notes into one inspection. AI helps flag possible issues and missing details, so your team can turn inspection findings into repair estimates while still on site.
            </p>
            <div className="mt-8 flex flex-wrap items-start gap-3">
              <StartDemo label="See an example" testid="home-view-example-button" className={RED} />
              {CONTACT.length ? <a href="#contact" data-testid="home-discuss-button" className={OUT}>Contact us</a> : null}
            </div>
            {user ? <p className="mt-4 text-[16px]">Signed in as {user.name}. <Link to="/office/jobs" data-testid="landing-continue-link" className="rr-focus font-bold underline">My inspections</Link></p> : null}
          </div>
        </section>

        <section id="handles" aria-labelledby="handles-h" className="scroll-mt-4 bg-[#F3F4F4] py-10 md:py-16">
          <div className={WRAP}>
            <H2 id="handles-h">From inspection to repair</H2>
            <div className="mt-6 grid gap-px border border-[#D5D8DA] bg-[#D5D8DA] md:grid-cols-3">
              {COLUMNS.map(([t, items]) => (
                <div key={t} data-testid={`home-column-${t.split(" ")[0].toLowerCase()}`} className="bg-white p-5 md:p-6">
                  <h3 className="text-[20px] font-bold">{t}</h3>
                  <ul className="mt-3 list-disc space-y-2 pl-5 text-[16px]">{items.map((x) => <li key={x}>{x}</li>)}</ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="how" aria-labelledby="how-h" className="scroll-mt-4 py-10 md:py-16">
          <div className={WRAP}>
            <H2 id="how-h">How it works</H2>
            <ol className="mt-6 grid gap-4 md:grid-cols-5">
              {STEPS.map(([t, d], i) => (
                <li key={t} data-testid={`landing-step-${i + 1}`} className="border-t-2 border-[#22272B] pt-3">
                  <p className="text-[14px] font-bold text-[#4A5056]">Step {i + 1}</p>
                  <p className="font-bold">{t}</p>
                  <p className="mt-1 text-[16px]">{d}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="example" aria-labelledby="example-h" className="scroll-mt-4 bg-[#F3F4F4] py-10 md:py-16">
          <div className={`${WRAP} grid gap-8 lg:grid-cols-12`}>
            <div className="min-w-0 lg:col-span-5">
              <H2 id="example-h">Example inspection</H2>
              <p className="mt-3">Follow a sample inspection from site photo to estimate, customer approval and work order.</p>
              <div className="mt-6 flex flex-wrap items-start gap-3">
                <StartDemo label="Try the demo" testid="open-demo-button" className={RED} />
                <a href={FIELD_APP} target="_blank" rel="noopener noreferrer" data-testid="field-app-link" className={OUT}>Open the field app</a>
              </div>
              <p data-testid="demo-note" className="mt-3 text-[16px]">The demo opens a sample workspace with an inspection, estimate and proposal to explore.</p>
              <p data-testid="field-app-note" className="mt-2 text-[16px]">Capture photos, voice notes and typed notes on your phone. Review the same inspection and prepare the estimate on the website.</p>
            </div>
            <figure data-testid="home-job-sheet" aria-labelledby="example-h" className="min-w-0 border border-[#B9BEC2] bg-white lg:col-span-7">
              <div className="p-4 md:p-5">
                <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[16px] sm:grid-cols-2">
                  <div><dt className="inline font-bold">Customer: </dt><dd className="inline">Cascade Feed &amp; Grain</dd></div>
                  <div><dt className="inline font-bold">Site: </dt><dd className="inline">Spur 1, east of switch</dd></div>
                  <div><dt className="inline font-bold">Confirmed finding: </dt><dd className="inline">8 crossties to replace</dd></div>
                  <div><dt className="inline font-bold">Not inspected: </dt><dd className="inline">Switch area, occupied</dd></div>
                </dl>
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-[15px]">
                    <thead><tr className="border-b border-[#22272B] text-left"><th className="py-1.5">Line</th><th className="py-1.5 text-right">Qty</th><th className="py-1.5 text-right">Amount</th></tr></thead>
                    <tbody>{SHEET.map(([a, b, c]) => <tr key={a} className="border-b border-[#D5D8DA]"><td className="py-1.5 pr-2">{a}</td><td className="py-1.5 text-right">{b}</td><td className="py-1.5 text-right">{c}</td></tr>)}</tbody>
                  </table>
                </div>
                <p className="mt-3 text-[16px]"><b>Total before tax: $4,026.00</b>. <span data-testid="home-job-sheet-status">Status: Draft proposal · Not sent</span></p>
              </div>
            </figure>
          </div>
        </section>

        <section aria-labelledby="control-h" className="py-10 md:py-16">
          <div className={`${WRAP} grid gap-8 md:grid-cols-2`}>
            <div>
              <H2 id="control-h">What you can capture</H2>
              <ul data-testid="home-capture-list" className="mt-4 list-disc space-y-2 pl-5">
                {CAPTURE.map(([t, d]) => <li key={t}><b>{t}:</b> {d}</li>)}
              </ul>
            </div>
            <div>
              <H2 id="review-h">What you can do with each inspection</H2>
              <ul data-testid="home-review-list" className="mt-4 list-disc space-y-2 pl-5">
                {REVIEW.map((x) => <li key={x}>{x}</li>)}
              </ul>
            </div>
          </div>
        </section>

        {CONTACT.length ? (
          <section id="contact" aria-labelledby="contact-h" className="scroll-mt-4 border-t border-[#D5D8DA] bg-[#F3F4F4] py-10 md:py-16">
            <div className={WRAP}>
              <H2 id="contact-h">Contact us</H2>
              <dl data-testid="home-contact-details" className="mt-4 grid max-w-[760px] gap-y-1 text-[16px]">
                {CONTACT.map(([l, v, k]) => (
                  <div key={k}>
                    <dt className="inline font-bold">{l}: </dt>
                    <dd data-testid={`home-contact-${k}`} className="inline break-words">
                      <a href={k === "email" ? `mailto:${v}` : `tel:${v.replace(/[^\d+]/g, "")}`} className="rr-focus underline underline-offset-4">{v}</a>
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
        ) : null}
      </main>
      <footer className="bg-[#22272B] py-8 text-white">
        <div className={`${WRAP} flex flex-wrap items-center gap-x-6 gap-y-3 text-[16px]`}>
          <span className="font-bold">RailReady</span>
          <Link to="/login" data-testid="footer-signin-link" className="rr-focus underline underline-offset-4">Sign in</Link>
          <Link to="/demo" data-testid="footer-demo-link" className="rr-focus underline underline-offset-4">Try the demo</Link>
        </div>
      </footer>
    </div>
  );
}
