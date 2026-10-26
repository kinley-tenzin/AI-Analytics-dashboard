import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router";

import { useCurrentUser } from "../../auth/session";
import { ConversationProvider } from "../../lib/conversation";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * The application frame: sidebar navigation, top bar and the page area. On narrow screens the
 * sidebar becomes a drawer opened from the top bar.
 */
export function AppShell() {
  const user = useCurrentUser();
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Sidebar user={user} open={menuOpen} onClose={closeMenu} />
      {menuOpen && <div className="shell__backdrop" onClick={closeMenu} aria-hidden="true" />}
      <div className="shell__main">
        <TopBar user={user} menuOpen={menuOpen} onMenu={() => setMenuOpen(true)} />
        <main id="main" className="page" tabIndex={-1}>
          {/* Per sign-in: the shell unmounts on sign-out, which forgets the conversation. */}
          <ConversationProvider key={user.username}>
            <Outlet />
          </ConversationProvider>
        </main>
      </div>
    </div>
  );
}
