import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { ChevronDown, LogOut, RotateCcw, Settings2, TrainFront, UserCircle2 } from "lucide-react";
import { errText } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Btn } from "./ui";

const NAV = [
  ["/office/jobs", "Jobs", "nav-jobs"],
  ["/office/inbox", "Inbox", "nav-inbox"],
  ["/office/contracts", "Agreements", "nav-contracts"],
  ["/office/repairs", "Repairs", "nav-repairs"],
];
const SETTINGS_NAV = [
  ["/office/settings/templates", "Checklists", "nav-settings-templates"],
  ["/office/settings/processing", "Photo analysis", "nav-settings-processing"],
];
const ADMIN_NAV = [["/office/diagnostics", "Diagnostics", "nav-diagnostics"]];
const navCls = ({ isActive }) => `rr-focus inline-flex min-h-[44px] items-center rounded-md px-3 text-sm font-medium transition-colors ${isActive ? "bg-[#3A4146] text-white shadow-[inset_0_-2px_0_#B32624]" : "text-[#D5DADF] hover:bg-[#2E3439]"}`;

function ResetDemo() {
  const { resetDemo } = useAuth();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function reset() {
    setBusy(true);
    setErr(null);
    try {
      await resetDemo();
      nav("/office/jobs", { replace: true, state: { reset: Date.now() } });
    } catch (e) {
      setErr(e?.status === 429 ? "Too many resets in a short time. Your jobs are unchanged. Wait a minute, then try again." : errText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex items-center gap-2">
      {err ? <span data-testid="demo-reset-error" role="alert" className="max-w-[260px] text-[13px] font-medium text-[#FFD7D5]">{err}</span> : null}
      <Btn small kind="secondary" icon={RotateCcw} loading={busy} testid="demo-reset-button" onClick={reset}>Reset demo</Btn>
    </div>
  );
}

function AccountMenu() {
  const { user, workspace, signOut } = useAuth();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger data-testid="account-menu-button" className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-md px-2 text-left text-white hover:bg-[#2E3439]">
        <UserCircle2 aria-hidden className="h-5 w-5 shrink-0 text-[#C9CED3]" />
        <span className="hidden leading-tight sm:block">
          <span data-testid="header-user-name" className="block text-sm font-medium">{user?.name}</span>
          <span data-testid="header-user-role" className="block text-xs text-[#AEB6BD]">{user?.role}</span>
        </span>
        <ChevronDown aria-hidden className="h-4 w-4 text-[#AEB6BD]" />
        <span className="sr-only">Account menu</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[220px]">
        <DropdownMenuLabel className="font-normal">
          <span className="block text-sm font-medium text-[#202428]">{user?.name}</span>
          <span className="block text-xs text-[#59636B]">{user?.role} - {workspace?.name}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem data-testid="signout-button" className="min-h-[40px] cursor-pointer gap-2" onSelect={() => { signOut(); window.location.replace("/"); }}>
          <LogOut aria-hidden className="h-4 w-4" />Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function OfficeLayout() {
  const { workspace, isDemo, isForeman, canConfigure, isAdmin } = useAuth();
  const navItems = isForeman ? [["/office/inbox", "My inspections", "nav-inbox"]] : NAV;
  return (
    <div className="min-h-screen bg-[#F3F4F4] text-[#202428]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:p-2">Skip to content</a>
      <header className="bg-[#22272B] text-white">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-1.5 md:px-8">
          <NavLink to="/office/jobs" data-testid="header-brand-link" className="rr-focus flex min-h-[44px] items-center gap-2 rounded text-[17px] font-semibold">
            <TrainFront aria-hidden className="h-5 w-5 text-[#C9CED3]" /> RailReady
            <span data-testid="header-workspace-label" className="hidden text-[13px] font-normal text-[#AEB6BD] sm:inline">{workspace?.name}</span>
          </NavLink>
          <nav aria-label="Office" className="order-3 flex w-full flex-wrap gap-1 sm:order-none sm:w-auto">
            {navItems.map(([to, label, tid]) => (
              <NavLink key={to} to={to} data-testid={tid} className={navCls}>
                {label}
              </NavLink>
            ))}
          </nav>
          {canConfigure ? (
            <nav aria-label="Settings" data-testid="nav-settings" className="order-4 flex w-full flex-wrap items-center gap-1 border-t border-[#3A4146] pt-1 sm:order-none sm:w-auto sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
              <span className="flex items-center gap-1.5 px-1 text-[12px] font-medium uppercase tracking-wide text-[#AEB6BD]"><Settings2 aria-hidden className="h-3.5 w-3.5" />Settings</span>
              {[...SETTINGS_NAV, ...(isAdmin ? ADMIN_NAV : [])].map(([to, label, tid]) => <NavLink key={to} to={to} data-testid={tid} className={navCls}>{label}</NavLink>)}
            </nav>
          ) : null}
          <div className="ml-auto flex items-center gap-2">{isDemo ? <ResetDemo /> : null}<AccountMenu /></div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
